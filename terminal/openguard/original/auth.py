# auth.py — JWT 签发/验证 + 用户认证
import time
import uuid
import secrets
import hashlib
import bcrypt
import jwt
from config import config
from database import (
    find_user_by_username, find_user_by_id, insert_user, insert_refresh_token,
    find_refresh_token, revoke_refresh_token, revoke_all_user_refresh_tokens,
    update_user_last_login, insert_agent, insert_sso_link,
)
from session_store import session_store

BCRYPT_COST = 12

# SSO 用户的密码占位符（非法 bcrypt 哈希 → 密码登录一律失败）
SSO_PASSWORD_PLACEHOLDER = "!sso!"

# 用户不存在时也执行一次 bcrypt 校验的占位哈希，避免计时侧信道泄露用户名是否存在
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"openguard-dummy-password", bcrypt.gensalt(BCRYPT_COST)).decode()


def _nanoid(length: int = 16) -> str:
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(chars) for _ in range(length))


def _hash_token(token: str) -> str:
    """SHA-256 哈希（用于存储 refresh token，不占 bcrypt 72 字节限制）"""
    return hashlib.sha256(token.encode()).hexdigest()


# ====== JWT ======

def sign_access_token(user_id: str, username: str, role: str,
                      security_level: str, jti: str, sid: str,
                      trace_id: str = "") -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "security_level": security_level,
        "jti": jti,
        "sid": sid,
        "trace_id": trace_id or f"openguard-{uuid.uuid4().hex[:12]}",
        "iat": int(time.time()),
        "exp": int(time.time()) + config.jwt_access_ttl,
        "iss": config.jwt_issuer,
        "aud": config.jwt_audience,
    }
    return jwt.encode(payload, config.jwt_private_key, algorithm="RS256")


def sign_refresh_token(user_id: str, jti: str, sid: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": jti,
        "sid": sid,
        "iat": int(time.time()),
        "exp": int(time.time()) + config.jwt_refresh_ttl,
    }
    return jwt.encode(payload, config.jwt_private_key, algorithm="RS256")


def verify_access_token(token: str) -> dict:
    return jwt.decode(
        token, config.jwt_public_key, algorithms=["RS256"],
        issuer=config.jwt_issuer, audience=config.jwt_audience
    )


def verify_refresh_token(token: str) -> dict:
    payload = jwt.decode(token, config.jwt_public_key, algorithms=["RS256"])
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Not a refresh token")
    return payload


# ====== Agent ======

def _slug_username(username: str) -> str:
    import re
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", username).strip("-").lower()
    return slug or "user"


async def _create_default_agent(user_id: str, username: str) -> dict:
    """为新用户创建默认 Agent（注册即建 agent，agentClaw 风格）。

    1. 生成全局唯一的 openclaw agent id：<user_id>-<slug>-<uuid8>
    2. 通过 Bridge HTTP API 在共享 OpenClaw 实例中创建真实 Agent
    3. 写入 user_agents 映射表
    """
    import httpx
    # agentClaw 约定：agent id 自携带租户信息
    agent_id = f"{user_id}-{_slug_username(username)}-{uuid.uuid4().hex[:8]}"
    agent_record = {
        "id": "ua_" + _nanoid(12),
        "user_id": user_id,
        "agent_id": agent_id,
        "name": f"{username}'s Agent",
        "is_default": 1,
        "status": "active",
        "created_at": int(time.time() * 1000),
    }

    # 通过 Bridge 在 OpenClaw 中创建真实 Agent（失败不阻断注册，仅告警）
    bridge_http = config.bridge_url.replace("ws://", "http://").replace("wss://", "https://").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(
                f"{bridge_http}/api/agents",
                headers={"X-Bridge-Token": config.bridge_token},
                json={"agentId": agent_id, "name": agent_record["name"]},
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                print(f"[Auth] OpenClaw agent created via bridge: {agent_id}")
            else:
                print(f"[Auth] bridge agents.create failed ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        print(f"[Auth] bridge agents.create error: {type(e).__name__}: {e}")

    await insert_agent(agent_record)
    return agent_record


def _sync_user_to_ac(user_id, username, security_level, specials=None, agent_id=None):
    """users.txt 已下线：个人版执法改为从 auth.db 动态回查，这里不再写本地规则文件。"""
    return None


async def register_user(username: str, password: str) -> dict:
    if len(username) < 3 or len(username) > 32:
        raise ValueError("用户名长度必须 3-32 字符")
    if len(password) < 8:
        raise ValueError("密码长度必须 >= 8")

    existing = await find_user_by_username(username)
    if existing:
        raise ValueError("用户名已存在")

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(BCRYPT_COST)).decode()
    user_id = "usr_" + _nanoid(16)
    now = int(time.time() * 1000)

    # 确定角色：所有用户默认 user，ADMIN_USERNAME 匹配的自动提升
    role = "admin" if username == config.admin_username else "user"
    sec_level = "top_secret" if role == "admin" else "internal"

    await insert_user({
        "id": user_id, "username": username, "password_hash": password_hash,
        "role": role, "security_level": sec_level, "status": "active",
        "created_at": now,
    })

    # 创建默认 Agent
    agent = await _create_default_agent(user_id, username)

    # 同步写入 Access Control 规则库
    _sync_user_to_ac(user_id, username, sec_level, agent_id=agent.get("agent_id"))

    return {
        "id": user_id, "username": username,
        "role": role, "security_level": sec_level, "status": "active",
        "agent": {"agent_id": agent["agent_id"], "name": agent["name"]},
    }


async def create_sso_user(provider: str, subject: str, username: str) -> dict:
    """为 SSO 首次登录创建本地用户（占位密码，无法用密码登录）。"""
    base = username
    suffix = 0
    while await find_user_by_username(username):
        suffix += 1
        username = f"{base}{suffix}"[:32]

    user_id = "usr_" + _nanoid(16)
    now = int(time.time() * 1000)
    role = "admin" if username == config.admin_username else "user"
    sec_level = "top_secret" if role == "admin" else "internal"

    await insert_user({
        "id": user_id, "username": username,
        "password_hash": SSO_PASSWORD_PLACEHOLDER,
        "role": role, "security_level": sec_level, "status": "active",
        "created_at": now,
    })

    # 创建默认 Agent（失败不阻断，与注册流程一致）
    agent = await _create_default_agent(user_id, username)

    # 同步写入 Access Control 规则库
    _sync_user_to_ac(user_id, username, sec_level, agent_id=agent.get("agent_id") if agent else None)

    await insert_sso_link({
        "provider": provider, "subject": subject,
        "user_id": user_id, "created_at": now,
    })
    print(f"[SSO] 新用户 {username} (provider={provider}, sub={subject[:12]}...)")

    return await find_user_by_id(user_id)


async def issue_token_pair(user: dict, client_ip: str = "unknown") -> dict:
    """为已认证用户签发 access+refresh 双 Token 并登记会话（密码/SSO 共用）。"""
    session_id = "sess_" + _nanoid(16)
    access_jti = str(uuid.uuid4())
    refresh_jti = str(uuid.uuid4())
    trace_id = f"openguard-{uuid.uuid4().hex[:12]}"

    access_token = sign_access_token(
        user["id"], user["username"], user["role"],
        user["security_level"], access_jti, session_id, trace_id
    )
    refresh_token = sign_refresh_token(user["id"], refresh_jti, session_id)

    # 创建会话
    await session_store.create_session(
        session_id=session_id, user_id=user["id"], access_jti=access_jti,
        ip=client_ip, ttl=config.jwt_access_ttl,
    )

    # 存 Refresh Token 到 SQLite（SHA-256 哈希，不受 bcrypt 72 字节限制）
    refresh_hash = _hash_token(refresh_token)
    now_ms = int(time.time() * 1000)
    await insert_refresh_token({
        "jti": refresh_jti, "user_id": user["id"], "session_id": session_id,
        "token_hash": refresh_hash,
        "expires_at": now_ms + config.jwt_refresh_ttl * 1000,
        "created_at": now_ms,
    })

    # 更新最后登录时间
    await update_user_last_login(user["id"], now_ms)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "session_id": session_id,
        "expires_in": config.jwt_access_ttl,
        "user": {
            "id": user["id"], "username": user["username"],
            "role": user["role"],
            "security_level": user["security_level"], "status": user["status"],
        },
    }


async def authenticate_desktop_user(client_ip: str = "127.0.0.1") -> dict:
    """为本机个人版工作台签发非管理员会话。

    个人版不展示企业管理入口，但聊天链路仍需要一个经过 OpenGuard
    校验的会话；该账号仅允许由本机桌面端通过专用请求头创建/登录。
    """
    username = "desktop-local"
    user = await find_user_by_username(username)
    if not user:
        now = int(time.time() * 1000)
        user_id = "usr_" + _nanoid(16)
        password_hash = bcrypt.hashpw(secrets.token_urlsafe(32).encode(), bcrypt.gensalt(BCRYPT_COST)).decode()
        await insert_user({
            "id": user_id,
            "username": username,
            "password_hash": password_hash,
            "role": "user",
            "security_level": "internal",
            "status": "active",
            "created_at": now,
        })
        await _create_default_agent(user_id, username)
        _sync_user_to_ac(user_id, username, "internal")
        user = await find_user_by_username(username)
    if not user or user.get("status") != "active":
        raise ValueError("本机个人会话不可用")
    return await issue_token_pair(user, client_ip)


async def authenticate_user(username: str, password: str, client_ip: str = "unknown") -> dict:
    user = await find_user_by_username(username)

    # 防时序攻击：用户不存在时用占位哈希也执行一次 bcrypt，SSO 占位哈希校验失败即拒绝
    stored_hash = user["password_hash"] if user else _DUMMY_PASSWORD_HASH
    try:
        valid = bool(bcrypt.checkpw(password.encode(), stored_hash.encode()))
    except ValueError:
        valid = False  # 非法哈希（如 SSO 占位符）一律视为不匹配

    if not user or not valid:
        raise ValueError("用户名或密码错误")
    if user["status"] != "active":
        raise ValueError("账户已被禁用")

    return await issue_token_pair(user, client_ip)


async def refresh_session(old_refresh_token: str) -> dict:
    # 1. 验证签名
    payload = verify_refresh_token(old_refresh_token)

    # 2. 查数据库
    stored = await find_refresh_token(payload["jti"])

    # 3. 重用检测
    if not stored or stored["revoked_at"] is not None:
        await revoke_all_user_refresh_tokens(payload["sub"], int(time.time() * 1000))
        raise ValueError("Token 重用 detected，所有会话已撤销")

    # 4. 验证哈希
    if _hash_token(old_refresh_token) != stored["token_hash"]:
        raise ValueError("Refresh Token 验证失败")

    # 5. 生成新的 session + Token
    new_session_id = "sess_" + _nanoid(16)
    new_access_jti = str(uuid.uuid4())
    new_refresh_jti = str(uuid.uuid4())
    new_trace_id = f"openguard-{uuid.uuid4().hex[:12]}"

    user = await find_user_by_id(payload["sub"])
    if not user:
        raise ValueError("User not found")

    new_access_token = sign_access_token(
        user["id"], user["username"], user["role"],
        user["security_level"], new_access_jti, new_session_id, new_trace_id
    )
    new_refresh_token = sign_refresh_token(payload["sub"], new_refresh_jti, new_session_id)

    # 6. 撤销旧的，写入新的
    now_ms = int(time.time() * 1000)
    await revoke_refresh_token(payload["jti"], now_ms)
    refresh_hash = _hash_token(new_refresh_token)
    await insert_refresh_token({
        "jti": new_refresh_jti, "user_id": payload["sub"],
        "session_id": new_session_id, "token_hash": refresh_hash,
        "expires_at": now_ms + config.jwt_refresh_ttl * 1000,
        "created_at": now_ms,
    })

    # 7. 创建新会话
    await session_store.create_session(
        session_id=new_session_id, user_id=payload["sub"],
        access_jti=new_access_jti, ip="refresh", ttl=config.jwt_access_ttl,
    )

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "session_id": new_session_id,
    }
