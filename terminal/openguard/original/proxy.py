# proxy.py — HTTP + WebSocket 反向代理（agentClaw 风格）
#
# 特性：
#   1. 注入 X-Agent-Id + HMAC 签名（防篡改）
#   2. Admin 路径保护（channels, nodes, models/config）
#   3. WebSocket keepalive + 重试连接 + 空闲超时
#   4. 代理前释放 DB 连接
import asyncio
import hashlib
import hmac
import os
import httpx
from fastapi import Request, Response, HTTPException
from config import config
from middleware import auth_middleware, get_clawguard_headers
from database import find_agent_by_user

OPENCLAW_URL = config.openclaw_url.rstrip("/")
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:18080").rstrip("/")
_client: httpx.AsyncClient | None = None

# 需要 admin 权限的路径前缀
ADMIN_ONLY_PATHS = ["/channels", "/nodes", "/models/config"]


def _sign_agent_id(agent_id: str) -> str:
    """HMAC-SHA256 签名 agent_id，防止篡改"""
    if not config.bridge_token:
        return ""
    return hmac.new(
        config.bridge_token.encode(),
        agent_id.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]


def bridge_ws_url(agent_id: str) -> str:
    """构建带 HMAC 签名的 Bridge 接入 URL（bridge.js 会校验）。"""
    import time
    from urllib.parse import urlencode
    ts = int(time.time() * 1000)
    sig = hmac.new(
        config.bridge_token.encode(),
        f"openguard:{agent_id}:{ts}".encode(),
        hashlib.sha256,
    ).hexdigest()[:16]
    qs = urlencode({"agentId": agent_id, "ts": str(ts), "sig": sig})
    base = config.bridge_url
    return base + ("&" if "?" in base else "?") + qs


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    return _client


async def shutdown_proxy():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _build_target_path(request: Request) -> str:
    """转换路径：/api/openclaw/xxx → /xxx，同时移除 token 参数"""
    path = request.url.path
    # 去掉 /api/openclaw 前缀，保留 /xxx
    if path.startswith("/api/openclaw"):
        path = path[len("/api/openclaw"):] or "/"
    elif path.startswith("/api"):
        # 兼容旧前缀 /api/xxx
        path = path[4:] or "/"
    # 重建 query string，去掉 token
    params = [(k, v) for k, v in request.query_params.items() if k != "token"]
    qs = "&".join(f"{k}={v}" for k, v in params)
    return path + ("?" + qs if qs else "")


async def proxy_to_openclaw(request: Request) -> Response:
    """HTTP 代理：验证 JWT → 注入 X-Agent-Id + HMAC → 转发到 OpenClaw"""
    user = await auth_middleware(request)

    # 获取用户默认 Agent ID
    agent = await find_agent_by_user(user.user_id)
    agent_id = agent["agent_id"] if agent else "unknown"
    agent_sig = _sign_agent_id(agent_id)

    target_path = _build_target_path(request)

    # Admin 路径保护
    if user.role != "admin":
        target_normalized = target_path.split("?")[0]
        for protected in ADMIN_ONLY_PATHS:
            if target_normalized.startswith(protected):
                raise HTTPException(
                    status_code=403,
                    detail={"error": "此路径需要管理员权限", "code": "FORBIDDEN"}
                )

    body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None

    # 注入 Agent ID + 签名 + 用户信息 + Clawguard 身份头
    headers = {
        "X-Agent-Id": agent_id,
        "X-Agent-Id-Sig": agent_sig,
        "x-forwarded-user": user.username,
        "x-forwarded-user-id": user.user_id,
        "x-forwarded-session-id": user.session_id,
        "x-forwarded-security-level": user.security_level,
        "x-forwarded-for": request.client.host if request.client else "127.0.0.1",
    }
    # 注入 Clawguard 统一身份头（对接方案 7.7）
    headers.update(get_clawguard_headers(user))
    if user.role == "admin":
        headers["X-Is-Admin"] = "true"

    # 透传原始 content-type
    ct = request.headers.get("content-type")
    if ct:
        headers["content-type"] = ct

    client = _get_client()
    try:
        resp = await client.request(
            method=request.method,
            url=f"{OPENCLAW_URL}{target_path}",
            headers=headers,
            content=body,
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail={"error": "OpenClaw 服务不可用，请稍后重试", "code": "UPSTREAM_DOWN"}
        )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
        media_type=resp.headers.get("content-type"),
    )


# ====== WebSocket 代理 ======

from starlette.websockets import WebSocket


async def ws_proxy(websocket: WebSocket) -> None:
    """WebSocket 代理：验证 JWT → 注入 X-Agent-Id → 连接 OpenClaw

    增强特性：
      - 重试连接（最多 5 次，每次间隔 2 秒）
      - keepalive ping/pong（每 30 秒，pong 超时 10 秒）
      - 空闲超时 120 秒
    """
    import websockets as ws

    # 从请求中提取 Token（cookie 优先，其次 query）
    token = websocket.cookies.get("token") or websocket.query_params.get("token")
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if not token:
        await websocket.close(code=4001, reason="Token missing")
        return

    # 验证 JWT
    from auth import verify_access_token
    from session_store import session_store
    try:
        payload = verify_access_token(token)
    except Exception:
        await websocket.close(code=4001, reason="Token invalid")
        return

    if not await session_store.validate_session(payload["sid"]):
        await websocket.close(code=4001, reason="Session invalid")
        return

    # 获取 Agent ID
    agent = await find_agent_by_user(payload["sub"])
    agent_id = agent["agent_id"] if agent else "unknown"
    agent_sig = _sign_agent_id(agent_id)

    await websocket.accept()

    # WebSocket 连接 URL（包含路径，与 HTTP 代理一致）
    ws_path = websocket.url.path
    if ws_path.startswith("/api/openclaw"):
        ws_path = ws_path[len("/api/openclaw"):] or "/"
    elif ws_path.startswith("/api"):
        ws_path = ws_path[4:] or "/"
    qs = websocket.url.query
    if qs:
        ws_path += "?" + qs
    ws_url = OPENCLAW_URL.replace("http://", "ws://").replace("https://", "wss://") + ws_path
    headers = {
        "X-Agent-Id": agent_id,
        "X-Agent-Id-Sig": agent_sig,
        "x-forwarded-user": payload["username"],
        "x-forwarded-user-id": payload["sub"],
        "x-forwarded-session-id": payload["sid"],
        "x-forwarded-security-level": payload.get("security_level", "internal"),
    }
    # 注入 Clawguard 统一身份头（对接方案 7.7）
    headers.update(get_clawguard_headers(payload))
    if payload.get("role") == "admin":
        headers["X-Is-Admin"] = "true"

    max_retries = 5
    retry_delay = 2
    idle_timeout = 120
    ping_interval = 30
    pong_timeout = 10

    for attempt in range(max_retries):
        try:
            async with ws.connect(ws_url, additional_headers=headers) as target:
                print(f"[WS Proxy] {payload['username']} connected (agent={agent_id}, attempt={attempt+1})")

                last_activity = asyncio.get_event_loop().time()

                async def keepalive():
                    """每 30s ping 一次，检测 pong 超时（10s）"""
                    nonlocal last_activity
                    while True:
                        await asyncio.sleep(ping_interval)
                        now = asyncio.get_event_loop().time()
                        # 如果超过 120s 无活动，关闭连接
                        if now - last_activity >= idle_timeout:
                            print(f"[WS Proxy] {payload['username']} idle timeout ({idle_timeout}s)")
                            break
                        try:
                            pong_waiter = await target.ping()
                            await asyncio.wait_for(pong_waiter, timeout=pong_timeout)
                            last_activity = asyncio.get_event_loop().time()
                        except asyncio.TimeoutError:
                            print(f"[WS Proxy] {payload['username']} pong timeout")
                            break
                        except ws.ConnectionClosed:
                            break

                async def forward_to_target():
                    nonlocal last_activity
                    try:
                        while True:
                            data = await websocket.receive()
                            last_activity = asyncio.get_event_loop().time()
                            if data["type"] == "websocket.disconnect":
                                return
                            await target.send(data.get("text") or data.get("bytes") or "")
                    except Exception:
                        pass

                async def forward_from_target():
                    nonlocal last_activity
                    try:
                        async for message in target:
                            last_activity = asyncio.get_event_loop().time()
                            await websocket.send_text(message if isinstance(message, str) else message.decode())
                    except ws.ConnectionClosed:
                        pass

                keepalive_task = asyncio.ensure_future(keepalive())
                done, pending = await asyncio.wait(
                    [asyncio.ensure_future(forward_to_target()),
                     asyncio.ensure_future(forward_from_target()),
                     keepalive_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                return  # success

        except (ConnectionRefusedError, OSError) as e:
            print(f"[WS Proxy] Attempt {attempt+1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
            else:
                await websocket.close(code=4002, reason=str(e))
        except Exception as e:
            print(f"[WS Proxy] Error: {e}")
            await websocket.close(code=4002, reason=str(e))
            return
