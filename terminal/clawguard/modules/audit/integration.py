"""Reusable in-process emission of security module results to Audit."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

from clawguard.adapters.audit_adapter import AuditAdapter
from clawguard.adapters.base import BaseAdapter
from clawguard.common.models import AuditEvent, ModuleResult, SecurityRequest
from clawguard.modules.audit.original import AuditQuery


_EVENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "clawguard:audit:module-result:v1")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _request_content(
    request: SecurityRequest,
    result: ModuleResult,
) -> dict[str, Any]:
    payload = request.model_dump(mode="json")["payload"]
    if request.context.stage in {"input", "output"}:
        # Input and output checks already receive JSON-compatible business
        # payloads from the shared FastAPI contract. Preserve that payload so
        # Audit records the text and its accompanying channel/identity context
        # instead of incorrectly projecting it into tool-call fields.
        return dict(payload)
    if request.context.stage == "content":
        content = {
            "tool_name": payload.get("tool_name", ""),
            "source": payload.get("source", ""),
            "url": payload.get("url", ""),
            "tool_call_id": payload.get("tool_call_id", ""),
        }
        if "content" in payload:
            content["content"] = payload["content"]
        if "text" in payload:
            content["text"] = payload["text"]
        return content

    arguments = payload.get("arguments", {})
    details = result.details if isinstance(result.details, Mapping) else {}
    path = details.get("path")
    if path is None and isinstance(arguments, Mapping):
        path = arguments.get("path", "")
    database = details.get("database", payload.get("database", ""))
    content = {
        "tool_name": payload.get("tool_name", ""),
        "arguments": arguments,
        "path": path or "",
        "database": database or "",
    }
    original_tool_name = payload.get("original_tool_name")
    if isinstance(original_tool_name, str):
        content["original_tool_name"] = original_tool_name
    return content


def build_module_audit_event(
    request: SecurityRequest,
    result: ModuleResult,
    *,
    parent_event_id: str | None = None,
    sequence: int | None = None,
) -> AuditEvent:
    """Map a module decision to one deterministic team AuditEvent."""

    payload = request.model_dump(mode="json")["payload"]
    content = _request_content(request, result)
    tool_call_id = payload.get("tool_call_id")
    resolved_parent = (
        parent_event_id
        if parent_event_id is not None
        else payload.get("parent_event_id")
    )
    resolved_sequence = sequence if sequence is not None else payload.get("sequence")
    request_identity = {
        "trace_id": request.context.trace_id,
        "session_id": request.context.session_id,
        "user_id": request.context.user_id,
        "timestamp": request.context.timestamp,
        "stage": request.context.stage,
        "source_module": result.module,
        "tool_call_id": tool_call_id,
        "content": content,
        "parent_event_id": resolved_parent,
        "sequence": resolved_sequence,
    }
    canonical_identity = _canonical_json(request_identity)
    request_fingerprint = hashlib.sha256(
        canonical_identity.encode("utf-8")
    ).hexdigest()
    event_id = f"module-audit-{uuid.uuid5(_EVENT_NAMESPACE, canonical_identity)}"
    result_payload = result.model_dump(mode="json")
    metadata: dict[str, Any] = {
        "tool_call_id": tool_call_id,
        "module_success": result.success,
        "details": result_payload["details"],
        "modified_data": result_payload["modified_data"],
        "latency_ms": result.latency_ms,
        "error": result.error,
        "correlation_quality": "tool_call_id" if tool_call_id else "fallback",
        "request_fingerprint": request_fingerprint,
    }
    identity_quality = payload.get("identity_correlation_quality")
    if isinstance(identity_quality, str):
        metadata["identity_correlation_quality"] = identity_quality
    if resolved_parent is not None:
        metadata["parent_event_id"] = resolved_parent
    if resolved_sequence is not None:
        metadata["sequence"] = resolved_sequence

    return AuditEvent(
        event_id=event_id,
        trace_id=request.context.trace_id,
        session_id=request.context.session_id,
        user_id=request.context.user_id,
        timestamp=request.context.timestamp,
        stage=request.context.stage,
        source_module=result.module,
        action=result.action,
        risk_score=result.risk_score,
        reason=result.reason,
        content=content,
        metadata=metadata,
    )


def _reuse_idempotent_event(candidate: AuditEvent) -> AuditEvent:
    """Reuse an exact prior decision while tolerating observed latency drift."""

    existing = AuditQuery().get_event(candidate.event_id)
    if existing is None:
        return candidate
    existing_event = AuditEvent.model_validate(existing)
    existing_payload = existing_event.model_dump(mode="json")
    candidate_payload = candidate.model_dump(mode="json")
    existing_metadata = existing_payload["metadata"]
    if "latency_ms" not in existing_metadata:
        return candidate
    candidate_payload["metadata"]["latency_ms"] = existing_metadata["latency_ms"]
    if candidate_payload == existing_payload:
        return existing_event
    return candidate


async def emit_module_audit_event(
    request: SecurityRequest,
    result: ModuleResult,
    *,
    audit_adapter: BaseAdapter | None = None,
    parent_event_id: str | None = None,
    sequence: int | None = None,
) -> ModuleResult:
    """Write through AuditAdapter and isolate every audit-side failure."""

    adapter = audit_adapter or AuditAdapter()
    try:
        event = build_module_audit_event(
            request,
            result,
            parent_event_id=parent_event_id,
            sequence=sequence,
        )
        if isinstance(adapter, AuditAdapter):
            event = _reuse_idempotent_event(event)
        audit_request = SecurityRequest(
            context=request.context.model_copy(update={"stage": "audit"}),
            payload=event.model_dump(mode="json"),
        )
        return await adapter.run(audit_request)
    except Exception as exc:
        return ModuleResult(
            module="audit",
            success=False,
            action="allow",
            risk_score=0.0,
            reason="audit_write_error",
            error=type(exc).__name__,
        )


def emitted_event_id(result: ModuleResult) -> str | None:
    """Return a recorder-confirmed event id without inferring one on failure."""

    if not result.success or not isinstance(result.details, Mapping):
        return None
    event_id = result.details.get("event_id")
    return event_id if isinstance(event_id, str) and event_id else None


def latest_tool_pre_event_id(request: SecurityRequest) -> str | None:
    """Find the latest recorded tool decision for this exact tool call."""

    tool_call_id = request.payload.get("tool_call_id")
    if not isinstance(tool_call_id, str) or not tool_call_id:
        return None
    try:
        matches = [
            event
            for event in AuditQuery().events(
                trace_id=request.context.trace_id,
                stage="tool_pre",
            )
            if event.get("metadata", {}).get("tool_call_id") == tool_call_id
        ]
    except Exception:
        return None
    return matches[-1]["event_id"] if matches else None
