from pathlib import Path
# -*- coding: utf-8 -*-
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
p = str(Path(__file__).parent / "01_多用户登录" / "openguard_auth.jsonl")
rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
from collections import Counter
print("total", len(rows))
print("endpoints:", Counter(r.get("endpoint") for r in rows))
print("expected_status:", Counter(r.get("expected_status") for r in rows))
print()
print(json.dumps(rows[0], ensure_ascii=False)[:400])
