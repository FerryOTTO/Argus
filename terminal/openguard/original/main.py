# main.py — OpenGuard FastAPI 主入口
import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.websockets import WebSocket

from config import config
from database import init_db, close_db
from session_store import session_store
from message_store import message_store
from routes import router as auth_router
from proxy import proxy_to_openclaw, ws_proxy, shutdown_proxy


# Jinja2 模板
templates = Jinja2Templates(directory=str(config.template_dir))


def _render(template_name: str, request: Request) -> HTMLResponse:
    """安全渲染模板，绕过 Starlette TemplateResponse 的缓存 bug"""
    template = templates.get_template(template_name)
    return HTMLResponse(template.render({"request": request}))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    await init_db()

    # users.txt 已下线：等级只存用户库，执法侧从 auth.db 动态回查，启动不再写本地规则文件。
    print(f"\n{'='*50}")
    print(f"  OpenGuard Auth Gateway")
    print(f"  Port:        {config.port}")
    print(f"  OpenClaw:    {config.openclaw_url}")
    print(f"  Clawguard:   {config.clawguard_url}")
    print(f"  Bridge:      {config.bridge_url}")
    print(f"  Session:     {'Redis' if config.redis_url else 'JSON file'}")
    print(f"  SQLite:      {config.sqlite_path}")
    print(f"  Bridge Token: {'*' * 16}")
    print(f"  Admin User:  {config.admin_username or '(env ADMIN_USERNAME)'}")
    print(f"{'='*50}")
    print(f"  Frontend:  http://localhost:{config.port}/")
    print(f"  Register:  POST /auth/register")
    print(f"  Login:     POST /auth/login")
    print(f"  Admin API: GET  /api/admin/users")
    # 初始化 APScheduler - 每周一零点触发配额重置
    scheduler = AsyncIOScheduler()

    async def weekly_quota_reset():
        print(f"[Quota] Weekly quota reset triggered at {datetime.now()}", flush=True)

    scheduler.add_job(
        weekly_quota_reset,
        trigger=CronTrigger(day_of_week='mon', hour=0, minute=0, second=0),
        id='weekly_quota_reset',
        replace_existing=True,
    )
    scheduler.start()
    print("[Scheduler] APScheduler started, weekly quota reset on Monday 00:00 UTC")

    print(f"{'='*50}\n")
    yield
    # 关闭
    scheduler.shutdown(wait=False)
    await shutdown_proxy()
    await close_db()


app = FastAPI(title="OpenGuard Auth Gateway", lifespan=lifespan)

# Mount static files
static_dir = str(config.static_dir)
if Path(static_dir).exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ====== ① 认证 + Admin + Agent 路由（最高优先级）======
app.include_router(auth_router)

# ====== ①.5 LLM 密钥集中代理（/llm/v1/*，agentClaw 风格）======
from llm_proxy import router as llm_router
from skills_routes import router as skills_user_router, admin_router as skills_admin_router
app.include_router(llm_router)
app.include_router(skills_user_router)
app.include_router(skills_admin_router)


# ====== ② 前端页面 ======

from middleware import CSRF_COOKIE, generate_csrf_token

def _set_csrf(response: HTMLResponse, request: Request) -> HTMLResponse:
    """为页面响应设置 CSRF Cookie（如未有则生成）"""
    existing = request.cookies.get(CSRF_COOKIE)
    if not existing:
        response.set_cookie(
            key=CSRF_COOKIE,
            value=generate_csrf_token(),
            samesite="lax", path="/", httponly=False,
        )
    return response


@app.get("/", include_in_schema=False)
async def index(request: Request):
    token = request.cookies.get("token")
    if token:
        try:
            from auth import verify_access_token
            jwt_payload = verify_access_token(token)
            if await session_store.validate_session(jwt_payload["sid"]):
                return RedirectResponse(url="/dashboard", status_code=302)
        except Exception:
            pass
    return _set_csrf(_render("login.html", request), request)


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    return _set_csrf(_render("login.html", request), request)


@app.get("/register", include_in_schema=False)
async def register_page(request: Request):
    return _set_csrf(_render("login.html", request), request)


@app.get("/dashboard", include_in_schema=False)
async def dashboard_page(request: Request):
    return _set_csrf(_render("dashboard.html", request), request)


@app.get("/admin", include_in_schema=False)
async def admin_page(request: Request):
    return _set_csrf(_render("admin.html", request), request)


# ====== ③ 聊天 WebSocket ======

@app.websocket("/chat")
async def chat_ws(websocket: WebSocket):
    """浏览器聊天端点：验证 JWT → 连接持久 Bridge → 双向转发"""
    import websockets as ws
    from auth import verify_access_token
    from session_store import session_store
    from database import find_agent_by_user

    token = websocket.query_params.get("token") or websocket.cookies.get("token")
    if not token:
        await websocket.close(code=4001, reason="Token missing")
        return

    try:
        jwt_payload = verify_access_token(token)
    except Exception:
        await websocket.close(code=4001, reason="Token invalid")
        return

    if not await session_store.validate_session(jwt_payload["sid"]):
        await websocket.close(code=4001, reason="Session invalid")
        return

    agent = await find_agent_by_user(jwt_payload["sub"])
    openclaw_agent = agent["agent_id"] if agent else "main"
    req_session = websocket.query_params.get("session", "")
    # 规范 session key（agentClaw 约定）：复用旧 main 会话时自动重定向到用户自己的 agent
    from middleware import to_openclaw_session_key
    openclaw_session = to_openclaw_session_key(req_session, openclaw_agent)
    username = jwt_payload["username"]

    await websocket.accept()
    print(f"[Chat] {username} connected (session={openclaw_session})")

    # 连接持久 Bridge，双向转发（Bridge 已维持与 OpenClaw 的长连接）
    bridge_ws_url = config.bridge_url

    async def bridge_to_browser():
        ai_text = ""
        while True:
            try:
                raw = await bridge.recv()
                msg = json.loads(raw)
                if msg.get("type") == "event":
                    evt = msg.get("event", "")
                    payload = msg.get("payload", {})
                    if evt == "agent":
                        data = payload.get("data", {})
                        # 处理错误（如模型不可用、API Key 无效等）
                        phase = data.get("phase", "")
                        if phase == "error":
                            err_msg = data.get("error", "Unknown error")
                            await websocket.send_text(f"\n[Error: {err_msg}]")
                            print(f"[Chat] Agent error for {username}: {err_msg}")
                            ai_text = ""
                            continue
                        full = data.get("text", "")
                        if not full and isinstance(data.get("content"), list):
                            full = "".join(
                                b.get("text", "") for b in data["content"]
                                if b.get("type") == "text"
                            )
                        if full and len(full) > len(ai_text):
                            delta = full[len(ai_text):]
                            ai_text = full
                            await websocket.send_text(delta)
                    elif evt == "bridge.disconnected":
                        if ai_text.strip():
                            await message_store.save_message(
                                jwt_payload["sub"], openclaw_session, "assistant", ai_text)
                        await websocket.send_text("\n[Bridge 重连中...]")
                        ai_text = ""
                elif msg.get("type") == "res":
                    if not msg.get("ok"):
                        err = msg.get("error", {}).get("message", "unknown")
                        await websocket.send_text(f"\n[Error: {err}]")
            except Exception as e:
                print(f"[Chat] bridge_to_browser error: {type(e).__name__}: {e}")
                if ai_text.strip():
                    await message_store.save_message(
                        jwt_payload["sub"], openclaw_session, "assistant", ai_text)
                break

    bridge_retries = 3
    last_error = None
    for attempt in range(bridge_retries):
        try:
            from proxy import bridge_ws_url
            signed_bridge_url = bridge_ws_url(openclaw_agent)
            async with ws.connect(signed_bridge_url) as bridge:
                print(f"[Chat] {username} Bridge connected (attempt={attempt+1})")

                async def browser_to_bridge():
                    nonlocal last_browser_activity
                    while True:
                        try:
                            data = await websocket.receive_text()
                            last_browser_activity = asyncio.get_event_loop().time()
                            # 持久化用户消息
                            await message_store.save_message(
                                jwt_payload["sub"], openclaw_session, "user", data)
                            await bridge.send(json.dumps({
                                "type": "req", "id": str(uuid.uuid4()),
                                "method": "agent",
                                "params": {
                                    "agentId": openclaw_agent,
                                    "sessionKey": openclaw_session,
                                    "message": data,
                                    "idempotencyKey": str(uuid.uuid4())
                                }
                            }))
                        except Exception as e:
                            print(f"[Chat] browser_to_bridge error: {type(e).__name__}: {e}")
                            break

                # 连接治理（agentClaw 风格）：30s ping 保活 bridge；浏览器 300s 无活动判死
                last_browser_activity = asyncio.get_event_loop().time()

                async def keepalive():
                    nonlocal last_browser_activity
                    while True:
                        await asyncio.sleep(30)
                        now = asyncio.get_event_loop().time()
                        if now - last_browser_activity >= 300:
                            print(f"[Chat] {username} idle timeout (300s)")
                            break
                        try:
                            pong_waiter = await bridge.ping()
                            await asyncio.wait_for(pong_waiter, timeout=10)
                        except Exception:
                            print(f"[Chat] {username} bridge pong timeout")
                            break

                async def _wrap_bridge_to_browser():
                    try:
                        await bridge_to_browser()
                    finally:
                        pass

                done, pending = await asyncio.wait(
                    [asyncio.ensure_future(browser_to_bridge()),
                     asyncio.ensure_future(_wrap_bridge_to_browser()),
                     asyncio.ensure_future(keepalive())],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                # 等待取消生效，避免悬空协程继续引用已关闭的 bridge/websocket
                await asyncio.gather(*pending, return_exceptions=True)
            break  # success
        except (ConnectionRefusedError, OSError, Exception) as e:
            last_error = e
            err_name = type(e).__name__
            print(f"[Chat] Bridge attempt {attempt+1}/{bridge_retries} failed: {err_name}: {e}")
            if attempt < bridge_retries - 1:
                await asyncio.sleep(2)
            else:
                await websocket.send_text(f"\n[Error: 无法连接到 OpenClaw Bridge，请检查服务是否启动]")

    print(f"[Chat] {username} disconnected")


# ====== ④ 健康检查 ======

import time as _time

@app.get("/health")
async def health():
    """健康检查：自身状态 + Bridge 连通性 + Clawguard 连通性（对接方案 8.1）"""
    bridge_ok = False
    clawguard_ok = False
    try:
        import websockets as _ws
        async with _ws.connect(config.bridge_url) as _:
            bridge_ok = True
    except Exception:
        pass

    try:
        import httpx as _httpx
        _no_proxy = {"http://": _httpx.AsyncHTTPTransport(), "https://": _httpx.AsyncHTTPTransport()}
        async with _httpx.AsyncClient(
            timeout=3, trust_env=False,
            transport=_httpx.AsyncHTTPTransport(), mounts=_no_proxy,
        ) as c:
            r = await c.get(f"{config.clawguard_url}/health")
            clawguard_ok = r.status_code == 200
    except Exception:
        pass

    modules = {
        "auth": "ok",
        "session": "ok",
        "proxy": "ok",
        "bridge": "ok" if bridge_ok else "error",
        "clawguard": "ok" if clawguard_ok else "error",
    }
    all_ok = bridge_ok and clawguard_ok
    return {
        "status": "ok" if all_ok else "degraded",
        "service": "openguard",
        "modules": modules,
        "timestamp": int(_time.time()),
    }


# ====== ④.5 Favicon ======

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    favicon_path = config.static_dir / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(str(favicon_path))
    return Response(status_code=404)


# ====== ⑤ HTTP 代理：/api/openclaw/* → OpenClaw ======
@app.api_route("/api/openclaw/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def api_proxy(request: Request):
    return await proxy_to_openclaw(request)


# ====== ⑤.5 WebSocket 代理：/api/openclaw/* ======
@app.websocket("/api/openclaw/{path:path}")
async def api_ws_proxy(websocket: WebSocket):
    await ws_proxy(websocket)


# ====== ⑥ 兜底代理：所有其他请求 → OpenClaw ======
# 排除静态资源路径，避免被转发到 OpenClaw
_STATIC_ONLY = {"/favicon.ico", "/robots.txt"}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def catchall_proxy(request: Request):
    if request.url.path in _STATIC_ONLY:
        return Response(status_code=404)
    # /api/admin/* 及其他未匹配的 /api/ 接口（除 /api/openclaw/* 外）禁止回落到 OpenClaw SPA 产生 HTML 响应
    if request.url.path.startswith("/api/admin/") or (request.url.path.startswith("/api/") and not request.url.path.startswith("/api/openclaw/")):
        return JSONResponse(
            status_code=404,
            content={"detail": {"error": f"API 路由不存在: {request.url.path}", "code": "NOT_FOUND"}}
        )
    return await proxy_to_openclaw(request)


@app.websocket("/{path:path}")
async def catchall_ws_proxy(websocket: WebSocket):
    await ws_proxy(websocket)


# ====== 启动 ======
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.port, log_level="info")
