from __future__ import annotations

from time import perf_counter
from typing import Any, Literal

from io_guard.adapters.base import BaseAdapter
from io_guard.service import GuardService

try:
    from argus.common.models import ModuleResult, SecurityRequest
except ModuleNotFoundError:
    # The canonical models are supplied by the integration repository.
    from io_guard.argus_contracts import ModuleResult, SecurityRequest


ErrorAction = Literal["allow", "block"]


class IOGuardAdapter(BaseAdapter):
    """Convert Argus V2.1 contracts to the original IO Guard API.

    The adapter deliberately calls :class:`GuardService` instead of reaching
    into individual detectors.  This keeps all original detection and policy
    behaviour unchanged while providing the common ``ModuleResult`` contract.
    """

    name = "io_guard"
    _STAGE_MAP = {
        "input": "input",
        "content": "context",
        "output": "output",
    }
    _MODULE_NAMES = {
        "input": "io_guard.input",
        "content": "io_guard.context",
        "output": "io_guard.output",
    }
    _CONTENT_FIELDS = {
        "input": "text",
        "content": "content",
        "output": "text",
    }

    def __init__(
        self,
        service: GuardService,
        *,
        on_error: ErrorAction = "allow",
    ) -> None:
        if on_error not in {"allow", "block"}:
            raise ValueError("on_error must be 'allow' or 'block'")
        self.service = service
        self.on_error = on_error

    async def run(self, request: SecurityRequest) -> ModuleResult:
        started = perf_counter()
        stage = str(request.context.stage)
        module_name = self._MODULE_NAMES.get(stage, f"io_guard.{stage}")
        try:
            original_stage = self._STAGE_MAP[stage]
            original_payload = self._to_original_payload(request, stage)
            raw_result = self.service.check(original_stage, original_payload)
            return self._to_module_result(
                raw_result,
                stage=stage,
                module_name=module_name,
                started=started,
                original_content=str(original_payload["content"]),
            )
        except Exception as exc:
            return ModuleResult(
                module=module_name,
                success=False,
                action=self.on_error,
                reason="module_error",
                details={"stage": stage},
                latency_ms=self._latency_ms(started),
                error=str(exc),
            )

    def _to_original_payload(
        self,
        request: SecurityRequest,
        stage: str,
    ) -> dict[str, Any]:
        field_name = self._CONTENT_FIELDS[stage]
        content = request.payload.get(field_name)
        if not isinstance(content, str):
            raise ValueError(f"payload.{field_name} must be a string")

        payload = request.payload
        metadata = self._metadata(payload)
        return {
            "content": content,
            "trace_id": request.context.trace_id,
            "session_id": request.context.session_id,
            "user_id": request.context.user_id,
            "role_level": payload.get("role_level", 0),
            "principal_type": payload.get("principal_type", "external_user"),
            "target_audience": payload.get("target_audience", "external"),
            "channel_classification": payload.get(
                "channel_classification", "public"
            ),
            "purpose": payload.get("purpose", ""),
            "allowed_data_scopes": payload.get("allowed_data_scopes", []),
            "metadata": metadata,
            "parent_event_id": payload.get("parent_event_id"),
        }

    @staticmethod
    def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
        raw_metadata = payload.get("metadata")
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        if raw_metadata is not None and not isinstance(raw_metadata, dict):
            metadata["source_metadata"] = raw_metadata
        for field_name in (
            "channel",
            "history",
            "source",
            "url",
            "tool_name",
            "tool_call_id",
        ):
            if field_name in payload:
                metadata[field_name] = payload[field_name]
        return metadata

    def _to_module_result(
        self,
        raw_result: dict[str, Any],
        *,
        stage: str,
        module_name: str,
        started: float,
        original_content: str,
    ) -> ModuleResult:
        action = str(raw_result.get("decision", "allow"))
        if action not in {"allow", "block", "rewrite"}:
            raise ValueError(f"unsupported IO Guard decision: {action}")

        sanitized_content = str(raw_result.get("sanitized_content", ""))
        risk_types = raw_result.get("risk_types", [])
        modified_data = None
        if action == "rewrite":
            output_field = "content" if stage == "content" else "text"
            modified_data = {output_field: sanitized_content}

        processing_metadata = raw_result.get("processing_metadata", {})
        details = {
            "event_id": raw_result.get("event_id"),
            "policy_id": raw_result.get("policy_id"),
            "risk_types": risk_types,
            "verdict": raw_result.get("verdict"),
            "primary_label": raw_result.get("primary_label"),
            "dimension": raw_result.get("dimension"),
            "mitigated": raw_result.get("mitigated", False),
            "evidence": raw_result.get("evidence", []),
            "processing_metadata": (
                processing_metadata
                if isinstance(processing_metadata, dict)
                else {}
            ),
        }
        return ModuleResult(
            module=module_name,
            success=True,
            action=action,
            risk_score=float(raw_result.get("risk_score", 0.0)),
            reason=str(raw_result.get("reason", "")),
            modified_data=modified_data,
            details=details,
            latency_ms=self._latency_ms(started),
        )

    @staticmethod
    def _latency_ms(started: float) -> float:
        return round((perf_counter() - started) * 1000, 3)
