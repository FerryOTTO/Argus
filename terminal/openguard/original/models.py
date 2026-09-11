# models.py — Pydantic 数据模型
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
import uuid
import time


# ====== 请求模型 ======

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RoleUpdateRequest(BaseModel):
    role: str = Field(pattern="^(user|admin)$")


class StatusUpdateRequest(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")


class QuotaUpdateRequest(BaseModel):
    """配额更新：quota_tier 与 daily_token_quota 至少填一项。

    daily_token_quota 传 null 表示清除个人限额、回落到档位默认值。
    """
    quota_tier: str | None = Field(default=None, pattern="^(free|basic|pro)$")
    daily_token_quota: int | None = Field(default=None, ge=0)


class SecurityLevelUpdateRequest(BaseModel):
    security_level: str = Field(pattern="^(public|internal|secret|top_secret|1|2|3|4)$")


class UserRuleSaveRequest(BaseModel):
    user_id: str = Field(min_length=1)
    level: str = "internal"
    specials: Optional[List[str]] = None


class ResourceRuleSaveRequest(BaseModel):
    pattern: str = Field(min_length=1)
    required_level: str = "internal"
    inherit_mode: str = "flat"


class AdminQuarantineClearRequest(BaseModel):
    user_id: str = Field(min_length=1)


# ====== 中间件上下文 ======

class UserContext(BaseModel):
    user_id: str
    username: str
    role: str = "user"
    security_level: str
    session_id: str
    access_jti: str
    trace_id: str = ""


# ====== 对接方案第5节：统一安全数据结构 ======


class ModelUpdateRequest(BaseModel):
    model: str


class RequestContext(BaseModel):
    """一次请求的身份和链路信息（对接方案 5.1）"""
    trace_id: str = ""
    session_id: str = "default_session"
    user_id: str = "default_user"
    stage: Literal["input", "tool_pre", "content", "output"] = "input"
    timestamp: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S+08:00"))

    @classmethod
    def from_user_context(cls, uc: UserContext, stage: str = "input") -> "RequestContext":
        return cls(
            trace_id=uc.trace_id or str(uuid.uuid4()),
            session_id=uc.session_id,
            user_id=uc.user_id,
            stage=stage,  # type: ignore
        )


class SecurityRequest(BaseModel):
    """统一安全检查请求（对接方案 5.2）"""
    context: RequestContext
    payload: Dict[str, Any] = Field(default_factory=dict)


class ModuleResult(BaseModel):
    """单个安全模块的返回结果（对接方案 5.3）"""
    module: str
    success: bool = True
    action: Literal["allow", "block", "rewrite", "human_review"] = "allow"
    risk_score: float = 0.0
    reason: str = ""
    modified_data: Optional[Any] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    error: Optional[str] = None


class SecurityResponse(BaseModel):
    """统一安全检查响应（对接方案 5.4）"""
    trace_id: str
    stage: str
    action: Literal["allow", "block", "rewrite", "human_review"]
    risk_score: float = 0.0
    reason: str = ""
    data: Optional[Any] = None
    module_results: List[ModuleResult] = Field(default_factory=list)


class AuditEvent(BaseModel):
    """审计事件（对接方案 7.8）"""
    event_id: str
    trace_id: str
    session_id: str
    user_id: str
    timestamp: str
    stage: str
    source_module: str
    action: str
    risk_score: float
    reason: str
    content: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
