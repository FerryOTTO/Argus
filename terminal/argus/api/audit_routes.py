"""HTTP and HTML views for the Audit event store."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from argus.modules.audit.original import (
    AuditJsonlError,
    AuditQuery,
    AuditRiskReviewError,
    AuditStore,
    GraphIntegrityError,
)


router = APIRouter()
UI_PATH = Path(__file__).resolve().parents[1] / "modules" / "audit" / "ui" / "index.html"
T = TypeVar("T")


class DeleteAuditTracesRequest(BaseModel):
    """Explicit trace identifiers selected by the Audit operator."""

    trace_ids: list[str]


class AuditRiskReviewRequest(BaseModel):
    """Operator decision that changes only the effective risk view."""

    dismissed: bool


def _run_query(operation: Callable[[], T]) -> T:
    """Map storage and graph failures without exposing event content or file paths."""

    try:
        return operation()
    except AuditJsonlError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "audit_jsonl_invalid",
                "message": "Audit data is unavailable because the JSONL source is invalid.",
                "line_number": exc.line_number,
            },
        ) from exc
    except AuditRiskReviewError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "audit_risk_review_invalid",
                "message": "Audit risk review data is unavailable.",
            },
        ) from exc
    except GraphIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "audit_graph_integrity_error",
                "message": str(exc),
            },
        ) from exc


def _event_reference(node: dict[str, Any]) -> dict[str, Any]:
    event = node["raw_event"]
    return {
        "event_id": event["event_id"],
        "trace_id": event["trace_id"],
        "timestamp": event["timestamp"],
        "stage": event["stage"],
        "source_module": event["source_module"],
        "action": event["action"],
        "risk_score": event["risk_score"],
        "reason": event["reason"],
        "sequence": node.get("sequence"),
        "direct_risk_source": node["direct_risk_source"],
        "original_direct_risk_source": node.get("original_direct_risk_source"),
        "risk_review_status": node.get("risk_review_status"),
    }


@router.get("/v1/audit/overview")
def get_audit_overview(module: str | None = None) -> dict[str, Any]:
    """Return global or module-specific read-only KPI and chart aggregates."""

    return _run_query(lambda: AuditQuery().overview(module=module))


@router.get("/v1/audit/traces")
def list_audit_traces(
    session_id: str | None = None,
    risk_only: bool = False,
    module: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> dict[str, Any]:
    """Return newest-first task summaries with bounded pagination, optionally filtered by module."""

    traces = _run_query(
        lambda: AuditQuery().list_traces(session_id=session_id, module=module)
    )
    if risk_only:
        traces = [item for item in traces if item["direct_risk_source_count"] > 0]
    return {
        "items": traces[offset : offset + limit],
        "total": len(traces),
        "limit": limit,
        "offset": offset,
    }


@router.delete("/v1/audit/traces")
def delete_audit_traces(request: DeleteAuditTracesRequest) -> dict[str, Any]:
    """Delete selected traces while preserving every unrelated JSONL event."""

    normalized = {
        trace_id.strip()
        for trace_id in request.trace_ids
        if isinstance(trace_id, str) and trace_id.strip()
    }
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "trace_ids_required",
                "message": "At least one non-empty trace_id is required.",
            },
        )
    if len(normalized) > 200:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "too_many_trace_ids",
                "message": "At most 200 trace_id values can be deleted at once.",
            },
        )

    result = _run_query(lambda: AuditStore().delete_traces(normalized))
    return {
        "requested_trace_count": len(normalized),
        "deleted_trace_count": len(result["deleted_trace_ids"]),
        **result,
    }


@router.get("/v1/audit/traces/{trace_id}")
def get_audit_trace(trace_id: str) -> dict[str, Any]:
    """Return one isolated task graph as ordered nodes and evidence edges."""

    trace = _run_query(lambda: AuditQuery().get_trace(trace_id))
    if trace is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "trace_not_found", "message": "Audit trace not found."},
        )
    nodes = trace["nodes"]
    return {
        **trace,
        "risk_event_count": len(trace["direct_risk_source_ids"]),
        "started_at": nodes[0]["timestamp"],
        "ended_at": nodes[-1]["timestamp"],
    }


@router.get("/v1/audit/events/{event_id}")
def get_audit_event(event_id: str) -> dict[str, Any]:
    """Return a complete event plus its immediate graph neighborhood."""

    query = AuditQuery()
    event = _run_query(lambda: query.get_event(event_id))
    if event is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "event_not_found", "message": "Audit event not found."},
        )
    trace = _run_query(lambda: query.get_trace(event["trace_id"]))
    assert trace is not None
    by_id = {node["node_id"]: node for node in trace["nodes"]}
    incoming = [edge for edge in trace["edges"] if edge["target"] == event_id]
    outgoing = [edge for edge in trace["edges"] if edge["source"] == event_id]
    return {
        **event,
        "direct_risk_source": by_id[event_id]["direct_risk_source"],
        "original_direct_risk_source": by_id[event_id].get(
            "original_direct_risk_source"
        ),
        "risk_review_status": by_id[event_id].get("risk_review_status"),
        "parents": [_event_reference(by_id[edge["source"]]) for edge in incoming],
        "children": [_event_reference(by_id[edge["target"]]) for edge in outgoing],
        "incoming_edges": incoming,
        "outgoing_edges": outgoing,
    }


@router.put("/v1/audit/events/{event_id}/risk-review")
def review_audit_event_risk(
    event_id: str,
    request: AuditRiskReviewRequest,
) -> dict[str, Any]:
    """Persist an operator override without mutating the AuditEvent JSONL."""

    query = AuditQuery()
    event = _run_query(lambda: query.get_event(event_id))
    if event is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "event_not_found", "message": "Audit event not found."},
        )
    trace = _run_query(lambda: query.get_trace(event["trace_id"]))
    assert trace is not None
    node = next(item for item in trace["nodes"] if item["node_id"] == event_id)
    if request.dismissed and node.get("original_direct_risk_source") is not True:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "event_not_original_risk_source",
                "message": "Only an original direct risk source can be dismissed.",
            },
        )
    review = _run_query(
        lambda: query.review_store.set_dismissed(
            event_id=event_id,
            trace_id=event["trace_id"],
            dismissed=request.dismissed,
        )
    )
    refreshed = _run_query(lambda: query.get_trace(event["trace_id"]))
    assert refreshed is not None
    refreshed_node = next(
        item for item in refreshed["nodes"] if item["node_id"] == event_id
    )
    return {
        **review,
        "direct_risk_source": refreshed_node["direct_risk_source"],
        "original_direct_risk_source": refreshed_node[
            "original_direct_risk_source"
        ],
        "risk_review_status": refreshed_node.get("risk_review_status"),
    }


def _trace_paths(
    event_id: str,
    direction: str,
    max_depth: int,
    max_paths: int,
) -> dict[str, Any]:
    query = AuditQuery()

    def operation() -> dict[str, Any]:
        try:
            method = query.causes if direction == "causes" else query.impacts
            return method(event_id, max_depth=max_depth, max_paths=max_paths)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "event_not_found",
                    "message": "Audit event not found.",
                },
            ) from exc
        except ValueError as exc:
            if "not a direct risk source" in str(exc):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "event_not_direct_risk_source",
                        "message": "This event is not a direct risk investigation source.",
                    },
                ) from exc
            raise

    return _run_query(operation)


@router.get("/v1/audit/events/{event_id}/causes")
def get_audit_causes(
    event_id: str,
    max_depth: int = Query(default=8, ge=1, le=64),
    max_paths: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    """Reuse AuditQuery.causes for bounded reverse investigation."""

    return _trace_paths(event_id, "causes", max_depth, max_paths)


@router.get("/v1/audit/events/{event_id}/impacts")
def get_audit_impacts(
    event_id: str,
    max_depth: int = Query(default=8, ge=1, le=64),
    max_paths: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    """Reuse AuditQuery.impacts for bounded forward investigation."""

    return _trace_paths(event_id, "impacts", max_depth, max_paths)


@router.get("/audit", include_in_schema=False)
def audit_explorer() -> FileResponse:
    """Serve the dependency-free, local Audit explorer."""

    return FileResponse(UI_PATH, media_type="text/html")


@router.get("/audit/coder/assets/{filename}", include_in_schema=False)
@router.get("/coder/assets/{filename}", include_in_schema=False)
def audit_coder_asset(filename: str) -> FileResponse:
    """Serve MiMo Code typography assets (e.g. self-hosted fonts)."""

    target = (UI_PATH.parent / "coder" / "assets" / filename).resolve()
    if target.is_file():
        media_type = "font/woff2" if filename.endswith(".woff2") else "application/octet-stream"
        return FileResponse(target, media_type=media_type)
    raise HTTPException(status_code=404, detail="Asset not found")

