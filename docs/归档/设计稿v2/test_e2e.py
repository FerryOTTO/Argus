"""
Argus 访问控制 — 端到端测试（E2E）
============================================================
测试路径：用户 → OpenGuard (:3000) → check() → OpenClaw (:18789)

前置条件：
  1. OpenClaw 在 :18789 运行
  2. OpenGuard 在 :3000 运行
  3. 数据库中有不同 security_level 的测试用户

用法：
  py -3 test_e2e.py
"""
import sys
import io
import json
import urllib.request
import urllib.error

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:3000"
PASSWORD = "test12345"

# 测试用例：(用户名, 请求路径, 期望结果, 测试说明)
# 资源规则：/channels→4, /nodes→4, /models/config→4, /admin/*→4, /agent→1
CASES = [
    # ── 管理员 (top_secret=4) ──
    ("adminuser", "/agent",         200, "管理员访问 /agent"),
    ("adminuser", "/channels",      200, "管理员访问 /channels（等级4≥4且role=admin）"),
    ("adminuser", "/nodes",         200, "管理员访问 /nodes"),

    # ── secret=3 用户 ──
    ("robertwright", "/agent",      200, "secret用户访问 /agent"),
    ("robertwright", "/channels",   403, "secret用户访问 /channels（等级3<4，且非admin）"),

    # ── internal=2 用户 ──
    ("benjaminsmith", "/agent",     200, "internal用户访问 /agent"),
    ("benjaminsmith", "/channels",  403, "internal用户访问 /channels（等级2<4）"),
    ("benjaminsmith", "/nodes",     403, "internal用户访问 /nodes（等级2<4）"),

    # ── public=1 用户 ──
    ("williamsims", "/agent",       200, "public用户访问 /agent（需1）"),
    ("williamsims", "/channels",    403, "public用户访问 /channels（等级1<4）"),
    ("williamsims", "/nodes",       403, "public用户访问 /nodes（等级1<4）"),
    ("williamsims", "/",            200, "public用户访问根路径（需1）"),
]

_results = []


def login(username: str) -> str:
    """用用户名+密码登录，返回 access_token"""
    data = json.dumps({"username": username, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{BASE}/auth/login",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
            return body["access_token"]
    except urllib.error.HTTPError as e:
        print(f"  ❌ 登录失败: {username} → {e.code} {e.read().decode()}")
        raise


def run_case(username: str, path: str, expect_code: int, desc: str) -> bool:
    """通过代理请求路径，验证 HTTP 状态码"""
    try:
        token = login(username)
    except Exception:
        return False

    # 通过 /api/openclaw 前缀请求
    url = f"{BASE}/api/openclaw{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            actual = resp.status
    except urllib.error.HTTPError as e:
        actual = e.code
        # 读取 Argus 返回的拦截原因
        try:
            detail = json.loads(e.read())
            reason = detail.get("detail", {}).get("reason", str(detail))
        except Exception:
            reason = str(e)

    ok = actual == expect_code
    mark = "✅" if ok else "❌"
    status_str = "ALLOW" if actual < 400 else "BLOCK"
    expect_str = "ALLOW" if expect_code < 400 else "BLOCK"
    extra = ""
    if not ok:
        extra = f"  [期望 {expect_code} 实际 {actual}]"
    elif actual >= 400 and "reason" in dir():
        extra = f"  reason: {reason}"

    print(f"  {mark} {desc}")
    print(f"     user={username} path={path} → 期望{expect_str} 实际{status_str}{extra}")
    return ok


# ============================================================
print("=" * 72)
print("       🛡️  Argus 端到端测试")
print("=" * 72)
print(f"  OpenGuard:  {BASE}")
print(f"  OpenClaw:   http://127.0.0.1:18789")
print(f"  测试用例:   {len(CASES)} 项")
print()

results = []
for username, path, expect, desc in CASES:
    results.append(run_case(username, path, expect, desc))

print(f"\n{'=' * 72}")
print(f"  结果: {sum(results)}/{len(results)} 通过")
print("=" * 72)

sys.exit(0 if all(results) else 1)
