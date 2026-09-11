# middleware.py — JWT 认证中间件 + CSRF 保护 + Argus 身份传递
import hashlib
import hmac
import secrets
import uuid
from fastapi import Request, HTTPException
from auth import verify_access_token
from session_store import session_store
from config import config
from models import UserContext, RequestContext


def to_openclaw_session_key(session_key: str, agent_id: str | None = None) -> str:
    """规范 OpenClaw session key 为 agent:<agentId>:<key> 格式（agentClaw 约定）。

    - 无前缀：幂等加上 agent:<agentId>: 前缀
    - 已有 agent: 前缀但 agent 与当前用户不符：重定向到用户自己的 agent（防串会话）
    - 无 agent_id 时原样返回（legacy 单 agent 模式）
    """
    key = (session_key or "").strip()
    if not key:
        return f"agent:{agent_id or 'main'}:main"
    if key.startswith("agent:"):
        parts = key.split(":", 2)
        if agent_id and len(parts) >= 3 and parts[1] != agent_id:
            return f"agent:{agent_id}:{parts[2]}"
        return key
    return f"agent:{agent_id}:{key}" if agent_id else key


def sign_user_context(uc: UserContext) -> str:
    """对注入的用户身份上下文做 HMAC 签名（防下游伪造）。"""
    canonical = "|".join([
        uc.user_id, uc.session_id, uc.trace_id, uc.role, uc.security_level,
    ])
    return hmac.new(
        config.bridge_token.encode(), canonical.encode(), hashlib.sha256,
    ).hexdigest()[:16]



# ====== CSRF 保护 ======

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
# 需要 CSRF 校验的路径和方法
CSRF_PROTECTED_PREFIXES = ["/auth/", "/api/"]


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


async def csrf_middleware(request: Request) -> None:
    """CSRF 双提交 Cookie 验证。

    只对状态变更请求（POST/PUT/DELETE/PATCH）检验。
    读取 Cookie 中的 csrf_token 和请求头 X-CSRF-Token，两者必须一致。
    如果请求带有有效的 Bearer token（API 客户端），则跳过 CSRF 检查。
    """
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return

    # 有有效 Bearer token 的是 API 客户端，跳过 CSRF
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header[7:]
            payload = verify_access_token(token)
            if await session_store.validate_session(payload.get("sid", "")):
                return  # 有效 JWT，不是 CSRF 攻击场景
        except Exception:
            pass  # token 无效，继续 CSRF 检查

    path = request.url.path
    needs_csrf = any(path.startswith(p) for p in CSRF_PROTECTED_PREFIXES)
    if not needs_csrf:
        return

    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get(CSRF_HEADER)

    if not cookie_token or not header_token:
        raise HTTPException(
            status_code=403,
            detail={"error": "CSRF token 缺失", "code": "CSRF_MISSING"}
        )
    if not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(
            status_code=403,
            detail={"error": "CSRF token 不匹配", "code": "CSRF_INVALID"}
        )


def extract_token(request: Request) -> str | None:
    """提取 Token，三级 fallback：
       1. Authorization: Bearer xxx header
       2. Cookie: token=xxx
       3. URL ?token=xxx
    """
    # ① Authorization header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]

    # ② Cookie
    cookie_token = request.cookies.get("token")
    if cookie_token:
        return cookie_token

    # ③ URL 参数
    url_token = request.query_params.get("token")
    if url_token:
        return url_token

    return None


async def auth_middleware(request: Request) -> UserContext:
    """FastAPI 依赖：验证 JWT + 会话白名单，返回用户上下文（含 trace_id）"""
    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail={"error": "缺少 Token", "code": "TOKEN_MISSING"})

    try:
        payload = verify_access_token(token)
    except Exception as e:
        error_name = type(e).__name__
        if "expired" in str(e).lower() or error_name == "ExpiredSignatureError":
            raise HTTPException(status_code=401, detail={"error": "Token 已过期", "code": "TOKEN_EXPIRED"})
        raise HTTPException(status_code=401, detail={"error": "Token 无效", "code": "TOKEN_INVALID"})

    valid = await session_store.validate_session(payload["sid"])
    if not valid:
        raise HTTPException(status_code=401, detail={
            "error": "Token 已失效，请重新登录", "code": "SESSION_INVALID"
        })

    # trace_id：优先从请求头读取（上游已生成），否则从 JWT payload 取，否则新建
    trace_id = (
        request.headers.get("X-Argus-Trace-Id")
        or payload.get("trace_id")
        or f"{config.trace_id_prefix}-{uuid.uuid4().hex[:12]}"
    )

    return UserContext(
        user_id=payload["sub"],
        username=payload["username"],
        role=payload.get("role", "user"),
        security_level=payload["security_level"],
        session_id=payload["sid"],
        access_jti=payload["jti"],
        trace_id=trace_id,
    )


async def admin_required(request: Request) -> UserContext:
    """FastAPI 依赖：认证 + 要求 admin 角色"""
    user = await auth_middleware(request)
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail={"error": "需要管理员权限", "code": "FORBIDDEN"}
        )
    return user


# ====== Argus 身份头注入（对接方案 7.7） ======

def get_argus_headers(user_ctx: dict | UserContext) -> dict[str, str]:
    """从用户上下文组装 X-Argus-* 请求头。

    这些头在转发给 OpenClaw 时注入，
    OpenClaw Adapter 读取后组装 RequestContext 调用 Argus。
    对应对接方案 7.7 节。

    参数 user_ctx 可以是一个 dict（来自 JWT payload）或 UserContext 对象。
    """
    if isinstance(user_ctx, UserContext):
        uc = user_ctx
    else:
        # 从 dict 构造（用于 WebSocket 代理等场景）
        uc = UserContext(
            user_id=user_ctx.get("sub", user_ctx.get("user_id", config.default_user_id)),
            username=user_ctx.get("username", ""),
            role=user_ctx.get("role", "user"),
            security_level=user_ctx.get("security_level", "internal"),
            session_id=user_ctx.get("sid", user_ctx.get("session_id", config.default_session_id)),
            access_jti=user_ctx.get("jti", ""),
            trace_id=user_ctx.get("trace_id", f"{config.trace_id_prefix}-{uuid.uuid4().hex[:12]}"),
        )

    headers = {
        "X-Argus-User-Id": uc.user_id,
        "X-Argus-Session-Id": uc.session_id,
        "X-Argus-Trace-Id": uc.trace_id,
        "X-Argus-Role": uc.role,
        "X-Argus-Security-Level": uc.security_level,
        # 网关注入的上下文防篡改签名（下游可用 bridge_token 验证）
        "X-Openguard-Sig": sign_user_context(uc),
    }
    return headers
