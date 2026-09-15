from pathlib import Path
# -*- coding: utf-8 -*-
import json, sys, sqlite3
sys.stdout.reconfigure(encoding="utf-8")
p = str(Path(__file__).parent / "05_检索安全" / "retrieval_guard.jsonl")
rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
from collections import Counter
print("total", len(rows))
print("category:", Counter(r["category"] for r in rows))
print("expected:", Counter(r["expected_action"] for r in rows))
print()
print("by category x expected:")
c = Counter((r["category"], r["expected_action"]) for r in rows)
for k, v in sorted(c.items()):
    print("  %-26s %-8s %d" % (k[0], k[1], v))
print()
for r in rows[:3]:
    print(json.dumps(r, ensure_ascii=False)[:260])
