"""Step 6c: token 消耗账本（插件 llm_output 钩子记的真实消耗）。

写入方：argus-adapter 插件（网关进程内内存账本）经 POST /v1/local/usage/ingest
批量上报；落盘 runtime/usage/usage.jsonl（append-only，一行一条）。
读取方：GET /v1/local/usage（按模型聚合累计）与 GET /v1/desktop/runtime
（today/7d/30d 三段曲线，结构与旧审计桶一致，前端零改）。
无数据时返回全零，不估算、不编数。
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1/local/usage", tags=["local-usage"])

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
USAGE_PATH = os.path.join(ROOT, "runtime", "usage", "usage.jsonl")


def _num(value: Any) -> float:
    try:
        f = float(value or 0)
        return f if f > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _append(records: List[Dict[str, Any]]) -> int:
    if not records:
        return 0
    os.makedirs(os.path.dirname(USAGE_PATH), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    with open(USAGE_PATH, "a", encoding="utf-8") as f:
        for r in records:
            if not isinstance(r, dict):
                continue
            total = _num(r.get("total")) or (
                _num(r.get("input")) + _num(r.get("output"))
                + _num(r.get("cacheRead")) + _num(r.get("cacheWrite"))
            )
            if total <= 0:
                continue
            f.write(json.dumps({
                "model": str(r.get("model") or "unknown"),
                "input": _num(r.get("input")),
                "output": _num(r.get("output")),
                "cacheRead": _num(r.get("cacheRead")),
                "cacheWrite": _num(r.get("cacheWrite")),
                "total": total,
                "at": str(r.get("at") or now),
            }, ensure_ascii=False) + "\n")
            n += 1
    return n


def _load(limit: int = 5000) -> List[Dict[str, Any]]:
    try:
        if not os.path.exists(USAGE_PATH):
            return []
        with open(USAGE_PATH, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return []
    out = []
    for ln in lines[-limit:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if isinstance(r, dict) and _num(r.get("total")) > 0:
            out.append(r)
    return out


def _parse_at(value: Any) -> Optional[datetime]:
    """Parse ISO timestamps and epoch timestamps emitted by the adapter."""
    try:
        if isinstance(value, (int, float)) and value > 0:
            epoch = float(value)
            if epoch > 10_000_000_000:  # adapter uses JavaScript Date.now() milliseconds
                epoch /= 1000
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        raw = str(value).strip()
        if raw.isdigit():
            epoch = float(raw)
            if epoch > 10_000_000_000:
                epoch /= 1000
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def read_usage_buckets() -> Dict[str, List[Dict[str, Any]]]:
    """today（按小时）/ 7d / 30d（按天）三段曲线；聚合全模型。"""
    now = datetime.now(timezone.utc)
    day_start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    m30_start = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
    hour_start = now.replace(minute=0, second=0, microsecond=0)

    n_hours = max(1, int((now - hour_start).total_seconds() // 3600) + 1)
    today = [{"time": (hour_start + timedelta(hours=i)).strftime("%H:00"),
              "input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0,
              "cost": 0, "requests": 0} for i in range(n_hours)]
    d7 = [{"time": (day_start + timedelta(days=i)).strftime("%m/%d"),
           "input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0,
           "cost": 0, "requests": 0} for i in range(7)]
    d30 = [{"time": (m30_start + timedelta(days=i)).strftime("%m/%d"),
            "input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0,
            "cost": 0, "requests": 0} for i in range(30)]

    for r in _load():
        at = _parse_at(r.get("at"))
        if at is None:
            continue
        inp, outp = _num(r.get("input")), _num(r.get("output"))
        cwrite, cread = _num(r.get("cacheWrite")), _num(r.get("cacheRead"))
        hi = int((at - hour_start).total_seconds() // 3600)
        if 0 <= hi < len(today):
            p = today[hi]
            p["input"] += inp
            p["output"] += outp
            p["cacheCreate"] += cwrite
            p["cacheRead"] += cread
            p["requests"] += 1
        d7i = (at.date() - day_start.date()).days
        if 0 <= d7i < 7:
            p = d7[d7i]
            p["input"] += inp
            p["output"] += outp
            p["cacheCreate"] += cwrite
            p["cacheRead"] += cread
            p["requests"] += 1
        d30i = (at.date() - m30_start.date()).days
        if 0 <= d30i < 30:
            p = d30[d30i]
            p["input"] += inp
            p["output"] += outp
            p["cacheCreate"] += cwrite
            p["cacheRead"] += cread
            p["requests"] += 1
    return {"today": today, "7d": d7, "30d": d30}


class UsageIngestBody(BaseModel):
    records: List[Dict[str, Any]] = []


@router.post("/ingest")
def ingest_usage(body: UsageIngestBody):
    """插件批量上报（网关内存账本 -> 落盘）。返回写入条数。"""
    n = _append(body.records or [])
    return {"ok": True, "written": n}


@router.get("")
def get_usage():
    """按模型聚合累计（个人版首页用量下拉框/卡片用）。"""
    agg: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"input": 0.0, "output": 0.0, "cacheRead": 0.0,
                 "cacheWrite": 0.0, "total": 0.0, "calls": 0}
    )
    for r in _load():
        m = str(r.get("model") or "unknown")
        a = agg[m]
        a["input"] += _num(r.get("input"))
        a["output"] += _num(r.get("output"))
        a["cacheRead"] += _num(r.get("cacheRead"))
        a["cacheWrite"] += _num(r.get("cacheWrite"))
        a["total"] += _num(r.get("total"))
        a["calls"] += 1
    models = [{"model": m, **{k: (int(v) if k == "calls" else v) for k, v in a.items()}}
              for m, a in sorted(agg.items())]
    total = sum(a["total"] for a in agg.values())
    return {"data": {"models": models, "total": total,
                     "calls": sum(a["calls"] for a in agg.values())}}
