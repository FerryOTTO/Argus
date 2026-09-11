from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


SecurityStage = Literal["input", "tool_pre", "content", "output"]
SecurityAction = Literal["allow", "block", "rewrite"]


class RequestContext(BaseModel):
    """Standalone copy of the Clawguard V2.1 request context contract.

    The integration repository owns the canonical models.  Keeping this small
    compatibility model in the original IO Guard project lets the adapter be
    tested before it is copied into that repository.
    """

    trace_id: str
    session_id: str = "default_session"
    user_id: str = "default_user"
    stage: SecurityStage
    timestamp: str


class SecurityRequest(BaseModel):
    context: RequestContext
    payload: dict[str, Any] = Field(default_factory=dict)


class ModuleResult(BaseModel):
    module: str
    success: bool = True
    action: SecurityAction = "allow"
    risk_score: float = 0.0
    reason: str = ""
    modified_data: Optional[Any] = None
    details: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    error: Optional[str] = None


class SecurityResponse(BaseModel):
    trace_id: str
    stage: str
    action: SecurityAction
    risk_score: float = 0.0
    reason: str = ""
    data: Optional[Any] = None
    module_results: list[ModuleResult] = Field(default_factory=list)
