# -*- coding: utf-8 -*-
"""用「具体数据池」替换 jsonl 里的所有占位符 / 抽象内容（幂等，可重复运行）。

数据池：真实结构 JWT、具体 ID、具体正文、具体附件路径、具体恶意域名。
替换后仍保留说明：token 类加 note「示例值，测试时替换为真实生成值」。
"""
import json, glob, os, base64

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)


def b64u(d: dict) -> str:
    raw = json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwt(claims: dict) -> str:
    h = b64u({"alg": "HS256", "typ": "JWT"})
    p = b64u(claims)
    return f"{h}.{p}.demo_signature_abc123"


# ---------------- 具体数据池 ----------------
ACCESS_ZHANGSAN = jwt({"sub": "usr_8f3a2b1c", "username": "zhangsan", "role": "user", "exp": 1757580800})
ACCESS_LISI     = jwt({"sub": "usr_9c2d4e6f", "username": "lisi", "role": "user", "exp": 1757580800})
ACCESS_ALICE    = jwt({"sub": "usr_a1b2c3d4", "username": "alice", "role": "user", "exp": 1757580800})
ACCESS_ADMIN    = jwt({"sub": "usr_admin01", "username": "admin", "role": "admin", "exp": 1757580800})
ACCESS_FREE     = jwt({"sub": "usr_8f3a2b1c", "username": "zhangsan", "role": "user", "quota_tier": "free", "exp": 1757580800})
ACCESS_EXPIRED  = jwt({"sub": "usr_8f3a2b1c", "username": "zhangsan", "role": "user", "exp": 1600000000})
ACCESS_TAMPERED = jwt({"sub": "usr_8f3a2b1c", "username": "zhangsan", "role": "admin", "exp": 1757580800})[:-17] + "tampered_signature"

REFRESH_VALID = "rf_9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c"
REFRESH_USED  = "rf_9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c"
LLM_PROXY     = "sk-argus-proxy-9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c"

TOKEN_MAP = {
    "<有效access_token>": ACCESS_ZHANGSAN,
    "<有效token>": ACCESS_ZHANGSAN,
    "<登出前的token>": ACCESS_ZHANGSAN,
    "<用户A token>": ACCESS_ALICE,
    "<普通用户token>": ACCESS_LISI,
    "<admin token>": ACCESS_ADMIN,
    "<Free档用户token>": ACCESS_FREE,
    "<过期token>": ACCESS_EXPIRED,
    "<伪造/篡改token>": ACCESS_TAMPERED,
    "<有效refresh_token>": REFRESH_VALID,
    "<已用过的refresh_token>": REFRESH_USED,
    "<LLM_PROXY_TOKEN>": LLM_PROXY,
    "<user_id>": "usr_8f3a2b1c",
    "<slug>": "zhangsan-agent",
    "<uuid8>": "a3f8c2d1",
}

CONTENT_MAP = {
    "任何正文内容": "武汉市加快推进数字经济高质量发展，到2027年数字经济核心产业增加值年均增长10%，打造全国数字经济一线城市。",
    "任何正文": "武汉市加快推进数字经济高质量发展，到2027年数字经济核心产业增加值年均增长10%。",
}

DOMAIN_MAP = {
    "evil.com": "malware-c2.xyz",
}

MEDIA_PATH = "C:/tmp/eval_attachments"  # 附件 path 具体化


def substitute(obj):
    """递归替换 dict/list 中字符串值里的占位符。返回 (是否替换过 token 占位符)。"""
    touched_token = False
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if isinstance(v, str):
                if v == "<评测时生成>" and "name" in obj:
                    obj[k] = f"{MEDIA_PATH}/{obj['name']}"
                    continue
                for old, new in TOKEN_MAP.items():
                    if old in v:
                        v = v.replace(old, new)
                        touched_token = True
                for old, new in CONTENT_MAP.items():
                    if old in v:
                        v = v.replace(old, new)
                for old, new in DOMAIN_MAP.items():
                    if old in v:
                        v = v.replace(old, new)
                obj[k] = v
            elif isinstance(v, (dict, list)):
                touched_token |= substitute(v)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                touched_token |= substitute(v)
    return touched_token


total = 0
changed = 0
for f in sorted(glob.glob("*/*.jsonl")):
    rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
    file_changed = False
    for r in rows:
        touched = substitute(r)
        if touched:
            # token 类样本加说明
            note = r.get("note", "")
            tag = "示例值，测试时替换为真实生成值"
            if tag not in note:
                r["note"] = (note + "｜" + tag).strip("｜")
        file_changed = True
    with open(f, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    total += len(rows)
    changed += file_changed

# 校验：还有没有残留占位符（排除 <script> 合法内容）
remain = 0
for f in sorted(glob.glob("*/*.jsonl")):
    for l in open(f, encoding="utf-8"):
        if not l.strip():
            continue
        s = json.dumps(json.loads(l), ensure_ascii=False)
        for m in __import__("re").finditer(r"<[^>]{1,40}>", s):
            if m.group(0) in ("<script>", "</script>"):
                continue
            remain += 1
print(f"替换完成：共处理 {total} 条")
print(f"残留占位符（排除 <script>）：{remain}")
