from pathlib import Path
# -*- coding: utf-8 -*-
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "terminal"))
from argus.adapters.access_control_adapter import AccessControlAdapter
from argus.common.models import RequestContext, SecurityRequest
a = AccessControlAdapter(risk_link_enabled=False)
p = Path(__file__).parent / "03_访问控制" / "access_control_matrix.jsonl"
rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
bad = 0
for r in rows:
    if r.get("category") == "risk_escalation":
        continue
    req = SecurityRequest(context=RequestContext(user_id=r["context"]["user_id"], stage="tool_pre"), payload=r["payload"])
    res = a.run_sync(req)
    act = res["action"] if isinstance(res, dict) else res.action
    if act != r["expected_action"]:
        bad += 1
        pl = r["payload"]
        arg = pl.get("arguments", {})
        path = str(arg.get("path", ""))[:32]
        print("%-22s exp=%-6s act=%-6s user=%-12s tool=%-16s path=%-34s db=%s" % (
            r["id"], r["expected_action"], act, r["context"]["user_id"],
            str(pl.get("tool_name")), path, pl.get("database", "")))
print("mismatch", bad)
