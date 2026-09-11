from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from io_guard.taxonomy import RiskCategory


class SourceType(str, Enum):
    USER_PROMPT = "user_prompt"
    RETRIEVAL_CHUNK = "retrieval_chunk"
    TOOL_RESULT = "tool_result"
    MEMORY = "memory"
    MODEL_OUTPUT = "model_output"


RiskType = RiskCategory


class Decision(str, Enum):
    ALLOW = "allow"
    REWRITE = "rewrite"
    BLOCK = "block"


class PrincipalType(str, Enum):
    EXTERNAL_USER = "external_user"
    EMPLOYEE = "employee"
    PRIVILEGED_EMPLOYEE = "privileged_employee"
    SERVICE_ACCOUNT = "service_account"


class TargetAudience(str, Enum):
    EXTERNAL = "external"
    INTERNAL = "internal"


@dataclass(frozen=True)
class Evidence:
    detector: str
    risk_type: RiskType
    message: str
    score: float
    snippet: str = ""
    start: int | None = None
    end: int | None = None
    field_path: str = ""
    step_id: str = ""
    remediable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "risk_type": self.risk_type.value,
            "message": self.message,
            "score": self.score,
            "snippet": self.snippet,
            "start": self.start,
            "end": self.end,
            "dimension": self.risk_type.dimension.value,
            "field_path": self.field_path,
            "step_id": self.step_id,
            "remediable": self.remediable,
        }


@dataclass
class GuardRequest:
    content: str
    source_type: SourceType
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = ""
    user_id: str = ""
    role_level: int = 0
    principal_type: str = PrincipalType.EXTERNAL_USER.value
    target_audience: str = TargetAudience.EXTERNAL.value
    channel_classification: str = "public"
    purpose: str = ""
    allowed_data_scopes: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_event_id: str | None = None


@dataclass
class GuardResult:
    decision: Decision
    risk_score: float
    risk_types: list[RiskType]
    sanitized_content: str
    evidence: list[Evidence]
    reason: str
    trace_id: str
    event_id: str = field(default_factory=lambda: str(uuid4()))
    policy_id: str = "default"
    processing_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def primary_risk(self) -> RiskType | None:
        if not self.evidence:
            return None
        return max(self.evidence, key=lambda item: item.score).risk_type

    def to_dict(self) -> dict[str, Any]:
        primary = self.primary_risk
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "decision": self.decision.value,
            "risk_score": self.risk_score,
            "risk_types": [risk.value for risk in self.risk_types],
            "verdict": (
                "safe" if self.decision in {Decision.ALLOW, Decision.REWRITE}
                else "unsafe"
            ),
            "primary_label": primary.value if primary else None,
            "dimension": primary.dimension.value if primary else None,
            "mitigated": self.decision == Decision.REWRITE,
            "sanitized_content": self.sanitized_content,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "processing_metadata": self.processing_metadata,
            "evidence": [item.to_dict() for item in self.evidence],
        }
