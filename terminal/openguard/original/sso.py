# sso.py — 通用 OIDC/OAuth2 单点登录
# 设计：
#   1. 支持 OIDC 发现（SSO_ISSUER → .well-known/openid-configuration，带缓存）
#      或显式端点（SSO_AUTHORIZE_URL / SSO_TOKEN_URL / SSO_USERINFO_URL）
#   2. 身份以 userinfo 的 sub 为准（OAuth2 通用做法，兼容 GitHub/Keycloak/高校 IdP）
#   3. state 用 HMAC 签名防 CSRF，不落库
#   4. 首次登录自动注册（users 表 + 默认 agent + sso_links 绑定）
import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from typing import Any
from urllib.parse import urlencode, urljoin

import httpx

from config import config

SSO_REDIRECT_PATH = "/api/auth/sso/{provider}/callback"

# 模块级发现缓存：{issuer: (config, expires_at)}
_discovery_cache: dict[str, tuple[dict, float]] = {}


# ====== state 签名（防 CSRF） ======

def _state_secret() -> bytes:
    # 复用 JWT 私钥派生，部署时天然唯一
    return hashlib.sha256(config.jwt_private_key.encode()).digest()


def build_state(provider: str, ttl: int = 600) -> str:
    payload = {
        "provider": provider,
        "nonce": uuid.uuid4().hex,
        "exp": int(time.time()) + ttl,
    }
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode().rstrip("=")
    sig = hmac.new(_state_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_state(state: str, provider: str) -> dict:
    try:
        body, sig = state.rsplit(".", 1)
        expected = hmac.new(
            _state_secret(), body.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ValueError("state 签名无效")
        payload = json.loads(
            base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        )
    except Exception as exc:
        raise ValueError("state 无效或已过期") from exc
    if payload.get("provider") != provider:
        raise ValueError("state provider 不匹配")
    if payload.get("exp", 0) < time.time():
        raise ValueError("state 已过期")
    return payload


# ====== 提供商配置 ======

def _provider_config() -> dict:
    """合并环境变量，返回 {id, name, client_id, client_secret, endpoints}"""
    cfg = {
        "id": config.sso_provider_id,
        "name": config.sso_provider_name,
        "client_id": config.sso_client_id,
        "client_secret": config.sso_client_secret,
        "issuer": config.sso_issuer,
        "authorize_url": config.sso_authorize_url,
        "token_url": config.sso_token_url,
        "userinfo_url": config.sso_userinfo_url,
        "jwks_url": config.sso_jwks_url,
        "scopes": config.sso_scopes,
        "username_claim": config.sso_username_claim,
    }
    if not config.sso_enabled:
        raise ValueError("SSO 未启用")
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise ValueError("SSO_CLIENT_ID / SSO_CLIENT_SECRET 未配置")
    return cfg


async def _resolved_endpoints() -> dict:
    """优先 OIDC 发现，其次显式端点。返回 {authorize_url, token_url, userinfo_url}"""
    cfg = _provider_config()
    if cfg["issuer"]:
        return await _discover(cfg["issuer"])
    if not (cfg["authorize_url"] and cfg["token_url"]):
        raise ValueError("需配置 SSO_ISSUER 或 SSO_AUTHORIZE_URL+SSO_TOKEN_URL")
    return {
        "authorize_url": cfg["authorize_url"],
        "token_url": cfg["token_url"],
        "userinfo_url": cfg["userinfo_url"],
    }


async def _discover(issuer: str) -> dict:
    cached = _discovery_cache.get(issuer)
    if cached and cached[1] > time.time():
        return cached[0]

    well_known = urljoin(
        issuer.rstrip("/") + "/", ".well-known/openid-configuration"
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(well_known)
        resp.raise_for_status()
        doc = resp.json()

    endpoints = {
        "authorize_url": doc.get("authorization_endpoint", ""),
        "token_url": doc.get("token_endpoint", ""),
        "userinfo_url": doc.get("userinfo_endpoint", ""),
        "jwks_url": doc.get("jwks_uri", ""),
    }
    _discovery_cache[issuer] = (endpoints, time.time() + 3600)
    return endpoints


async def build_authorize_url(provider: str, base_url: str) -> tuple[str, str]:
    cfg = _provider_config()
    if provider != cfg["id"]:
        raise ValueError(f"未知的 SSO 提供商: {provider}")
    endpoints = await _resolved_endpoints()
    if not endpoints["authorize_url"]:
        raise ValueError("IdP 未提供 authorization_endpoint")

    state = build_state(provider)
    redirect_uri = base_url.rstrip("/") + SSO_REDIRECT_PATH.format(provider=provider)
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": cfg["scopes"],
        "state": state,
    }
    return f"{endpoints['authorize_url']}?{urlencode(params)}", state


async def _exchange_code(provider: str, code: str, redirect_uri: str) -> dict:
    cfg = _provider_config()
    endpoints = await _resolved_endpoints()
    if not endpoints["token_url"]:
        raise ValueError("IdP 未提供 token_endpoint")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            endpoints["token_url"],
            data=data,
            auth=(cfg["client_id"], cfg["client_secret"]),
        )
        if resp.status_code >= 400:
            raise ValueError(f"token 交换失败 ({resp.status_code}): {resp.text[:200]}")
        return resp.json()


async def _fetch_userinfo(access_token: str) -> dict:
    cfg = _provider_config()
    endpoints = await _resolved_endpoints()
    if not endpoints["userinfo_url"]:
        # 无 userinfo 端点时，退化为解析 id_token（仅标准 OIDC 才会走到这里）
        raise ValueError("IdP 未提供 userinfo_endpoint，暂不支持纯 id_token 模式")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            endpoints["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code >= 400:
            raise ValueError(f"userinfo 获取失败 ({resp.status_code}): {resp.text[:200]}")
        return resp.json()


def _pick_username(claims: dict) -> str:
    cfg = _provider_config()
    raw = (
        claims.get(cfg["username_claim"])
        or claims.get("preferred_username")
        or claims.get("name")
        or claims.get("email")
        or f"sso_{str(claims.get('sub', ''))[:12]}"
    )
    username = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw))[:32]
    if len(username) < 3:
        username = f"sso_{username or 'user'}"
    return username


# ====== 用户查找/创建（首次自动注册） ======

async def find_or_create_sso_user(provider: str, claims: dict, client_ip: str = "unknown") -> dict:
    """按 (provider, sub) 查找；不存在则自动注册 + 建默认 agent。返回 user 行 dict。"""
    import time as _time

    from auth import create_sso_user  # 延迟导入避免循环依赖
    from database import find_sso_link

    subject = str(claims.get("sub") or claims.get("id") or "")
    if not subject:
        raise ValueError("IdP userinfo 缺少 sub 字段，无法绑定用户")

    link = await find_sso_link(provider, subject)
    if link:
        from database import find_user_by_id
        user = await find_user_by_id(link["user_id"])
        if not user or user["status"] != "active":
            raise ValueError("SSO 账号已停用，请联系管理员")
        return user

    return await create_sso_user(provider, subject, _pick_username(claims))


# ====== 完整回调处理 ======

async def handle_sso_callback(
    provider: str, code: str, state: str, base_url: str, client_ip: str = "unknown"
) -> dict:
    """校验 state → 换 code → 取 userinfo → 找/建用户 → 签发双 token。"""
    verify_state(state, provider)

    redirect_uri = base_url.rstrip("/") + SSO_REDIRECT_PATH.format(provider=provider)
    token_resp = await _exchange_code(provider, code, redirect_uri)
    access_token = token_resp.get("access_token", "")
    if not access_token:
        raise ValueError("IdP token 响应缺少 access_token")

    claims = await _fetch_userinfo(access_token)

    user = await find_or_create_sso_user(provider, claims, client_ip)

    from auth import issue_token_pair
    return await issue_token_pair(user, client_ip)


def sso_providers_public(base_url: str) -> list[dict]:
    """供前端 /api/auth/sso-providers 展示（不泄露 secret）。"""
    if not config.sso_enabled:
        return []
    login_url = base_url.rstrip("/") + f"/api/auth/sso/{config.sso_provider_id}"
    return [{"id": config.sso_provider_id, "name": config.sso_provider_name, "login_url": login_url}]
