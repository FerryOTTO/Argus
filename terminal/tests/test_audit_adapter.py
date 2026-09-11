from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from argus.adapters.audit_adapter import AuditAdapter
from argus.api.main import app
from argus.common.models import RequestContext, SecurityRequest
from argus.core.registry import registry


def audit_event(**overrides):
    event = {
        "event_id": "audit-adapter-001",
        "trace_id": "trace-adapter",
        "session_id": "session-adapter",
        "user_id": "user-adapter",
        "timestamp": "2026-08-09T10:00:00+08:00",
        "stage": "tool_pre",
        "source_module": "tool_guard",
        "action": "block",
        "risk_score": 0.92,
        "reason": "synthetic upstream reason",
        "content": {"tool_name": "synthetic_tool"},
        "metadata": {"sequence": 1},
    }
    event.update(overrides)
    return event


def request(payload):
    return SecurityRequest(
        context=RequestContext(
            trace_id="trace-adapter",
            session_id="session-adapter",
            user_id="user-adapter",
            stage="audit",
            timestamp="2026-08-09T10:00:00+08:00",
        ),
        payload=payload,
    )


def run_adapter(adapter, payload):
    return asyncio.run(adapter.run(request(payload)))


def test_valid_audit_event_is_written_and_original_values_are_preserved(
    tmp_path, monkeypatch
):
    destination = tmp_path / "audit.jsonl"
    monkeypatch.setenv("ARGUS_AUDIT_PATH", str(destination))

    result = run_adapter(AuditAdapter(), audit_event())

    assert result.success is True
    assert result.action == "allow"
    assert result.reason == "audit_recorded"
    assert result.risk_score == 0.92
    assert result.details["stored"] is True
    assert result.details["event_id"] == "audit-adapter-001"
    assert result.details["trace_id"] == "trace-adapter"
    stored = json.loads(destination.read_text(encoding="utf-8"))
    for field in (
        "source_module",
        "action",
        "risk_score",
        "reason",
        "content",
        "metadata",
    ):
        assert stored[field] == audit_event()[field]
    assert "risk_level" not in stored


def test_audit_endpoint_no_longer_returns_mock_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_AUDIT_PATH", str(tmp_path / "api.jsonl"))
    response = TestClient(app).post("/v1/audit/event", json=audit_event())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["action"] == "allow"
    assert body["reason"] == "audit_recorded"
    assert body["reason"] != "mock_audit_recorded"
    assert body["details"]["stored"] is True


def test_low_and_high_scores_only_change_direct_risk_marker(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ARGUS_AUDIT_PATH", str(tmp_path / "risk.jsonl"))
    monkeypatch.setenv("ARGUS_AUDIT_RISK_THRESHOLD", "0.5")
    adapter = AuditAdapter()

    low = run_adapter(
        adapter, audit_event(event_id="low", risk_score=0.49, reason="low original")
    )
    high = run_adapter(
        adapter, audit_event(event_id="high", risk_score=0.92, reason="high original")
    )

    assert low.success and high.success
    assert low.details["direct_risk_source"] is False
    assert high.details["direct_risk_source"] is True
    records = [
        json.loads(line)
        for line in (tmp_path / "risk.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(item["risk_score"], item["reason"]) for item in records] == [
        (0.49, "low original"),
        (0.92, "high original"),
    ]
    assert all("risk_level" not in item for item in records)


def test_identical_event_retry_is_idempotent_and_trace_remains_queryable(
    tmp_path, monkeypatch
):
    destination = tmp_path / "idempotent.jsonl"
    monkeypatch.setenv("ARGUS_AUDIT_PATH", str(destination))
    client = TestClient(app)

    first = client.post("/v1/audit/event", json=audit_event())
    retry = client.post("/v1/audit/event", json=audit_event())

    assert first.status_code == retry.status_code == 200
    assert first.json()["success"] is True
    assert retry.json()["success"] is True
    assert len(destination.read_text(encoding="utf-8").splitlines()) == 1

    from argus.modules.audit.original import AuditQuery, AuditStore

    trace = AuditQuery(AuditStore(destination)).get_trace("trace-adapter")
    assert trace is not None
    assert [node["event_id"] for node in trace["nodes"]] == [
        "audit-adapter-001"
    ]


def test_conflicting_duplicate_event_is_rejected_without_changing_log(
    tmp_path, monkeypatch
):
    destination = tmp_path / "conflict.jsonl"
    monkeypatch.setenv("ARGUS_AUDIT_PATH", str(destination))
    adapter = AuditAdapter()

    first = run_adapter(adapter, audit_event())
    conflict = run_adapter(
        adapter,
        audit_event(reason="conflicting upstream reason"),
    )

    assert first.success is True
    assert conflict.success is False
    assert conflict.action == "allow"
    assert conflict.reason == "audit_write_error"
    assert "conflicting duplicate event_id" in (conflict.error or "")
    records = destination.read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    assert json.loads(records[0])["reason"] == "synthetic upstream reason"


def test_write_failure_is_fail_open_and_does_not_escape():
    def fail(_event):
        raise OSError("synthetic write failure")

    result = run_adapter(AuditAdapter(recorder=fail), audit_event())

    assert result.success is False
    assert result.action == "allow"
    assert result.reason == "audit_write_error"
    assert result.error == "synthetic write failure"


def test_write_failure_does_not_make_fastapi_return_unhandled_500(monkeypatch):
    def fail(_event):
        raise OSError("synthetic endpoint failure")

    monkeypatch.setitem(registry._adapters, "audit", AuditAdapter(recorder=fail))
    response = TestClient(app).post("/v1/audit/event", json=audit_event())

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["action"] == "allow"
    assert response.json()["reason"] == "audit_write_error"


def test_adapter_revalidates_payload_before_writing(tmp_path, monkeypatch):
    destination = tmp_path / "invalid.jsonl"
    monkeypatch.setenv("ARGUS_AUDIT_PATH", str(destination))
    invalid = audit_event()
    invalid.pop("event_id")

    result = run_adapter(AuditAdapter(), invalid)

    assert result.success is False
    assert result.action == "allow"
    assert result.reason == "audit_write_error"
    assert not destination.exists()
