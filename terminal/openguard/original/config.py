# config.py — 加载环境变量和密钥
import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
load_dotenv()


def _fallback_keys_dir() -> Path:
    """包目录不可写时的密钥回退目录（如安装到 Program Files）。"""
    base = os.getenv("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "ClawGuard" / "keys"


def _ensure_keypair(keys_dir: Path) -> bool:
    """在 keys_dir 下生成 RSA-2048 密钥对，成功返回 True。

    出厂包不再携带固定私钥：每台机器首次启动时各自生成，避免所有部署共用
    同一 JWT 签名密钥（否则任何拿到安装包的人都能伪造 token）。
    """
    private_path = keys_dir / "private.pem"
    public_path = keys_dir / "public.pem"
    if private_path.exists() and public_path.exists():
        return True
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except Exception as exc:  # pragma: no cover
        raise FileNotFoundError(
            "缺少 cryptography 依赖，无法自动生成 JWT 密钥对。请先执行 "
            "pip install -r requirements.txt。"
        ) from exc

    try:
        keys_dir.mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        public_path.write_bytes(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        return True
    except OSError:
        return False


def _read_key(env_var: str) -> str:
    default_name = "private.pem" if "PRIVATE" in env_var else "public.pem"
    val = os.getenv(env_var, "")
    if val:
        key_path = Path(val)
        if not key_path.is_absolute():
            key_path = ROOT_DIR / key_path
    else:
        key_path = ROOT_DIR / "keys" / default_name

    # 密钥缺失时自动生成（优先就地生成，目录不可写则回退到用户目录）
    if not key_path.exists() or key_path.is_dir():
        if not _ensure_keypair(key_path.parent):
            fallback = _fallback_keys_dir()
            _ensure_keypair(fallback)
            key_path = fallback / default_name

    if not key_path.exists() or key_path.is_dir():
        raise FileNotFoundError(
            f"密钥文件不存在: {key_path}。请先运行生成密钥对。"
        )
    return key_path.read_text(encoding="utf-8")


class Config:
    port: int = int(os.getenv("PORT", "8001"))

    # JWT
    jwt_private_key: str = _read_key("JWT_PRIVATE_KEY_PATH")
    jwt_public_key: str = _read_key("JWT_PUBLIC_KEY_PATH")
    jwt_issuer: str = os.getenv("JWT_ISSUER", "openclaw-auth")
    jwt_audience: str = os.getenv("JWT_AUDIENCE", "openclaw-gateway")
    jwt_access_ttl: int = int(os.getenv("JWT_ACCESS_TOKEN_TTL", "900"))
    jwt_refresh_ttl: int = int(os.getenv("JWT_REFRESH_TOKEN_TTL", "604800"))

    # Redis (optional)
    redis_url: str = os.getenv("REDIS_URL", "")

    # SQLite
    sqlite_path: Path = ROOT_DIR / os.getenv("SQLITE_PATH", "./data/auth.db")

    # OpenClaw backend
    openclaw_url: str = os.getenv("OPENCLAW_URL", "http://127.0.0.1:18789")

    # Bridge WebSocket URL
    bridge_url: str = os.getenv("BRIDGE_URL", "ws://127.0.0.1:18080")
    bridge_token: str = os.getenv("BRIDGE_TOKEN", "")

    # Clawguard
    clawguard_url: str = os.getenv("CLAWGUARD_URL", "http://127.0.0.1:8000")
    clawguard_timeout: int = int(os.getenv("CLAWGUARD_TIMEOUT", "10"))
    trace_id_prefix: str = os.getenv("TRACE_ID_PREFIX", "openguard")

    # ===== LLM 代理：4 家主流提供商（DeepSeek / MiniMax / GLM / Kimi） =====
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

    minimax_api_key: str = os.getenv("MINIMAX_API_KEY", "")
    minimax_base_url: str = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")

    zhipu_api_key: str = os.getenv("ZHIPU_API_KEY", "")
    zhipu_base_url: str = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")

    moonshot_api_key: str = os.getenv("MOONSHOT_API_KEY", "")
    moonshot_base_url: str = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")

    # ===== 统一端点（可选，公司自建 OpenAI 协议代理，配置后覆盖所有提供商） =====
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_api_base: str = os.getenv("LLM_API_BASE", "")

    # ===== 自部署 vLLM/Ollama（可选） =====
    hosted_vllm_api_key: str = os.getenv("HOSTED_VLLM_API_KEY", "")
    hosted_vllm_api_base: str = os.getenv("HOSTED_VLLM_API_BASE", "")

    llm_proxy_token: str = os.getenv("LLM_PROXY_TOKEN", "")
    # 设为 true 时，无法归属到用户（缺 X-Agent-Id）的 LLM 请求将被拒绝，防止配额绕过
    llm_proxy_require_agent: bool = os.getenv("LLM_PROXY_REQUIRE_AGENT", "false").lower() in ("1", "true", "yes")

    # ===== 模型管理配置 =====
    default_model: str = os.getenv("DEFAULT_MODEL", "deepseek/deepseek-v4-flash")

    available_models: list = [
        # --- 深度求索 DeepSeek（V4 代） ---
        {"id": "deepseek/deepseek-v4-pro",   "name": "DeepSeek V4 Pro",   "description": "旗舰推理模型，1M 上下文"},
        {"id": "deepseek/deepseek-v4-flash", "name": "DeepSeek V4 Flash", "description": "快速低成本模型，1M 上下文"},
        # --- 月之暗面 Kimi / Moonshot ---
        {"id": "kimi/kimi-k2.5",          "name": "Kimi K2.5",        "description": "Kimi 最新旗舰"},
        {"id": "kimi/kimi-k2",            "name": "Kimi K2",          "description": "Kimi 标准旗舰，128K"},
        {"id": "kimi/moonshot-v1-128k",   "name": "Moonshot V1 128K", "description": "Kimi 经典长上下文"},
        # --- 智谱 AI GLM ---
        {"id": "glm/glm-4-plus",  "name": "GLM-4-Plus",  "description": "智谱旗舰"},
        {"id": "glm/glm-4-air",   "name": "GLM-4-Air",   "description": "智谱高性价比"},
        {"id": "glm/glm-4-flash", "name": "GLM-4-Flash", "description": "智谱极速免费"},
        # --- MiniMax ---
        {"id": "minimax/minimax-m2", "name": "MiniMax M2", "description": "MiniMax 推理旗舰"},
        {"id": "minimax/minimax-m1", "name": "MiniMax M1", "description": "MiniMax 推理模型"},
    ]

    # ===== 模型定价：元 / 1K tokens（input/output 分开）。上线前请按实际价格填写 =====
    model_pricing: dict = {
        "deepseek/deepseek-v4-pro":   {"input": 0.004, "output": 0.016},
        "deepseek/deepseek-v4-flash": {"input": 0.0005, "output": 0.002},
        "kimi/kimi-k2.5":             {"input": 0.006, "output": 0.016},
        "kimi/kimi-k2":               {"input": 0.006, "output": 0.016},
        "kimi/moonshot-v1-128k":      {"input": 0.012, "output": 0.012},
        "glm/glm-4-plus":             {"input": 0.005, "output": 0.005},
        "glm/glm-4-air":              {"input": 0.0005, "output": 0.0005},
        "glm/glm-4-flash":            {"input": 0.0000, "output": 0.0000},
        "minimax/minimax-m2":         {"input": 0.004, "output": 0.016},
        "minimax/minimax-m1":         {"input": 0.002, "output": 0.008},
    }

    # ===== 配额配置（周度） =====
    quota_free: int = int(os.getenv("QUOTA_FREE", "140000000"))
    quota_basic: int = int(os.getenv("QUOTA_BASIC", "7000000"))
    quota_pro: int = int(os.getenv("QUOTA_PRO", "70000000"))

    quota_reset_weekday: int = int(os.getenv("QUOTA_RESET_WEEKDAY", "0"))
    quota_reset_hour: int = int(os.getenv("QUOTA_RESET_HOUR", "0"))
    quota_reset_minute: int = int(os.getenv("QUOTA_RESET_MINUTE", "0"))

    # 默认用户
    default_user_id: str = os.getenv("DEFAULT_USER_ID", "default_user")
    default_session_id: str = os.getenv("DEFAULT_SESSION_ID", "default_session")

    # Admin
    admin_username: str = os.getenv("ADMIN_USERNAME", "")

    # SSO
    sso_enabled: bool = os.getenv("SSO_ENABLED", "false").lower() in ("1", "true", "yes")
    sso_provider_id: str = os.getenv("SSO_PROVIDER_ID", "oidc")
    sso_provider_name: str = os.getenv("SSO_PROVIDER_NAME", "SSO 登录")
    sso_client_id: str = os.getenv("SSO_CLIENT_ID", "")
    sso_client_secret: str = os.getenv("SSO_CLIENT_SECRET", "")
    sso_issuer: str = os.getenv("SSO_ISSUER", "")
    sso_authorize_url: str = os.getenv("SSO_AUTHORIZE_URL", "")
    sso_token_url: str = os.getenv("SSO_TOKEN_URL", "")
    sso_userinfo_url: str = os.getenv("SSO_USERINFO_URL", "")
    sso_jwks_url: str = os.getenv("SSO_JWKS_URL", "")
    sso_scopes: str = os.getenv("SSO_SCOPES", "openid profile email")
    sso_username_claim: str = os.getenv("SSO_USERNAME_CLAIM", "preferred_username")

    # Template directory
    template_dir: Path = ROOT_DIR / "templates"
    static_dir: Path = ROOT_DIR / "static"


config = Config()
