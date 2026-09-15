# -*- coding: utf-8 -*-
"""从 jsonl 动态重建 4 份文档，条数/覆盖率全部对齐，杜绝硬编码过期数字。

生成：输入输出对照.md、预期输出对照表.csv（Excel 友好 BOM）
更新：README.md、测试场景手册_通俗版.md 的条数与覆盖说明

可重复运行（幂等）。
"""
import json, glob, csv, os, re

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)

MOD = {
    "openguard_auth.jsonl": "多用户登录",
    "io_guard_input.jsonl": "输入安全",
    "io_guard_output.jsonl": "输出安全",
    "io_guard_content.jsonl": "上下文安全",
    "retrieval_guard.jsonl": "检索安全",
    "tool_guard_intent.jsonl": "工具安全",
    "access_control_matrix.jsonl": "访问控制",
    "sandbox_harm_detector.jsonl": "沙箱执行",
    "media_input.jsonl": "附件防护",
    "audit_events.synthetic.jsonl": "日志审计",
}

# 加载全部
data = {}
for f in sorted(glob.glob("*/*.jsonl")):
    fn = os.path.basename(f)
    with open(f, encoding="utf-8") as fh:
        data[fn] = [json.loads(l) for l in fh if l.strip()]

total = sum(len(v) for v in data.values())
real = sum(1 for v in data.values() for r in v
           if re.search(r"-(r|w)\d+$", r.get("id") or ""))
counts = {MOD[fn]: len(v) for fn, v in data.items()}

def summary(fn, r):
    p = r.get("payload", {})
    if fn.startswith("openguard"):
        req = json.dumps(r.get("request", {}), ensure_ascii=False)
        if len(req) > 55: req = req[:52] + "..."
        return (f"{r.get('method','')} {r.get('endpoint','')} {req}",
                f"HTTP {r.get('expected_status','')} — {r.get('expected','')}")
    if fn.startswith("io_guard"):
        s = p.get("text") or p.get("content") or ""
        e = r.get("expected_action", "")
        if r.get("expected_label"): e += f" / {r.get('expected_label','')}"
        return (s, e)
    if fn.startswith("retrieval"):
        return (f"URL={p.get('url','')}  内容={p.get('content','')}",
                r.get("expected_action", ""))
    if fn.startswith("tool_guard"):
        chain = " → ".join(f"{t.get('tool_name','')}" for t in p.get("tool_chain", []))
        cur = f"{p.get('tool_name','')}({json.dumps(p.get('arguments',{}),ensure_ascii=False)})"
        s = f"意图={p.get('original_prompt','')}"
        if chain: s += f"  链={chain}"
        s += f"  当前={cur}"
        return (s, r.get("expected_action", ""))
    if fn.startswith("access_control"):
        c = r.get("context", {})
        pre = f" 前序拦截={len(c.get('pre_events', []))}次" if c.get("pre_events") else ""
        s = f"{c.get('user_id','')} 调 {p.get('tool_name','')}({json.dumps(p.get('arguments',{}),ensure_ascii=False)})" + pre
        return (s, r.get("expected_action", ""))
    if fn.startswith("sandbox"):
        return (p.get("command", ""),
                f"{r.get('expected_severity','')} 是否拦截={r.get('expected_blocked','')} 规则={r.get('expected_pattern','') or '—'}")
    if fn.startswith("media"):
        atts = "; ".join(f"{a.get('name','')}" for a in p.get("attachments", []))
        return (f"{p.get('text','')}  附件→ {atts}", r.get("expected_action", ""))
    if fn.startswith("audit"):
        return (f"{r.get('source_module','')}.{r.get('action','')}  {r.get('reason','')}",
                r.get("expected", "校验审计写入/查询/图构建"))
    return ("", r.get("expected_action", ""))

# ---- 1. 输入输出对照.md ----
md = ["# 测试集 输入 → 预期输出 对照表", "",
      f"共 {total} 条，含 {real} 条基于真实政府文件的案例（中央文件 id 含 -r，武汉市政府文件 id 含 -w）。", ""]
for fn in sorted(data):
    rows = data[fn]
    md += ["", f"## {MOD[fn]}（{len(rows)} 条）", ""]
    for r in rows:
        rid = r.get("id") or r.get("event_id", "")
        cat = r.get("category", "")
        inp, exp = summary(fn, r)
        md.append(f"### {rid}  [{cat}]")
        md.append(f"- 输入：{inp}")
        md.append(f"- 预期输出：{exp}")
        md.append("")
open("输入输出对照.md", "w", encoding="utf-8").write("\n".join(md))

# ---- 2. 预期输出对照表.csv ----
csv_rows = [["id", "文件", "category", "输入摘要", "预期输出", "说明"]]
for fn in sorted(data):
    for r in data[fn]:
        rid = r.get("id") or r.get("event_id", "")
        cat = r.get("category", "")
        inp, exp = summary(fn, r)
        inp = inp.replace("\n", " ").strip()
        if len(inp) > 60: inp = inp[:57] + "..."
        csv_rows.append([rid, fn, cat, inp, exp, r.get("note", "")])
with open("预期输出对照表.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh)
    w.writerows(csv_rows)

# ---- 3. 更新 README.md ----
t = open("README.md", encoding="utf-8").read()
# 目录树条数（动态，从 data 计算，杜绝硬编码过期）
tree = {fn: len(rows) for fn, rows in data.items()}
for fn, n in tree.items():
    t = re.sub(rf"({re.escape(fn)}\s+\S*?)\s*\d+ 条", rf"\1 {n} 条", t)
# 统计表（文件名后紧跟 | 数字 |）
for fn, n in tree.items():
    t = re.sub(rf"({re.escape(fn)}\s*\|\s*)\d+(\s*\|)", rf"\g<1>{n}\g<2>", t)
# 总条数（正则，任意旧值都能匹配）
t = re.sub(r"共 \*\*\d+ 条样本\*\*", f"共 **{total} 条样本**", t)
t = re.sub(r"\| \| \| \*\*合计\*\* \| \*\*\d+\*\* \|", f"| | | **合计** | **{total}** |", t)
t = re.sub(r"\*\*10 道安检 \+ \d+ 条带标准答案的考题\*\*", f"**10 道安检 + {total} 条带标准答案的考题**", t)
t = re.sub(r"(\S*输入输出对照\.md\s+)\d+( 条「输入 → 预期输出」完整对照)", rf"\g<1>{total}\g<2>", t)
# 模块覆盖说明（新增能力）
t = t.replace(
    "样本文件：`01_多用户登录/openguard_auth.jsonl`，测了注册/登录/刷新/登出/会话/多租户隔离/管理员权限/配额/限流/SSO 共 10 类。",
    "样本文件：`01_多用户登录/openguard_auth.jsonl`，测了注册/登录/刷新/登出/会话/多租户隔离/管理员权限(改角色·禁用账号·删除用户·用量)/配额/限流/SSO/过期与篡改 token/聊天会话 共 12 类。")
t = t.replace(
    "样本文件：`03_访问控制/access_control_matrix.jsonl`，测了四级密级 × 工具 × 路径 × 数据库矩阵、MAC/hybrid 模式、通配符与特例规则。",
    "样本文件：`03_访问控制/access_control_matrix.jsonl`，测了四级密级 × 工具 × 路径 × 数据库矩阵、MAC/hybrid 模式、通配符与特例规则，以及**审计风险联动二次审批 human_review**（频发试探→防线升级→转人工审批）。")
t = t.replace(
    "样本文件：`09_日志审计/audit_events.synthetic.jsonl`，测了攻击链/正常链/时序链/多用户/频发试探触发风险联动等审计事件。",
    "样本文件：`09_日志审计/audit_events.synthetic.jsonl`，测了攻击链/正常链/时序链/多用户/频发试探触发风险联动等审计事件；每条自带 `category`+`expected` 标准答案（验证图构建、风险源命中、human_review 升级）。")
open("README.md", "w", encoding="utf-8", newline="").write(t)

# ---- 4. 更新测试场景手册_通俗版.md ----
h = open("测试场景手册_通俗版.md", encoding="utf-8").read()
for fn, n in tree.items():
    h = re.sub(rf"(`{re.escape(fn)}`（)\d+( 条）)", rf"\g<1>{n}\g<2>", h)
    h = re.sub(rf"({re.escape(fn)}\s*\|\s*)\d+(\s*\|)", rf"\g<1>{n}\g<2>", h)
h = re.sub(r"\| \*\*合计\*\* \| \| \*\*\d+\*\* \|", f"| **合计** | | **{total}** |", h)
h = re.sub(r"(`输入输出对照\.md` —— )\d+( 条样本的「输入 → 预期输出」完整对照)",
           rf"\g<1>{total}\g<2>", h)
open("测试场景手册_通俗版.md", "w", encoding="utf-8", newline="").write(h)

print("=" * 60)
print(f"文档重建完成：总条数 {total}，真实案例 {real} 条")
print("  输入输出对照.md         已重建")
print("  预期输出对照表.csv      已重建（Excel 友好）")
print("  README.md              条数+覆盖说明 已更新")
print("  测试场景手册_通俗版.md   条数 已更新")
