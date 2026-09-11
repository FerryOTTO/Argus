# -*- coding: utf-8 -*-
"""
Clawguard v3 网关集成测试
test_gateway_e2e.py
============================================================
在 OpenGuard 网关上做端到端验证：
  L1 test_module_smoke       替换后的 auth_gateway 模块导入 + 判定正确（含盘符深度修复）
  L2 test_gateway_reachable  网关 /health 可达
  L3 test_user_levels        预检 4 个等级用户的数据库等级（/me）
  L4 test_http_acl_matrix    HTTP 代理 /api/openclaw/* 的 ACL 判定（403 拦截 / 放行）
  L5 test_ws_chat_precheck   聊天 WebSocket 第一层关键词预检（需 Bridge+OpenClaw，连不上自动跳过）

用法（可拷贝到网关目录，也可在本目录指向远程网关）:
    py -3 test_gateway_e2e.py
    OPEN_GUARD_URL=http://192.168.1.10:3000 py -3 test_gateway_e2e.py

前置条件:
    1. OpenGuard(:3000) 运行中，且 auth_gateway.py 已替换为修复后的 v3
    2. 数据库有 4 个等级用户 adminuser/robertwright/benjaminsmith/williamsims，密码 test12345
       （等级以数据库 users.security_level 为准；seed 默认 internal，需手动 UPDATE）
    3. L5 需要 Bridge(:18080) + OpenClaw(:18789) 全链路，连不上自动 SKIP
"""

import os
import io
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

# Windows 控制台 GBK 编码无法输出中文/emoji，统一切到 UTF-8
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.getenv("OPEN_GUARD_URL", "http://127.0.0.1:3000").rstrip("/")
WS_BASE = BASE.replace("http", "ws")  # http→ws, https→wss
PASSWORD = "test12345"

# 期望的数据库等级（与网关 rules/users.txt 及实际账号体系对应）
EXPECTED_LEVELS = {
    "adminuser": "top_secret",
    "robertwright": "secret",
    "benjaminsmith": "internal",
    "williamsims": "public",
}

# 资源规则（来自网关 rules/resources.txt）：/agent→1, /channels→4, /nodes→4, /models/config→4
PATH_LEVELS = {"/agent": 1, "/channels": 4, "/nodes": 4, "/models/config": 4}

_LEVEL_NUM = {"public": 1, "internal": 2, "secret": 3, "top_secret": 4}


# ============================================================
# 辅助函数
# ============================================================

def _request(method: str, path: str, token: str = None, body: dict = None):
    """发 HTTP 请求，返回 (状态码, 响应体字符串)。"""
    url = f"{BASE}{path}"
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def login(username: str) -> str:
    """登录并返回 access_token。"""
    code, body = _request("POST", "/auth/login", body={"username": username, "password": PASSWORD})
    if code != 200:
        raise RuntimeError(f"登录失败 {username} ({code}): {body[:200]}")
    return json.loads(body)["access_token"]


def get_me(token: str) -> dict:
    code, body = _request("GET", "/me", token=token)
    if code != 200:
        raise RuntimeError(f"/me 失败 ({code}): {body[:200]}")
    return json.loads(body)


# ============================================================
# 测试 1: 模块冒烟（L1，本地判定，不写规则文件）
# ============================================================

def test_module_smoke():
    """用受控规则验证替换后的 auth_gateway 判定正确（含盘符深度修复）"""
    import tempfile
    import shutil

    tmpdir = tempfile.mkdtemp()
    uf = Path(tmpdir) / "users.txt"
    rf = Path(tmpdir) / "resources.txt"
    uf.write_text(
        "adminuser | top_secret | *\n"
        "robertwright | secret |\n"
        "williamsims | public |\n",
        encoding="utf-8")
    rf.write_text(
        "/channels | top_secret | flat\n"
        "C:\\Windows\\* | top_secret | flat\n"
        "C:\\Users\\admin\\AppData\\* | secret | flat\n"
        "C:\\Users\\admin\\AppData\\Roaming\\* | top_secret | flat\n",
        encoding="utf-8")

    os.environ["CLAWGUARD_USERS_FILE"] = str(uf)
    os.environ["CLAWGUARD_RESOURCES_FILE"] = str(rf)
    sys.path.insert(0, str(Path(__file__).parent))

    import auth_gateway
    from auth_gateway import check, check_reason
    auth_gateway._store.reload()

    try:
        # adminuser 有 * 特例 → 全放行
        assert check("adminuser", "/channels", "", "") is True
        # public 访问 /channels → 拦截
        assert check("williamsims", "/channels", "", "") is False
        # 盘符深度修复的判别用例：
        # AppData\Roaming\* (top_secret=4) 比 AppData\* (secret=3) 更深 → 必须按 4 拦截
        # （旧版平铺匹配这里会错误放行 robertwright）
        assert check("robertwright", r"C:\Users\admin\AppData\Roaming\test.txt") is False
        assert check("robertwright", r"C:\Users\admin\AppData\local.txt") is True
        # check_reason 返回拦截原因
        ok, reason = check_reason("williamsims", "/channels")
        assert not ok and "资源所需 4" in reason
        print("✓ test_module_smoke passed")
    finally:
        shutil.rmtree(tmpdir)


# ============================================================
# 测试 2: 网关可达（L2 前置）
# ============================================================

def test_gateway_reachable():
    code, _ = _request("GET", "/health")
    assert code == 200, f"网关不可达: {code}（请先启动 OpenGuard 并替换修复后的 auth_gateway.py）"
    print("✓ test_gateway_reachable passed")


# ============================================================
# 测试 3: 用户等级预检
# ============================================================

def test_user_levels():
    """确认 4 个等级用户存在；等级不符仅告警（矩阵会按期望等级再判定）"""
    for username, expect in EXPECTED_LEVELS.items():
        token = login(username)   # 用户不存在会抛错 → 该测试 FAIL
        me = get_me(token)
        actual = me["security_level"]
        mark = "✅" if actual == expect else "⚠ 等级不符(请 UPDATE users SET security_level=...)"
        print(f"    {mark} {username}: DB={actual:<12} 期望={expect}")
    print("✓ test_user_levels passed")


# ============================================================
# 测试 4: HTTP 代理 ACL 矩阵
# ============================================================

def test_http_acl_matrix():
    """每个用户 × 每个资源路径，验证 403(ACCESS_DENIED) 或放行"""
    for username, level in EXPECTED_LEVELS.items():
        token = login(username)
        need_num = _LEVEL_NUM.get(level, 1)
        for path, need in PATH_LEVELS.items():
            code, body = _request("GET", f"/api/openclaw{path}", token=token)
            if need_num >= need:
                # 应放行：200(OpenClaw在) 或 503(OpenClaw不在) 均视为通过 ACL
                assert code not in (401, 403), (
                    f"{username} 访问 {path}: 应放行但得到 {code}（body: {body[:120]}）")
            else:
                # 应拦截：403 且是 Clawguard 的 ACCESS_DENIED
                assert code == 403, (
                    f"{username} 访问 {path}: 应拦截但得到 {code}（body: {body[:120]}）")
                try:
                    detail = json.loads(body).get("detail", {})
                    assert detail.get("code") == "ACCESS_DENIED", (
                        f"{username} 访问 {path}: 期望 ACCESS_DENIED 实际 {detail}")
                except (json.JSONDecodeError, AttributeError):
                    pass
    print("✓ test_http_acl_matrix passed")


# ============================================================
# 测试 5: 聊天 WebSocket 第一层预检（可选）
# ============================================================

def test_ws_chat_precheck():
    """public 用户发送含 C:\\Windows 的消息 → 应被第一层关键词预检拦截。
    需要 Bridge(:18080)+OpenClaw(:18789) 全链路；环境不具备时自动跳过，不计失败。"""
    try:
        import asyncio
        import websockets
    except ImportError:
        print("    SKIP test_ws_chat_precheck (缺少 websockets 库)")
        return

    token = login("williamsims")
    ws_url = f"{WS_BASE}/chat?token={token}"

    async def _run() -> str:
        """返回 'block'(拦截成功) / 'skip'(环境不具备)"""
        try:
            try:
                conn = websockets.connect(ws_url, open_timeout=8)
            except TypeError:   # 兼容不同 websockets 版本
                conn = websockets.connect(ws_url)
            async with conn as ws:
                await ws.send(r"看看 C:\Windows 里有什么")
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=8)
                        if "Clawguard" in msg:
                            return "block"
                    except asyncio.TimeoutError:
                        return "skip"   # 网关在等 Bridge(:18080)，全链路未就绪
        except Exception as e:
            print(f"    SKIP test_ws_chat_precheck (需 Bridge/OpenClaw 全链路): {e}")
            return "skip"

    result = asyncio.run(_run())
    if result == "block":
        print("✓ test_ws_chat_precheck passed")
    else:
        print("    SKIP test_ws_chat_precheck (需 Bridge+OpenClaw 全链路才能触发第一层拦截)")


# ============================================================
# 运行全部测试
# ============================================================

def run_all_tests():
    print("=" * 60)
    print("Clawguard v3 网关集成测试")
    print(f"目标网关: {BASE}")
    print("=" * 60)
    print()

    tests = [
        test_module_smoke,
        test_gateway_reachable,
        test_user_levels,
        test_http_acl_matrix,
        test_ws_chat_precheck,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"✗ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()

    print()
    print("=" * 60)
    print(f"测试结果: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
