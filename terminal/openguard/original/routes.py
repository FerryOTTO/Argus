# routes.py — 认证 + 用户管理 + Agent 路由
import json
import time
import uuid
import urllib.parse
import websockets
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from auth import register_user, authenticate_user, authenticate_desktop_user, refresh_session
from session_store import session_store
from middleware import auth_middleware, admin_required, csrf_middleware
from models import (
    RegisterRequest, LoginRequest, RefreshRequest,
    ModelUpdateRequest, RoleUpdateRequest, StatusUpdateRequest, QuotaUpdateRequest,
    SecurityLevelUpdateRequest, UserRuleSaveRequest, ResourceRuleSaveRequest, AdminQuarantineClearRequest,
)
from database import (
    list_users, find_user_by_id, find_user_by_username, find_agent_by_user, list_user_agents,
    update_user_role, update_user_status, update_user_security_level, update_user_quota, delete_user_by_id,
    revoke_all_user_refresh_tokens, list_usage_records,
    sum_user_tokens_since, sum_user_cost_since, get_week_start_ms, get_next_week_start_ms,
    get_db,
)
from config import config
from rate_limiter import limiter


# 供 skill 路由复用：返回 user 对象或抛 401
async def get_current_user(request: Request):
    """FastAPI Depends 风格的当前用户解析器。"""
    return await auth_middleware(request)

router = APIRouter()


# ====== 认证路由 ======

@router.post("/auth/register")
async def register(body: RegisterRequest, request: Request):
    # 速率限制：每分钟最多 3 次注册
    ip = request.client.host if request.client else "127.0.0.1"
    if not limiter.is_allowed(f"register:{ip}", 3, 60):
        raise HTTPException(status_code=429, detail={"error": "请求过于频繁，请稍后重试", "code": "RATE_LIMITED"})
    try:
        user = await register_user(body.username, body.password)
        return user
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})


def _token_response(data: dict) -> JSONResponse:
    """返回 Token，并由服务端写入同源 Cookie。

    企业版运行在 Electron webview 中时，登录请求和后续 dashboard 导航可能
    发生在不同的 renderer 文档上下文。仅依赖 login.html 里的 document.cookie
    会导致导航后 Cookie 丢失，页面又被当成未登录而回到登录页。由服务端在
    登录响应中设置 Cookie，可以保证浏览器/webview 的 cookie jar 正确接管会话。
    """
    response = JSONResponse(data)
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    if access_token:
        response.set_cookie(
            key="token", value=access_token, max_age=config.jwt_access_ttl,
            path="/", httponly=False, samesite="lax",
        )
    if refresh_token:
        response.set_cookie(
            key="refresh_token", value=refresh_token, max_age=config.jwt_refresh_ttl,
            path="/", httponly=False, samesite="lax",
        )
    return response


@router.post("/auth/desktop")
async def desktop_login(request: Request):
    """本机个人版会话：不开放企业管理能力，仅用于本地工作台聊天。"""
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"} or request.headers.get("X-Clawguard-Desktop") != "1":
        raise HTTPException(status_code=403, detail={"error": "仅允许本机桌面端调用", "code": "DESKTOP_ONLY"})
    try:
        return _token_response(await authenticate_desktop_user(client_host))
    except ValueError as e:
        raise HTTPException(status_code=503, detail={"error": str(e), "code": "DESKTOP_SESSION_UNAVAILABLE"})


@router.post("/auth/login")
async def login(body: LoginRequest, request: Request):
    # 速率限制：每分钟最多 5 次登录
    ip = request.client.host if request.client else "127.0.0.1"
    if not limiter.is_allowed(f"login:{ip}", 5, 60):
        raise HTTPException(status_code=429, detail={"error": "请求过于频繁，请稍后重试", "code": "RATE_LIMITED"})
    try:
        result = await authenticate_user(body.username, body.password, request.client.host or "unknown")
        return _token_response(result)
    except ValueError as e:
        raise HTTPException(status_code=401, detail={"error": str(e)})


@router.post("/auth/refresh")
async def refresh(body: RefreshRequest):
    try:
        result = await refresh_session(body.refresh_token)
        return _token_response(result)
    except ValueError as e:
        raise HTTPException(status_code=401, detail={"error": str(e)})


@router.post("/auth/logout")
async def logout(request: Request):
    await csrf_middleware(request)
    user = await auth_middleware(request)
    await session_store.destroy_session(user.session_id)
    print(f"[Auth] User {user.username} logged out, session {user.session_id} destroyed")
    return {"success": True}


# ====== SSO（通用 OIDC/OAuth2，SSO_ENABLED=true 时生效） ======

@router.get("/api/auth/sso-providers")
async def sso_providers(request: Request):
    """公开的 SSO 提供商列表（前端登录页据此渲染按钮）。"""
    import sso
    return sso.sso_providers_public(str(request.base_url))


@router.get("/api/auth/sso/{provider}")
async def sso_login(provider: str, request: Request):
    """发起 SSO：生成 state 并 307 跳转 IdP 授权页。"""
    import sso
    ip = request.client.host if request.client else "127.0.0.1"
    if not limiter.is_allowed(f"sso:{ip}", 6, 60):
        raise HTTPException(status_code=429, detail={"error": "请求过于频繁，请稍后重试", "code": "RATE_LIMITED"})
    try:
        url, _state = await sso.build_authorize_url(provider, str(request.base_url))
        return RedirectResponse(url, status_code=307)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})


@router.get("/api/auth/sso/{provider}/callback")
async def sso_callback(provider: str, request: Request,
                       code: str = "", state: str = "", error: str = ""):
    """IdP 回调：校验 state → 换 token → 取 userinfo → 找/建用户 → 签发双 Token。"""
    import sso
    landing = "/sso-landing#"
    fail = "/login?sso_error=" + urllib.parse.quote(
        error or "sso_failed", safe=""
    )
    if error:
        return RedirectResponse(fail)
    if not code or not state:
        return RedirectResponse(fail)
    try:
        result = await sso.handle_sso_callback(
            provider, code, state, str(request.base_url),
            client_ip=request.client.host if request.client else "unknown",
        )
    except ValueError as e:
        print(f"[SSO] callback 失败: {e}")
        return RedirectResponse("/login?sso_error=" + urllib.parse.quote(str(e), safe=""))
    fragment = urllib.parse.urlencode({
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
    })
    return RedirectResponse(landing + fragment)


@router.get("/sso-landing", include_in_schema=False)
async def sso_landing():
    """SSO 落地页：从 URL fragment 取 token 写入 cookie 后跳转 dashboard。"""
    html = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>登录中…</title></head><body>
<script>
(function(){
  var params = new URLSearchParams(location.hash.replace('#',''));
  var access = params.get('access_token');
  var refresh = params.get('refresh_token');
  if (access) {
    var d = new Date(); d.setTime(d.getTime() + 86400000);
    document.cookie = 'token=' + access + ';expires=' + d.toUTCString() + ';path=/;SameSite=Lax';
    if (refresh) {
      var d2 = new Date(); d2.setTime(d2.getTime() + 7*86400000);
      document.cookie = 'refresh_token=' + refresh + ';expires=' + d2.toUTCString() + ';path=/;SameSite=Lax';
    }
    location.replace('/dashboard');
  } else {
    location.replace('/login?sso_error=' + encodeURIComponent(params.get('error') || 'sso_failed'));
  }
})();
</script></body></html>"""
    return HTMLResponse(html)


@router.get("/me")
async def me(request: Request):
    user = await auth_middleware(request)
    agent = await find_agent_by_user(user.user_id)

    # 周度配额信息
    week_start_ms = get_week_start_ms()
    next_week_start_ms = get_next_week_start_ms()
    quota_used = await sum_user_tokens_since(user.user_id, week_start_ms)
    quota_cost = await sum_user_cost_since(user.user_id, week_start_ms)

    user_data = await find_user_by_id(user.user_id)
    quota_tier = user_data.get("quota_tier", "free") if user_data else "free"
    daily_limit = user_data.get("daily_token_quota") if user_data else None

    _TIER_LIMITS = {
        "free": config.quota_free,
        "basic": config.quota_basic,
        "pro": config.quota_pro,
    }
    quota_limit = daily_limit if daily_limit is not None else _TIER_LIMITS.get(quota_tier, _TIER_LIMITS["free"])

    return {
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role,
        "security_level": user.security_level,
        "session_id": user.session_id,
        "trace_id": user.trace_id,
        "agent_id": agent["agent_id"] if agent else None,
        "agent_name": agent["name"] if agent else None,
        # 新增字段
        "quota_tier": quota_tier,
        "quota_period": "weekly",
        "quota_used": quota_used,
        "quota_cost_used": quota_cost,
        "quota_limit": quota_limit,
        "quota_reset_at": next_week_start_ms,
        "default_model": config.default_model,
        "available_models": config.available_models,
    }


# ====== Agent 路由 ======



@router.put("/api/me/model")
async def update_my_model(body: ModelUpdateRequest, request: Request):
    """设置用户默认模型，持久化到 user_agents 表。"""
    user = await auth_middleware(request)
    agent = await find_agent_by_user(user.user_id)
    now = int(time.time() * 1000)
    if agent:
        await get_db().execute(
            "UPDATE user_agents SET model = ?, updated_at = ? WHERE agent_id = ?",
            [body.model, now, agent["agent_id"]])
        await get_db().commit()
    # 不修改共享的 config.available_models（避免跨用户污染），仅返回所选默认模型
    return {"default_model": body.model, "available_models": config.available_models}


@router.get("/api/agents")
async def get_my_agents(request: Request):
    user = await auth_middleware(request)
    agents = await list_user_agents(user.user_id)
    return [dict(a) for a in agents]


@router.get("/api/agents/default")
async def get_default_agent(request: Request):
    user = await auth_middleware(request)
    agent = await find_agent_by_user(user.user_id)
    if not agent:
        raise HTTPException(status_code=404, detail={"error": "No default agent found"})
    return {"agent_id": agent["agent_id"], "name": agent["name"]}


# ====== 用户管理路由（需登录查看列表） ======

@router.get("/auth/users")
async def get_users(request: Request):
    await admin_required(request)
    users = await list_users()
    return [dict(u) for u in users]


@router.get("/auth/sessions")
async def get_sessions(request: Request):
    await admin_required(request)
    return await session_store.list_sessions()


# ====== Admin 路由 ======

@router.get("/api/admin/users")
async def admin_list_users(request: Request):
    await admin_required(request)
    users = await list_users()
    week_start_ms = get_week_start_ms()
    result = []
    for u in users:
        agents = await list_user_agents(u["id"])
        week_used = await sum_user_tokens_since(u["id"], week_start_ms)
        week_cost = await sum_user_cost_since(u["id"], week_start_ms)
        result.append({
            **dict(u),
            "agents": [dict(a) for a in agents],
            "week_used": week_used,
            "week_cost": week_cost,
        })
    return result


@router.get("/api/admin/usage")
async def admin_list_usage(request: Request):
    """LLM 计量记录（管理员）"""
    await admin_required(request)
    records = await list_usage_records(limit=200)
    return [dict(r) for r in records]


@router.put("/api/admin/users/{user_id}/role")
async def admin_update_role(user_id: str, body: RoleUpdateRequest, request: Request):
    await csrf_middleware(request)
    admin = await admin_required(request)
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail={"error": "不能修改自己的角色"})
    target = await find_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail={"error": "用户不存在"})
    await update_user_role(user_id, body.role)
    print(f"[Admin] {admin.username} changed {target['username']}'s role to {body.role}")
    return {"success": True, "user_id": user_id, "role": body.role}


@router.put("/api/admin/users/{user_id}/status")
async def admin_update_status(user_id: str, body: StatusUpdateRequest, request: Request):
    await csrf_middleware(request)
    admin = await admin_required(request)
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail={"error": "不能修改自己的状态"})
    target = await find_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail={"error": "用户不存在"})
    await update_user_status(user_id, body.status)
    print(f"[Admin] {admin.username} changed {target['username']}'s status to {body.status}")
    return {"success": True, "user_id": user_id, "status": body.status}


@router.put("/api/admin/users/{user_id}/quota")
async def admin_update_quota(user_id: str, body: QuotaUpdateRequest, request: Request):
    """设置用户配额档位与个人每周 token 限额（daily_token_quota 为 None 表示用档位默认）。"""
    await csrf_middleware(request)
    admin = await admin_required(request)
    if not body.model_fields_set:
        raise HTTPException(status_code=400, detail={"error": "quota_tier 与 daily_token_quota 至少填一项"})
    target = await find_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail={"error": "用户不存在"})

    new_tier = body.quota_tier if body.quota_tier is not None else target.get("quota_tier", "free")
    # 用 model_fields_set 区分：未传 daily_token_quota=保持现值；显式传 null=清除回落档位默认
    if "daily_token_quota" in body.model_fields_set:
        new_limit = body.daily_token_quota
    else:
        new_limit = target.get("daily_token_quota")

    await update_user_quota(user_id, new_tier, new_limit)
    print(f"[Admin] {admin.username} set {target['username']}'s quota: tier={new_tier} daily={new_limit}")
    return {"success": True, "user_id": user_id, "quota_tier": new_tier, "daily_token_quota": new_limit}


import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _get_ac_store():
    from clawguard.modules.access_control.original import auth_gateway
    return auth_gateway._store


def _get_quarantine_store():
    from clawguard.modules.access_control.quarantine_store import QuarantineStore
    return QuarantineStore()


@router.put("/api/admin/users/{user_id}/security_level")
async def admin_update_security_level(user_id: str, body: SecurityLevelUpdateRequest, request: Request):
    """设置用户安全权限等级（用户库为准，执法侧从 auth.db 动态回查）。"""
    await csrf_middleware(request)
    admin = await admin_required(request)
    target = await find_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail={"error": "用户不存在"})

    level_aliases = {
        "1": "public", "2": "internal", "3": "secret", "4": "top_secret",
        "public": "public", "internal": "internal", "secret": "secret", "top_secret": "top_secret",
    }
    normalized = level_aliases.get(body.security_level.lower(), "internal")
    await update_user_security_level(user_id, normalized)

    # users.txt 已下线：等级只存用户库，不再写本地规则文件。

    print(f"[Admin] {admin.username} changed {target['username']}'s security level to {normalized}")
    return {"success": True, "user_id": user_id, "security_level": normalized}


@router.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: str, request: Request):
    await csrf_middleware(request)
    admin = await admin_required(request)
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail={"error": "不能删除自己"})
    target = await find_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail={"error": "用户不存在"})
    # 撤销该用户所有 refresh token + 会话
    now_ms = int(time.time() * 1000)
    await revoke_all_user_refresh_tokens(user_id, now_ms)
    await delete_user_by_id(user_id)

    # users.txt 已下线：用户删除只清用户库，无本地规则文件可清。

    print(f"[Admin] {admin.username} deleted user {target['username']}")
    return {"success": True, "user_id": user_id}


# ====== 访问控制与规则修改管理路由 ======

@router.get("/api/admin/rules")
async def admin_get_rules(request: Request):
    """获取访问控制的所有用户规则、资源规则及隔离列表。"""
    await admin_required(request)
    store = _get_ac_store()
    q_store = _get_quarantine_store()

    # users.txt 已下线：用户规则以用户库为准
    _lvl_map = {"public": 1, "internal": 2, "secret": 3, "top_secret": 4}
    user_rules = []
    for _u in (await list_users()):
        _lv = _lvl_map.get(str(_u.get("security_level") or "").lower(), 2)
        _sp = ["*"] if (_lv == 4 or _u.get("role") == "admin") else []
        user_rules.append({"user_id": _u.get("username"), "level": _lv, "specials": _sp})
    resource_rules = store.list_resource_rules()
    quarantine_items = q_store.list_active()

    return {
        "users": user_rules,
        "resources": resource_rules,
        "quarantine": quarantine_items,
    }


@router.post("/api/admin/rules/users")
async def admin_save_user_rule(body: UserRuleSaveRequest, request: Request):
    """更新用户规则：只允许已存在的用户，等级写入用户库（users.txt 已下线）。"""
    await csrf_middleware(request)
    await admin_required(request)
    target_uid = body.user_id.strip()
    level_aliases = {
        "1": "public", "2": "internal", "3": "secret", "4": "top_secret",
        "public": "public", "internal": "internal", "secret": "secret", "top_secret": "top_secret",
    }
    normalized = level_aliases.get(str(body.level or "").lower(), "internal")
    target = await find_user_by_id(target_uid)
    if not target:
        target = await find_user_by_username(target_uid)
    if not target and target_uid.startswith("agent_"):
        async with get_db() as db:
            async with db.execute("SELECT user_id FROM user_agents WHERE agent_id = ?", [target_uid]) as cur:
                row = await cur.fetchone()
                if row:
                    target = await find_user_by_id(row[0])
    if not target:
        raise HTTPException(status_code=404, detail={"error": "用户不存在，请先在用户管理中创建"})
    await update_user_security_level(target["id"], normalized)
    lvl_int = {"public": 1, "internal": 2, "secret": 3, "top_secret": 4}[normalized]
    note = ""
    if body.specials:
        note = "（特例 specials 已忽略：用户规则只保留等级，特例仅终端绑定用户有效）"
    return {"success": True, "message": "用户 " + target["username"] + " 等级已更新为 " + normalized + note,
            "user": {"user_id": target["username"], "level": lvl_int, "specials": []}}


@router.delete("/api/admin/rules/users/{user_id}")
async def admin_delete_user_rule(user_id: str, request: Request):
    """用户规则以用户库为准：此处不删等级，仅提示到用户管理操作。"""
    await csrf_middleware(request)
    await admin_required(request)
    target_uid = user_id.strip()
    target = await find_user_by_id(target_uid)
    if not target:
        target = await find_user_by_username(target_uid)
    if not target:
        raise HTTPException(status_code=404, detail={"error": "用户不存在"})
    return {"success": True, "message": "用户规则以用户库为准，如需调整等级请到用户管理中修改"}


@router.post("/api/admin/rules/resources")
async def admin_save_resource_rule(body: ResourceRuleSaveRequest, request: Request):
    """添加或更新资源规则（写入 resources.txt）。"""
    await csrf_middleware(request)
    await admin_required(request)
    store = _get_ac_store()
    res = store.add_resource_rule(
        pattern=body.pattern.strip(),
        required_level=body.required_level.strip(),
        inherit_mode=body.inherit_mode.strip() or "flat"
    )
    return res


@router.delete("/api/admin/rules/resources/{pattern:path}")
async def admin_delete_resource_rule(pattern: str, request: Request):
    """删除资源规则。"""
    await csrf_middleware(request)
    await admin_required(request)
    store = _get_ac_store()
    res = store.remove_resource_rule(pattern.strip())
    return res


@router.post("/api/admin/rules/reload")
async def admin_reload_rules(request: Request):
    """重新从文件加载规则。"""
    await csrf_middleware(request)
    await admin_required(request)
    store = _get_ac_store()
    store.reload()
    return {"success": True, "message": "规则已从磁盘重新加载"}


@router.post("/api/admin/rules/quarantine/clear")
async def admin_clear_user_quarantine(body: AdminQuarantineClearRequest, request: Request):
    """解除单个用户的隔离状态。"""
    await csrf_middleware(request)
    admin = await admin_required(request)
    q_store = _get_quarantine_store()
    ok = q_store.clear(body.user_id.strip(), by=admin.username)
    if not ok:
        raise HTTPException(status_code=404, detail={"error": "该用户未处于隔离状态或已被解除"})
    return {"success": True, "user_id": body.user_id.strip(), "message": "隔离已解除"}


@router.post("/api/admin/rules/quarantine/clear_all")
async def admin_clear_all_quarantine(request: Request):
    """清空所有用户的隔离状态。"""
    await csrf_middleware(request)
    admin = await admin_required(request)
    q_store = _get_quarantine_store()
    cnt = q_store.clear_all()
    return {"success": True, "cleared_count": cnt, "message": f"已解除 {cnt} 个用户的隔离状态"}


@router.post("/api/admin/rules/clear_audit")
async def admin_clear_audit(request: Request):
    """清空审计事件（开发/演示防误伤）。"""
    await csrf_middleware(request)
    await admin_required(request)
    audit_file = _PROJECT_ROOT / "runtime" / "audit" / "audit-events.jsonl"
    cleared = False
    if audit_file.exists():
        try:
            audit_file.write_text("", encoding="utf-8")
            cleared = True
        except Exception as exc:
            raise HTTPException(status_code=500, detail={"error": f"清空审计文件失败: {exc}"})
    return {"success": True, "cleared": cleared, "message": "审计日志已清空"}



# ====== 聊天历史路由 ======

# ====== 聊天历史路由（通过 Bridge 查询 OpenClaw 原生 JSONL） ======

from proxy import bridge_ws_url
from middleware import to_openclaw_session_key


async def bridge_rpc(method: str, params: dict, agent_id: str = "main") -> dict:
    """通过 Bridge 调用 OpenClaw RPC，返回 payload。
    Bridge 不可用时返回空结果而非 500。"""
    try:
        async with websockets.connect(bridge_ws_url(agent_id)) as ws:
            req_id = str(uuid.uuid4())
            await ws.send(json.dumps({
                "type": "req", "id": req_id,
                "method": method, "params": params
            }))
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg.get("type") == "res" and msg.get("id") == req_id:
                    if msg.get("ok"):
                        return msg.get("payload", {})
                    raise HTTPException(
                        status_code=500,
                        detail=msg.get("error", {}).get("message", "RPC failed")
                    )
    except (ConnectionRefusedError, OSError) as e:
        print(f"[Bridge RPC] {method} failed: Bridge unavailable ({e})")
        return {}  # 返回空结果，前端显示空列表而非崩溃


@router.get("/api/chat/sessions")
async def list_chat_sessions(request: Request):
    user = await auth_middleware(request)
    agent = await find_agent_by_user(user.user_id)
    agent_id = agent["agent_id"] if agent else "main"
    prefix = agent_id

    result = await bridge_rpc("sessions.list", {
        "agentId": agent_id,
        "includeLastMessage": True
    }, agent_id=agent_id)
    sessions = []
    for s in result.get("sessions", []):
        key = s.get("key", "").lower()
        # 只返回 session key 中包含当前用户 agent_id 的会话（大小写不敏感）
        if prefix.lower() not in key:
            continue
        sessions.append({
            "session_key": key,
                "title": (s.get("lastMessagePreview") or s.get("derivedTitle") or
                          s.get("displayName") or key.split(":")[-1])[:50],
                "msg_count": s.get("messageCount") or s.get("numMessages") or "",
                "last_active": s.get("updatedAt"),
            })
    return sessions


@router.get("/api/chat/history/{session_key:path}")
async def get_chat_history_route(session_key: str, request: Request):
    user = await auth_middleware(request)
    agent = await find_agent_by_user(user.user_id)
    agent_id = agent["agent_id"] if agent else "main"
    key = urllib.parse.unquote(session_key)
    # 规范 session key：若前端传来旧 main 会话，重定向到用户自己的 agent
    key = to_openclaw_session_key(key, agent_id)
    result = await bridge_rpc("chat.history", {
        "sessionKey": key,
        "limit": 200
    }, agent_id=agent_id)
    messages = []
    for m in result.get("messages", []):
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("text", "")
        if not content:
            blocks = m.get("content", [])
            if isinstance(blocks, list):
                content = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            else:
                content = str(blocks)
        messages.append({"role": role, "content": content})
    return messages
