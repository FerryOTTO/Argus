from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from io_guard.config import OUTPUT_LEAKAGE_PATTERNS
from io_guard.events import (
    SecurityAction,
    SecurityDecision,
    SecurityEvent,
    SecurityStage,
)
from io_guard.types import Decision, Evidence, GuardRequest, GuardResult


STAGE_ALIASES = {
    "input": SecurityStage.PROMPT_GUARD,
    "pre_check": SecurityStage.PROMPT_GUARD,
    "prompt_guard": SecurityStage.PROMPT_GUARD,
    "context": SecurityStage.KNOWLEDGE,
    "retrieval_check": SecurityStage.KNOWLEDGE,
    "knowledge": SecurityStage.KNOWLEDGE,
    "output": SecurityStage.OUTPUT_GUARD,
    "post_check": SecurityStage.OUTPUT_GUARD,
    "output_guard": SecurityStage.OUTPUT_GUARD,
}

ACTION_MAP = {
    Decision.ALLOW: SecurityAction.ALLOW,
    Decision.REWRITE: SecurityAction.MODIFY,
    Decision.BLOCK: SecurityAction.BLOCK,
}


@dataclass
class AuditLogger:
    path: Path | str | None = None
    content_storage: str = "sanitized"
    max_content_chars: int = 2000

    def __post_init__(self) -> None:
        if self.content_storage not in {"none", "hash_only", "sanitized", "full"}:
            raise ValueError("unsupported audit content_storage mode")
        self.max_content_chars = max(0, int(self.max_content_chars))

    def configure(
        self,
        *,
        content_storage: str | None = None,
        max_content_chars: int | None = None,
    ) -> None:
        if content_storage is not None:
            if content_storage not in {
                "none",
                "hash_only",
                "sanitized",
                "full",
            }:
                raise ValueError("unsupported audit content_storage mode")
            self.content_storage = content_storage
        if max_content_chars is not None:
            self.max_content_chars = max(0, int(max_content_chars))

    def log(
        self,
        stage: str,
        request: GuardRequest,
        result: GuardResult,
    ) -> dict[str, Any]:
        event = self.build_event(stage, request, result)
        if self.path is not None:
            self._append(event)
        return event

    def build_event(
        self,
        stage: str,
        request: GuardRequest,
        result: GuardResult,
    ) -> dict[str, Any]:
        """Build the shared meeting-schema event without writing it."""
        security_stage = self._stage(stage)
        candidate_content = result.sanitized_content
        stored_content = self._stored_content(candidate_content)
        content_modified = candidate_content != request.content
        redaction_applied = content_modified or (
            stored_content is not None
            and stored_content != candidate_content[: self.max_content_chars]
        )
        content: dict[str, Any] = {
            "source_type": request.source_type.value,
            "original_sha256": self._hash_text(request.content),
            "storage_mode": self.content_storage,
            "modified": content_modified,
            "redaction_applied": redaction_applied,
            "truncated": len(candidate_content) > self.max_content_chars,
            "forwarded": result.decision in {Decision.ALLOW, Decision.REWRITE},
        }
        if self.content_storage == "full":
            content["original_text"] = request.content[: self.max_content_chars]
        if stored_content is not None:
            content["effective_text"] = stored_content
            if security_stage == SecurityStage.PROMPT_GUARD:
                content["modified_prompt"] = stored_content
            elif security_stage == SecurityStage.KNOWLEDGE:
                content["filtered_content"] = stored_content
            elif security_stage == SecurityStage.OUTPUT_GUARD:
                content["sanitized_output"] = stored_content

        request_metadata = dict(request.metadata)
        latency_ms = result.processing_metadata.get("latency_ms")
        metadata = {
            "tool_name": request_metadata.pop("tool_name", None),
            "model": request_metadata.pop("model", None),
            "latency_ms": latency_ms,
            "source_type": request.source_type.value,
            "role_level": request.role_level,
            "principal_type": request.principal_type,
            "target_audience": request.target_audience,
            "channel_classification": request.channel_classification,
            "purpose": request.purpose,
            "allowed_data_scopes": sorted(request.allowed_data_scopes),
            "policy_id": result.policy_id,
            "risk_types": [risk.value for risk in result.risk_types],
            "primary_label": (
                result.primary_risk.value if result.primary_risk else None
            ),
            "dimension": (
                result.primary_risk.dimension.value
                if result.primary_risk
                else None
            ),
            "processing": result.processing_metadata,
            "request": request_metadata,
            # Matched text is represented by a hash and offsets, never copied.
            "evidence": [self._safe_evidence(item) for item in result.evidence],
        }
        event = SecurityEvent(
            event_id=result.event_id,
            parent_event_id=request.parent_event_id,
            trace_id=request.trace_id,
            session_id=request.session_id,
            user_id=request.user_id,
            timestamp=result.created_at,
            stage=security_stage,
            source_module="input_output_guard",
            content=content,
            decision=SecurityDecision(
                action=ACTION_MAP[result.decision],
                risk_score=result.risk_score,
                reason=result.reason,
                confidence=self._decision_confidence(result),
            ),
            metadata=metadata,
        )
        return event.to_dict()

    def _append(self, event: dict[str, Any]) -> None:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    def _stored_content(self, content: str) -> str | None:
        if self.content_storage in {"none", "hash_only"}:
            return None
        value = content or ""
        if self.content_storage == "sanitized":
            for pattern, _message, _score, replacement in (
                OUTPUT_LEAKAGE_PATTERNS
            ):
                value = re.sub(
                    pattern,
                    replacement,
                    value,
                    flags=re.IGNORECASE,
                )
        return value[: self.max_content_chars]

    @staticmethod
    def _stage(stage: str) -> SecurityStage:
        if stage in STAGE_ALIASES:
            return STAGE_ALIASES[stage]
        try:
            return SecurityStage(stage)
        except ValueError as exc:
            raise ValueError(f"unsupported security event stage: {stage}") from exc

    @staticmethod
    def _decision_confidence(result: GuardResult) -> float:
        if not result.evidence:
            return 1.0
        if result.decision == Decision.ALLOW:
            return max(0.0, min(1.0, 1.0 - result.risk_score))
        return max(0.0, min(1.0, result.risk_score))

    def _safe_evidence(self, evidence: Evidence) -> dict[str, Any]:
        return {
            "detector": evidence.detector,
            "risk_type": evidence.risk_type.value,
            "message": evidence.message,
            "score": evidence.score,
            "snippet_hash": self._hash_text(evidence.snippet),
            "start": evidence.start,
            "end": evidence.end,
            "dimension": evidence.risk_type.dimension.value,
            "field_path": evidence.field_path,
            "step_id": evidence.step_id,
            "remediable": evidence.remediable,
        }
