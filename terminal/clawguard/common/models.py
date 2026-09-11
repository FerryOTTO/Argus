"""Clawguard 模块之间共用的数据结构。"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from clawguard.common.utils import generate_trace_id, utc_now_iso


Action = Literal["allow", "block", "rewrite", "human_review"]
Stage = Literal["input", "tool_pre", "content", "output", "audit"]


class RequestContext(BaseModel):
    """一次安全检查共用的用户、会话和链路信息。"""

    trace_id: str = Field(default_factory=generate_trace_id)
    session_id: str = "default_session"
    user_id: str = "default_user"
    stage: Stage
    timestamp: str = Field(default_factory=utc_now_iso)


class SecurityRequest(BaseModel):
    """所有安全模块统一接收的请求外壳。"""

    context: RequestContext
    payload: Dict[str, Any] = Field(default_factory=dict)


class ModuleResult(BaseModel):
    """单个安全模块返回的统一结果。"""

    module: str
    success: bool = True
    action: Action = "allow"
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    modified_data: Optional[Any] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = Field(default=0.0, ge=0.0)
    error: Optional[str] = None


class SecurityResponse(BaseModel):
    """统一 FastAPI 接口返回给 OpenClaw Adapter 的响应。"""

    trace_id: str
    stage: Stage
    action: Action
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    data: Optional[Any] = None
    module_results: List[ModuleResult] = Field(default_factory=list)


class AuditEvent(BaseModel):
    """OpenGuard、OpenClaw Adapter 和安全模块共用的审计事件。"""

    event_id: str
    trace_id: str
    session_id: str = "default_session"
    user_id: str = "default_user"
    timestamp: str = Field(default_factory=utc_now_iso)
    stage: str
    source_module: str
    action: str
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    content: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
