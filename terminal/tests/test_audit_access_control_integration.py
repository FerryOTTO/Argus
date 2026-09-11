from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argus.adapters.access_control_adapter import AccessControlAdapter
from argus.adapters.audit_adapter import AuditAdapter
from argus.api.main import app
from argus.common.models import ModuleResult, RequestContext, SecurityRequest
from argus.core.registry import registry
from argus.modules.audit.integration import emit_module_audit_event


CLIENT = TestClient(app)


class CountingToolAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, _request: SecurityRequest) -> ModuleResult:
        self.calls += 1
        return ModuleResult(
            module="tool_guard",
            success=True,
            action="allow",
            risk_score=0.31,
            reason="synthetic tool guard score=0.82",
            details={"score": 0.82, "chain_length": 1},
            latency_ms=12.345,
        )


class RaisingAccessAdapter:
    async def run(self, _request: SecurityRequest) -> ModuleResult:
        raise RuntimeError("synthetic access failure")


class RaisingAuditAdapter:
    async def run(self, _request: SecurityRequest) -> ModuleResult:
        raise OSError("synthetic audit failure")


class CaptureAuditAdapter:
    def __init__(self) -> None:
        self.requests: list[SecurityRequest] = []

    async def run(self, request: SecurityRequest) -> ModuleResult:
        self.requests.append(request)
        return ModuleResult(module="audit", action="allow", reason="captured")


def security_request(
    *,
    trace_id: str = "trace-access-allow",
    user_id: str = "user_01",
    tool_name: str = "read_file",
    tool_call_id: str | None = "call-access-001",
    path: str = "C:/Users/Public/synthetic.txt",
    database: str = "",
    sequence: int | None = 0,
) -> dict:
    payload = {
        "tool_name": tool_name,
        "arguments": {"path": path} if path else {},
        "database": database,
        "identity_correlation_quality": "sender_id",
    }
    if sequence is not None:
        payload["sequence"] = sequence
    original_name = {
        "read_file": "read",
        "write_file": "write",
        "execute_bash": "exec",
        "http_request": "web_fetch",
    }.get(tool_name)
    if original_name is not None:
        payload["original_tool_name"] = original_name
    if tool_call_id is not None:
        payload["tool_call_id"] = tool_call_id
    return {
        "context": {
            "trace_id": trace_id,
            "session_id": "session-access",
            "user_id": user_id,
            "stage": "tool_pre",
            "timestamp": "2026-08-16T09:00:00+08:00",
        },
        "payload": payload,
    }


def stored_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def integration_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    destination = tmp_path / "access-control-audit.jsonl"
    tool_adapter = CountingToolAdapter()
    monkeypatch.setenv("ARGUS_AUDIT_PATH", str(destination))
    monkeypatch.setenv("ARGUS_AUDIT_RISK_THRESHOLD", "0.5")
    monkeypatch.setitem(registry._adapters, "access_control", AccessControlAdapter())
    monkeypatch.setitem(registry._adapters, "tool_guard", tool_adapter)
    monkeypatch.setitem(registry._adapters, "audit", AuditAdapter())
    return destination, tool_adapter


def test_allow_result_is_automatically_written_with_complete_mapping(
    integration_env,
):
    destination, tool_adapter = integration_env
    request = security_request(database="db:public_db")

    response = CLIENT.post("/v1/tool/pre_check", json=request)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "allow"
    assert tool_adapter.calls == 1
    assert [item["module"] for item in body["module_results"]] == [
        "access_control",
        "tool_guard",
    ]
    access_result = body["module_results"][0]
    events = stored_events(destination)
    assert len(events) == 2
    event, tool_event = events
    assert event["trace_id"] == request["context"]["trace_id"]
    assert event["session_id"] == request["context"]["session_id"]
    assert event["user_id"] == request["context"]["user_id"]
    assert event["stage"] == "tool_pre"
    assert event["source_module"] == "access_control"
    assert event["action"] == access_result["action"]
    assert event["risk_score"] == access_result["risk_score"]
    assert event["reason"] == access_result["reason"]
    assert event["content"] == {
        "tool_name": "read_file",
        "original_tool_name": "read",
        "arguments": {"path": "C:/Users/Public/synthetic.txt"},
        "path": os.path.normpath("C:/Users/Public/synthetic.txt"),
        "database": "db:public_db",
    }
    assert event["metadata"]["tool_call_id"] == "call-access-001"
    assert event["metadata"]["module_success"] is True
    assert isinstance(event["metadata"]["latency_ms"], float)
    assert event["metadata"]["error"] is None
    assert event["metadata"]["correlation_quality"] == "tool_call_id"
    assert event["metadata"]["identity_correlation_quality"] == "sender_id"
    assert event["metadata"]["sequence"] == 0
    assert tool_event["event_id"] != event["event_id"]
    assert tool_event["trace_id"] == event["trace_id"]
    assert tool_event["session_id"] == event["session_id"]
    assert tool_event["source_module"] == "tool_guard"
    assert tool_event["action"] == "allow"
    assert tool_event["risk_score"] == 0.31
    assert tool_event["reason"] == "synthetic tool guard score=0.82"
    assert tool_event["metadata"]["details"] == {
        "score": 0.82,
        "chain_length": 1,
    }
    assert tool_event["metadata"]["module_success"] is True
    assert tool_event["metadata"]["latency_ms"] == 12.345
    assert tool_event["metadata"]["error"] is None
    assert tool_event["metadata"]["tool_call_id"] == "call-access-001"
    assert tool_event["metadata"]["sequence"] == 1
    assert tool_event["metadata"]["parent_event_id"] == event["event_id"]


def test_block_is_written_before_early_return_and_tool_guard_is_not_run(
    integration_env,
):
    destination, tool_adapter = integration_env
    request = security_request(
        trace_id="trace-access-block",
        user_id="user_public",
        tool_name="execute_bash",
        tool_call_id="call-access-block",
        path="",
    )

    response = CLIENT.post("/v1/tool/pre_check", json=request)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "block"
    assert body["risk_score"] == 1.0
    assert tool_adapter.calls == 0
    assert [item["module"] for item in body["module_results"]] == [
        "access_control"
    ]
    event = stored_events(destination)[0]
    assert event["action"] == "block"
    assert event["risk_score"] == 1.0
    assert event["reason"] == body["reason"]


def test_disabled_tool_guard_is_skipped_without_faking_a_tool_guard_event(
    integration_env,
    monkeypatch: pytest.MonkeyPatch,
):
    destination, tool_adapter = integration_env
    monkeypatch.setitem(
        registry.config["modules"]["tool_guard"], "enabled", False
    )

    response = CLIENT.post(
        "/v1/tool/pre_check",
        json=security_request(trace_id="trace-tool-guard-disabled"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "allow"
    assert [item["module"] for item in body["module_results"]] == [
        "access_control"
    ]
    assert tool_adapter.calls == 0
    events = stored_events(destination)
    assert len(events) == 1
    assert events[0]["source_module"] == "access_control"
    assert events[0]["action"] == "allow"


def test_access_control_exception_result_is_still_audited(
    integration_env, monkeypatch: pytest.MonkeyPatch
):
    destination, tool_adapter = integration_env
    monkeypatch.setitem(registry._adapters, "access_control", RaisingAccessAdapter())

    response = CLIENT.post(
        "/v1/tool/pre_check",
        json=security_request(trace_id="trace-access-error"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "block"
    assert body["reason"] == "module_error"
    assert tool_adapter.calls == 0
    event = stored_events(destination)[0]
    assert event["source_module"] == "access_control"
    assert event["action"] == "block"
    assert event["risk_score"] == 1.0
    assert event["reason"] == "module_error"
    assert event["metadata"]["module_success"] is False
    assert event["metadata"]["error"] == "synthetic access failure"


def test_identical_http_retry_is_idempotent_despite_latency_drift(integration_env):
    destination, tool_adapter = integration_env
    request = security_request()

    first = CLIENT.post("/v1/tool/pre_check", json=request)
    retry = CLIENT.post("/v1/tool/pre_check", json=request)

    assert first.status_code == retry.status_code == 200
    assert first.json()["action"] == retry.json()["action"] == "allow"
    events = stored_events(destination)
    assert len(events) == 2
    assert all(event["event_id"].startswith("module-audit-") for event in events)
    assert {event["source_module"] for event in events} == {
        "access_control",
        "tool_guard",
    }
    assert tool_adapter.calls == 2


def test_different_tool_call_ids_create_distinct_events(integration_env):
    destination, _tool_adapter = integration_env
    first = security_request(tool_call_id="call-distinct-001")
    second = security_request(tool_call_id="call-distinct-002")

    assert CLIENT.post("/v1/tool/pre_check", json=first).status_code == 200
    assert CLIENT.post("/v1/tool/pre_check", json=second).status_code == 200

    events = stored_events(destination)
    assert len(events) == 4
    assert len({event["event_id"] for event in events}) == 4
    assert {event["metadata"]["tool_call_id"] for event in events} == {
        "call-distinct-001",
        "call-distinct-002",
    }


def test_consecutive_tool_calls_use_disjoint_global_sequence_slots(
    integration_env,
):
    destination, _tool_adapter = integration_env
    first = security_request(
        trace_id="trace-multi-call",
        tool_call_id="call-multi-001",
        sequence=0,
    )
    second = security_request(
        trace_id="trace-multi-call",
        tool_call_id="call-multi-002",
        sequence=1,
    )

    assert CLIENT.post("/v1/tool/pre_check", json=first).status_code == 200
    assert CLIENT.post("/v1/tool/pre_check", json=second).status_code == 200

    events = stored_events(destination)
    assert [event["metadata"]["sequence"] for event in events] == [0, 1, 4, 5]
    trace = CLIENT.get("/v1/audit/traces/trace-multi-call").json()
    assert [node["sequence"] for node in trace["nodes"]] == [0, 1, 4, 5]


def test_missing_tool_call_id_uses_explicit_fallback_marker(integration_env):
    destination, _tool_adapter = integration_env

    response = CLIENT.post(
        "/v1/tool/pre_check",
        json=security_request(tool_call_id=None),
    )

    assert response.status_code == 200
    event = stored_events(destination)[0]
    assert event["metadata"]["tool_call_id"] is None
    assert event["metadata"]["correlation_quality"] == "fallback"
    assert len(event["metadata"]["request_fingerprint"]) == 64


def test_missing_call_sequence_omits_sequence_instead_of_reusing_zero(
    integration_env,
):
    destination, _tool_adapter = integration_env

    response = CLIENT.post(
        "/v1/tool/pre_check",
        json=security_request(
            trace_id="trace-no-sequence",
            tool_call_id="call-no-sequence",
            sequence=None,
        ),
    )

    assert response.status_code == 200
    events = stored_events(destination)
    assert len(events) == 2
    assert all("sequence" not in event["metadata"] for event in events)


@pytest.mark.parametrize(
    "request_payload,expected_action,expected_tool_calls",
    [
        (security_request(trace_id="trace-audit-fail-allow"), "allow", 1),
        (
            security_request(
                trace_id="trace-audit-fail-block",
                user_id="user_public",
                tool_name="execute_bash",
                tool_call_id="call-audit-fail-block",
                path="",
            ),
            "block",
            0,
        ),
    ],
)
def test_audit_exception_never_changes_access_decision_or_returns_500(
    integration_env,
    monkeypatch: pytest.MonkeyPatch,
    request_payload: dict,
    expected_action: str,
    expected_tool_calls: int,
):
    destination, tool_adapter = integration_env
    monkeypatch.setitem(registry._adapters, "audit", RaisingAuditAdapter())

    response = CLIENT.post("/v1/tool/pre_check", json=request_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == expected_action
    assert tool_adapter.calls == expected_tool_calls
    assert all(item["module"] != "audit" for item in body["module_results"])
    assert not destination.exists()


def test_changed_decision_with_same_event_id_keeps_store_conflict_protection(
    integration_env,
):
    destination, _tool_adapter = integration_env
    request_payload = security_request()
    request = SecurityRequest.model_validate(request_payload)
    first_result = ModuleResult(
        module="access_control",
        action="allow",
        risk_score=0.0,
        reason="first stable decision",
        latency_ms=1.0,
    )
    changed_result = first_result.model_copy(
        update={"action": "block", "risk_score": 1.0, "reason": "changed decision"}
    )

    first = asyncio.run(emit_module_audit_event(request, first_result))
    conflict = asyncio.run(emit_module_audit_event(request, changed_result))

    assert first.success is True
    assert conflict.success is False
    assert conflict.reason == "audit_write_error"
    events = stored_events(destination)
    assert len(events) == 1
    assert events[0]["reason"] == "first stable decision"


def test_explicit_parent_and_sequence_are_preserved_with_injected_adapter():
    adapter = CaptureAuditAdapter()
    request = SecurityRequest.model_validate(security_request())
    result = ModuleResult(
        module="access_control",
        action="allow",
        reason="synthetic captured decision",
        latency_ms=2.5,
    )

    audit_result = asyncio.run(
        emit_module_audit_event(
            request,
            result,
            audit_adapter=adapter,
            parent_event_id="synthetic-parent-event",
            sequence=7,
        )
    )

    assert audit_result.success is True
    event = adapter.requests[0].payload
    assert event["metadata"]["parent_event_id"] == "synthetic-parent-event"
    assert event["metadata"]["sequence"] == 7


def test_audit_query_api_and_page_source_see_real_access_control_event(
    integration_env,
):
    destination, _tool_adapter = integration_env
    request = security_request(trace_id="trace-access-ui")

    response = CLIENT.post("/v1/tool/pre_check", json=request)
    traces = CLIENT.get("/v1/audit/traces").json()
    trace = CLIENT.get("/v1/audit/traces/trace-access-ui").json()
    page = CLIENT.get("/audit")

    assert response.status_code == 200
    assert traces["items"][0]["trace_id"] == "trace-access-ui"
    assert [node["source_module"] for node in trace["nodes"]] == [
        "access_control",
        "tool_guard",
    ]
    assert page.status_code == 200
    assert "/v1/audit/traces" in page.text
    assert len(stored_events(destination)) == 2


def test_tool_pre_response_shape_remains_compatible(integration_env):
    _destination, _tool_adapter = integration_env

    body = CLIENT.post("/v1/tool/pre_check", json=security_request()).json()

    assert set(body) == {
        "trace_id",
        "stage",
        "action",
        "risk_score",
        "reason",
        "data",
        "module_results",
    }
    assert all(item["module"] != "audit" for item in body["module_results"])


def test_query_and_page_reads_do_not_modify_jsonl(integration_env):
    destination, _tool_adapter = integration_env
    CLIENT.post("/v1/tool/pre_check", json=security_request())
    before = hashlib.sha256(destination.read_bytes()).hexdigest()

    assert CLIENT.get("/v1/audit/traces").status_code == 200
    assert CLIENT.get("/v1/audit/traces/trace-access-allow").status_code == 200
    assert CLIENT.get("/audit").status_code == 200

    after = hashlib.sha256(destination.read_bytes()).hexdigest()
    assert before == after
