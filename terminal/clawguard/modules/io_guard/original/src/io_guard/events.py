from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


SCHEMA_VERSION = "1.0"


class SecurityStage(str, Enum):
    """Stages shared by the security modules described in the meeting spec."""

    USER_INPUT = "user_input"
    PROMPT_GUARD = "prompt_guard"
    KNOWLEDGE = "knowledge"
    PLANNING = "planning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SANDBOX = "sandbox"
    OUTPUT_GUARD = "output_guard"
    FINAL_OUTPUT = "final_output"
    ERROR = "error"


class SecurityAction(str, Enum):
    """Canonical actions used at module boundaries."""

    ALLOW = "allow"
    BLOCK = "block"
    MODIFY = "modify"


@dataclass(frozen=True)
class SecurityDecision:
    action: SecurityAction
    risk_score: float
    reason: str
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.risk_score <= 1.0:
            raise ValueError("risk_score must be between 0 and 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "risk_score": round(self.risk_score, 6),
            "reason": self.reason,
            "confidence": round(self.confidence, 6),
        }


@dataclass(frozen=True)
class SecurityEvent:
    """Framework-neutral event exchanged between security modules."""

    event_id: str
    trace_id: str
    session_id: str
    user_id: str
    timestamp: str
    stage: SecurityStage
    source_module: str
    content: dict[str, Any]
    decision: SecurityDecision
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_event_id: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.trace_id:
            raise ValueError("trace_id is required")
        if not self.source_module:
            raise ValueError("source_module is required")
        if not isinstance(self.content, dict):
            raise TypeError("content must be an object")
        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "parent_event_id": self.parent_event_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "stage": self.stage.value,
            "source_module": self.source_module,
            "content": dict(self.content),
            "decision": self.decision.to_dict(),
            "metadata": {
                "tool_name": self.metadata.get("tool_name"),
                "model": self.metadata.get("model"),
                "latency_ms": self.metadata.get("latency_ms"),
                **{
                    key: value
                    for key, value in self.metadata.items()
                    if key not in {"tool_name", "model", "latency_ms"}
                },
            },
        }
