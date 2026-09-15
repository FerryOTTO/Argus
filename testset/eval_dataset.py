# -*- coding: utf-8 -*-
"""Argus 评测运行框架（可直接运行版）。

把 test/ 下的 10 个 jsonl 数据集按功能送进 Argus 对应安全模块，
比对「实际结果 vs 标准答案」，输出命中率 / 混淆矩阵 / Recall / Precision / FPR。

用法：
    python eval_dataset.py --dataset io_guard_input
    python eval_dataset.py --all
    python eval_dataset.py --all --limit 20

前置条件（按模块）：
    需先定位 Argus 仓库（自动探测，或用 --repo / 环境变量 ARGUS_REPO 指定），
    并在该仓库内 pip install 好依赖（见 offline_subset.md）。

    io_guard_input/output/content  : 本地模型头已随仓库提交，可离线
    access_control_matrix          : 先在 rules/users.txt 配好 u_public/u_internal/u_secret/u_admin
                                     等级 1/2/3/4；risk_escalation 类会写临时审计事件触发联动
    sandbox_harm_detector          : 纯正则，零依赖
    retrieval_guard                : B 层注入需 torch + PIGuard；A/C 层 + empty_or_error 可离线
    tool_guard_intent              : 需配置 TOOL_GUARD_LLM_*（或注入 fake detector）
    media_input                    : PDF 抽取需 pymupdf，图片 OCR 需 RapidOCR
    audit_events.synthetic         : 离线，验证事件写入/图构建/风险联动升级
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

ACTION_SET = {"allow", "rewrite", "block", "human_review"}

# 当前被测仓库路径（_setup_repo 时记录，部分 runner 需要按仓库找模型/规则文件）
REPO: Path | None = None

# 环境缺件导致「没测」的用例：{原因: [用例 id]}，不算实现问题，单独列出来
NOT_COVERED: dict[str, list[str]] = {}

# 逐条判定结果（summarize 时填充，--dump 时落盘）
DETAILS: list[dict] = []


# ---------------------------------------------------------------------------
# 仓库定位
# ---------------------------------------------------------------------------

def _detect_repo() -> Path | None:
    env = os.getenv("ARGUS_REPO")
    candidates = []
    if env:
        candidates.append(Path(env))
    # 本测试集随 Argus 仓库一起分发时，直接按相对位置探测（<仓库根>/terminal）。
    # 其它情况一律用 --repo 或 ARGUS_REPO 显式指定。
    candidates += [
        Path(__file__).resolve().parent.parent / "terminal",
    ]
    for c in candidates:
        if (c / "argus").exists():
            return c
    return None


def _setup_repo(repo: str | None) -> Path:
    global REPO
    r = Path(repo).resolve() if repo else _detect_repo()
    if r is None or not (r / "argus").exists():
        print("✗ 未找到 Argus 仓库：请用 --repo 或环境变量 ARGUS_REPO 指定。", file=sys.stderr)
        sys.exit(2)
    REPO = r
    s = str(r)
    if s not in sys.path:
        sys.path.insert(0, s)
    return r


# ---------------------------------------------------------------------------
# 数据集加载
# ---------------------------------------------------------------------------

def load_dataset(name: str) -> list[dict]:
    """按文件名在 test/ 子目录里找 jsonl。"""
    matches = [p for p in BASE.rglob(f"{name}.jsonl")]
    if not matches:
        raise FileNotFoundError(f"未找到数据集 {name}.jsonl")
    path = matches[0]
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def judge(actual: str, expected: str) -> bool:
    return actual == expected


def summarize(name: str, rows: list[dict], outcomes: list[tuple[dict, str, bool]]):
    DETAILS.append({
        "dataset": name,
        "items": [
            {
                "id": r.get("id"),
                "category": r.get("category"),
                "expected_action": r.get("expected_action"),
                "actual_action": actual,
                "hit": hit,
                "stage": r.get("stage"),
            }
            for r, actual, hit in outcomes
        ],
    })
    total = len(rows)
    ok = sum(1 for _r, _a, hit in outcomes if hit)
    by_cat = defaultdict(lambda: [0, 0])
    for r, _a, hit in outcomes:
        by_cat[r.get("category", "?")][0] += hit
        by_cat[r.get("category", "?")][1] += 1

    cm = defaultdict(Counter)
    for r, actual, _hit in outcomes:
        cm[r.get("expected_action", "?")][actual] += 1

    pos = sum(1 for r in rows if r.get("expected_action") not in ("allow", None))
    tp = sum(1 for r, a, _h in outcomes if r.get("expected_action") not in ("allow", None) and a not in ("allow", None))
    fp = sum(1 for r, a, _h in outcomes if r.get("expected_action") == "allow" and a != "allow")
    fn = pos - tp
    recall = tp / pos if pos else 1.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    fpr = fp / (total - pos) if (total - pos) else 0.0

    print(f"\n{'=' * 62}\n[{name}] 共 {total} 条，命中 {ok}，命中率 {ok/total*100:.1f}%")
    if pos:
        print(f"拦截类：Recall={recall:.2%}  Precision={precision:.2%}  FPR={fpr:.2%}")
    print("按 category：")
    for cat, (o, t) in sorted(by_cat.items()):
        print(f"  {cat:<36} {o}/{t}")
    print("混淆矩阵（行=期望，列=实际）：")
    print("  " + f"{'期望/实际':<14}" + "".join(f"{a:<14}" for a in sorted(ACTION_SET)))
    for exp in sorted(cm):
        print("  " + f"{exp:<14}" + "".join(f"{cm[exp].get(a, 0):<14}" for a in sorted(ACTION_SET)))

    if NOT_COVERED:
        total_missing = sum(len(v) for v in NOT_COVERED.values())
        if total_missing:
            print(f"未覆盖 {total_missing} 条（环境缺件，非判定失败）：")
            for reason, ids in NOT_COVERED.items():
                print(f"  {reason}: {len(ids)} 条 -> {', '.join(ids)}")
            print(f"  实际已测 {total - total_missing} 条命中 {ok} "
                  f"({ok/max(total - total_missing, 1)*100:.1f}%)")
    NOT_COVERED.clear()
    return ok, total


# ---------------------------------------------------------------------------
# 各模块 runner
# ---------------------------------------------------------------------------

def run_io_guard(rows: list[dict]) -> list[tuple[dict, str, bool]]:
    from fastapi.testclient import TestClient
    from argus.api.main import app
    client = TestClient(app)
    outcomes = []
    for r in rows:
        body = {
            "context": {"trace_id": f"eval-{r['id']}", "session_id": "eval",
                        "user_id": "eval", "stage": r["stage"],
                        "timestamp": "2026-09-10T00:00:00+08:00"},
            "payload": r["payload"],
        }
        resp = client.post(f"/v1/{r['stage']}/check", json=body)
        actual = resp.json()["action"] if resp.status_code == 200 else "error"
        outcomes.append((r, actual, judge(actual, r["expected_action"])))
    return outcomes


def run_retrieval_guard(rows: list[dict]) -> list[tuple[dict, str, bool]]:
    import asyncio
    from argus.adapters.retrieval_guard_adapter import RetrievalGuardAdapter
    from argus.common.models import RequestContext, SecurityRequest

    # B 层（PIGuard 注入检测）模型体积大、被 .gitignore 排除，仓库里 models/ 只有 .gitkeep。
    # 有模型就三层全开；没模型就把 B 关掉，只测 A（URL 白名单）+ C（提示词包装），
    # 依赖 B 才能判定的注入类用例单独记为「未覆盖」，不混进命中率。
    model_dir = (REPO or Path(".")) / "argus" / "modules" / "retrieval_guard" / "models"
    model_ok = any(
        p.is_dir() and any(p.iterdir())
        for p in (model_dir.glob("*") if model_dir.exists() else [])
    )
    adapter = RetrievalGuardAdapter(guards={"B": model_ok})

    outcomes = []
    for r in rows:
        req = SecurityRequest(context=RequestContext(stage="content"),
                              payload=r["payload"])
        res = asyncio.run(adapter.run(req))
        # A 层先跑：凡是「该拦、A 层没拦下来」的，都是要 B 层才能判的注入类
        needs_b = (not model_ok) and r["expected_action"] == "block" and res.action != "block"
        hit = judge(res.action, r["expected_action"])
        if needs_b and not hit:
            NOT_COVERED.setdefault("B 层 PIGuard 模型未部署（仓库 models/ 为空）", []).append(r["id"])
        outcomes.append((r, res.action, hit))
    return outcomes


def run_tool_guard(rows: list[dict]) -> list[tuple[dict, str, bool]]:
    import asyncio
    from argus.adapters.tool_guard_adapter import ToolGuardAdapter
    from argus.common.models import RequestContext, SecurityRequest
    from argus.modules.tool_guard.session_store import ToolSessionStore
    adapter = ToolGuardAdapter(on_error="block")
    outcomes = []
    for r in rows:
        p = r["payload"]
        store = ToolSessionStore()
        store.set_prompt("eval-session", p["original_prompt"])
        for call in p["tool_chain"]:
            store.record_call("eval-session", call["tool_name"], call["arguments"])
        adapter._store = store
        req = SecurityRequest(
            context=RequestContext(session_id="eval-session", stage="tool_pre"),
            payload={"tool_name": p["tool_name"], "arguments": p["arguments"]},
        )
        res = asyncio.run(adapter.run(req))
        outcomes.append((r, res.action, judge(res.action, r["expected_action"])))
    return outcomes


def run_access_control(rows: list[dict]) -> list[tuple[dict, str, bool]]:
    from argus.adapters.access_control_adapter import AccessControlAdapter
    from argus.common.models import RequestContext, SecurityRequest
    from argus.modules.access_control.risk_link import AuditRiskMonitor, DynamicLinePolicy
    from argus.modules.access_control.quarantine_store import QuarantineStore
    from argus.modules.audit.original.storage import record_audit_event, AuditStore

    outcomes = []
    static_adapter = AccessControlAdapter(risk_link_enabled=False)

    for r in rows:
        user_id = r["context"]["user_id"]
        payload = r["payload"]

        if r.get("category") == "risk_escalation":
            # 写临时审计事件触发风险联动，再以 risk_link 开启态判定
            with tempfile.TemporaryDirectory() as tmp:
                from datetime import datetime, timedelta, timezone
                path = Path(tmp) / "audit.jsonl"
                now = datetime.now(timezone.utc)
                for i, pre in enumerate(r["context"].get("pre_events", [])):
                    ts = now - timedelta(seconds=10 + i)
                    record_audit_event({
                        "event_id": f"seed-{r['id']}-{i}",
                        "trace_id": f"seed-{r['id']}",
                        "session_id": "eval",
                        "user_id": user_id,
                        "timestamp": ts.isoformat(),
                        "stage": "tool_pre",
                        "source_module": "access_control",
                        "action": pre.get("action", "block"),
                        "risk_score": pre.get("risk_score", 1.0),
                        "reason": "seeded probe",
                        "content": {"tool_name": "execute_bash"},
                        "metadata": {"sequence": i + 1},
                    }, path=path)
                monitor = AuditRiskMonitor(store=AuditStore(path))
                adapter = AccessControlAdapter(risk_monitor=monitor,
                                               risk_policy=DynamicLinePolicy(),
                                               risk_link_enabled=True,
                                               quarantine_store=QuarantineStore(
                                                   Path(tmp) / "quarantine.json"))
                req = SecurityRequest(
                    context=RequestContext(user_id=user_id, session_id="eval", stage="tool_pre"),
                    payload=payload,
                )
                res = adapter.run_sync(req)
                actual = res["action"] if isinstance(res, dict) else res.action
        else:
            req = SecurityRequest(
                context=RequestContext(user_id=user_id, stage="tool_pre"),
                payload=payload,
            )
            res = static_adapter.run_sync(req)
            actual = res["action"] if isinstance(res, dict) else res.action

        outcomes.append((r, actual, judge(actual, r["expected_action"])))
    return outcomes


def run_sandbox(rows: list[dict]) -> list[tuple[dict, str, bool]]:
    from harm_detector import HarmDetector
    det = HarmDetector()
    outcomes = []
    for r in rows:
        report = det.scan(r["payload"]["command"], source="command")
        severity = report.severity.value
        ok = (severity == r["expected_severity"]
              and report.blocked == r["expected_blocked"])
        outcomes.append((r, severity, ok))
    return outcomes


def run_media(rows: list[dict]) -> list[tuple[dict, str, bool]]:
    from fastapi.testclient import TestClient
    from argus.api.main import app
    client = TestClient(app)
    outcomes = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for r in rows:
            payload = {"text": r["payload"]["text"], "attachments": []}
            for att in r["payload"]["attachments"]:
                content = att.get("content", "")
                fpath = tmp_path / att["name"]
                _materialize(fpath, att["name"], content)
                payload["attachments"].append(
                    {"name": att["name"], "path": str(fpath),
                     "mime_type": att.get("mime_type")})
            body = {"context": {"trace_id": f"eval-{r['id']}", "session_id": "eval",
                                "user_id": "eval", "stage": "input",
                                "timestamp": "2026-09-10T00:00:00+08:00"},
                    "payload": payload}
            resp = client.post("/v1/input/check", json=body)
            actual = resp.json()["action"] if resp.status_code == 200 else "error"
            outcomes.append((r, actual, judge(actual, r["expected_action"])))
    return outcomes


def _materialize(path: Path, name: str, content: str) -> None:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".csv", ".md"}:
        path.write_text(content, encoding="utf-8")
    elif suffix == ".pdf":
        try:
            import pymupdf as fitz
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), content)
            doc.save(str(path)); doc.close()
        except Exception:
            path.write_text(content, encoding="utf-8")
    elif suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        try:
            from PIL import Image
            Image.new("RGB", (60, 30), "white").save(str(path))
        except Exception:
            pass
    else:
        path.write_text(content, encoding="utf-8")


def run_audit(rows: list[dict]) -> list[tuple[dict, str, bool]]:
    """验证：事件写入可查、每 trace 可建图、风险联动升级链路正确。"""
    from argus.modules.audit.original import AuditQuery, record_audit_event
    from argus.modules.audit.original.storage import AuditStore
    outcomes = []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "audit.jsonl"
        for r in rows:
            record_audit_event(r, path=path)
        query = AuditQuery(store=AuditStore(path))

        for r in rows:
            eid = r["event_id"]
            cat = r.get("category", "")
            ok = query.get_event(eid) is not None
            if cat == "attack_chain":
                # 攻击链：应有可达的直接风险源（risk≥阈值）
                ok = ok and any(
                    e["risk_score"] >= query.threshold
                    for e in query.events(trace_id=r["trace_id"])
                )
            elif cat == "escalation":
                # 频发试探链：应包含 human_review 升级，或"升级后仍放行"的 risk_escalated 事件
                trace_events = query.events(trace_id=r["trace_id"])
                ok = ok and any(
                    e["action"] == "human_review"
                    or "risk_escalated" in e.get("reason", "")
                    for e in trace_events
                )
            actual = "ok" if ok else "fail"
            outcomes.append((r, actual, ok))
    return outcomes


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

RUNNERS = {
    "io_guard_input": run_io_guard,
    "io_guard_output": run_io_guard,
    "io_guard_content": run_io_guard,
    "retrieval_guard": run_retrieval_guard,
    "tool_guard_intent": run_tool_guard,
    "access_control_matrix": run_access_control,
    "sandbox_harm_detector": run_sandbox,
    "media_input": run_media,
    "audit_events.synthetic": run_audit,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Argus 评测运行框架")
    parser.add_argument("--dataset", choices=list(RUNNERS),
                        help="单个数据集（不含 .jsonl 后缀）")
    parser.add_argument("--all", action="store_true", help="运行全部数据集")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条")
    parser.add_argument("--repo", default=None, help="Argus 仓库路径（覆盖自动探测）")
    parser.add_argument("--dump", default=None, help="逐条判定结果写入的 JSON 路径")
    args = parser.parse_args()

    if not args.dataset and not args.all:
        parser.print_help()
        return 1

    _setup_repo(args.repo)
    # sandbox runner 需要 sandbox_mcp/original 在 path 上
    repo = _detect_repo() if not args.repo else Path(args.repo).resolve()
    if repo:
        sys.path.insert(0, str(repo / "sandbox_mcp" / "original"))

    names = list(RUNNERS) if args.all else [args.dataset]
    grand_ok = grand_total = 0
    for name in names:
        rows = load_dataset(name)
        if args.limit:
            rows = rows[: args.limit]
        outcomes = RUNNERS[name](rows)
        ok, total = summarize(name, rows, outcomes)
        grand_ok += ok
        grand_total += total
    if len(names) > 1:
        print(f"\n总命中 {grand_ok}/{grand_total} ({grand_ok/grand_total*100:.1f}%)")
    if args.dump:
        Path(args.dump).write_text(
            json.dumps(DETAILS, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"逐条结果已写入 {args.dump}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
