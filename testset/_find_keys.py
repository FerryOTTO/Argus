# -*- coding: utf-8 -*-
import os, re, sqlite3, sys, json
sys.stdout.reconfigure(encoding="utf-8")
ROOTS = [r"<仓库根目录>\terminal", r"<仓库根目录>\gateway", r"<仓库根目录>\desktop"]
pat = re.compile(r"(sk-[A-Za-z0-9_\-]{10,})")
hits = []
for root in ROOTS:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "release"}]
        for fn in filenames:
            if not fn.lower().endswith((".env", ".yaml", ".yml", ".json", ".txt", ".toml", ".ini", ".bat", ".ps1")):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(fp) > 2_000_000:
                    continue
                t = open(fp, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            for m in pat.finditer(t):
                hits.append((fp, m.group(1)[:8] + "..." + m.group(1)[-4:]))
for h in hits[:40]:
    print(h[0], "->", h[1])
print("total key-like hits:", len(hits))
print("---- db providers ----")
db = r"<仓库根目录>\gateway\data\llmgate.db"
if os.path.exists(db):
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tabs = [r[0] for r in cur.fetchall()]
        print("tables:", tabs)
        for t in tabs:
            if "provider" in t.lower() or "key" in t.lower():
                cur.execute("PRAGMA table_info(%s)" % t)
                cols = [c[1] for c in cur.fetchall()]
                print(t, cols)
        con.close()
    except Exception as e:
        print("db error", e)
