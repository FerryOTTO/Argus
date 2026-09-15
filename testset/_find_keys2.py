# -*- coding: utf-8 -*-
import json, sqlite3, sys
sys.stdout.reconfigure(encoding="utf-8")
p = r"<仓库根目录>\terminal\configs\remote.json"
d = json.load(open(p, encoding="utf-8"))
def scrub(o, k=""):
    if isinstance(o, dict):
        return {kk: ("***" if any(s in kk.lower() for s in ("key", "token", "secret", "password")) else scrub(vv, kk)) for kk, vv in o.items()}
    if isinstance(o, list):
        return [scrub(i) for i in o]
    if isinstance(o, str) and o.startswith("sk-"):
        return "***"
    return o
print("remote.json:", json.dumps(scrub(d), ensure_ascii=False, indent=2)[:1200])
print()
db = r"<仓库根目录>\gateway\data\llmgate.db"
con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
cur = con.cursor()
cur.execute("SELECT id,name,display_name,provider_type,api_base_url,api_key,is_active FROM providers")
for r in cur.fetchall():
    key = r[5] or ""
    keymask = (key[:7] + "..." + key[-4:]) if key else "(empty)"
    print("provider:", r[0], r[1], r[2], r[3], r[4], keymask, "active=", r[6])
con.close()
