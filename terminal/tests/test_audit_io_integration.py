from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawguard.adapters.audit_adapter import AuditAdapter
from clawguard.api.main import app
from clawguard.common.models import ModuleResult, SecurityRequest
from clawguard.core.registry import registry


CLIENT = TestClient(app)


class StaticModuleAdapter:
    def __init__(self, result: ModuleResult) -> None:
        self.result = result
        self.calls = 0

    async def run(self, _request: SecurityRequest) -> ModuleResult:
        self.calls += 1
        return self.result


class RaisingAuditAdapter:
    async def run(self, _request: SecurityRequest) -> ModuleResult:
        raise OSError("synthetic audit failure")


def security_request(stage: str, *, trace_id: str) -> dict:
    payload = {
        "text": (
            "synthetic blocked input"
            if stage == "input"
            else "Contact test@example.com"
        ),
        "channel": "synthetic-channel",
        "purpose": "synthetic-test",
        "metadata": {"hook": f"synthetic-{stage}-hook"},
    }
    return {
        "context": {
            "trace_id": trace_id,
            "session_id": "session-io-audit",
            "user_id": "user-io-audit",
            "stage": stage,
            "timestamp": "2026-08-23T23:30:00+08:00",
        },
        "payload": payload,
    }


def stored_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture
def io_audit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    destination = tmp_path / "io-audit.jsonl"
    input_adapter = StaticModuleAdapter(
        ModuleResult(
            module="io_guard.input",
            success=True,
            action="block",
            risk_score=0.94,
            reason="synthetic prompt injection",
            details={"risk_types": ["prompt_injection"]},
            latency_ms=1.25,
        )
    )
    output_adapter = StaticModuleAdapter(
        ModuleResult(
            module="io_guard.output",
            success=True,
            action="rewrite",
            risk_score=0.72,
            reason="synthetic output rewrite",
            modified_data={"text": "Contact [EMAIL]"},
            details={"risk_types": ["sensitive_data"]},
            latency_ms=1.5,
        )
    )
    monkeypatch.setenv("CLAWGUARD_AUDIT_PATH", str(destination))
    monkeypatch.setenv("CLAWGUARD_AUDIT_RISK_THRESHOLD", "0.5")
    monkeypatch.setitem(registry._adapters, "io_guard_input", input_adapter)
    monkeypatch.setitem(registry._adapters, "io_guard_output", output_adapter)
    monkeypatch.setitem(registry._adapters, "audit", AuditAdapter())
    return destination, input_adapter, output_adapter


def test_blocked_input_is_written_with_original_payload(io_audit_env):
    destination, input_adapter, _output_adapter = io_audit_env
    request = security_request("input", trace_id="trace-input-audit")

    response = CLIENT.post("/v1/input/check", json=request)

    assert response.status_code == 200
    assert response.json()["action"] == "block"
    assert input_adapter.calls == 1
    events = stored_events(destination)
    assert len(events) == 1
    event = events[0]
    assert event["trace_id"] == "trace-input-audit"
    assert event["stage"] == "input"
    assert event["source_module"] == "io_guard.input"
    assert event["action"] == "block"
    assert event["risk_score"] == 0.94
    assert event["reason"] == "synthetic prompt injection"
    assert event["content"] == request["payload"]
    assert event["metadata"]["details"] == {
        "risk_types": ["prompt_injection"]
    }


def test_rewritten_output_is_written_with_original_and_modified_data(io_audit_env):
    destination, _input_adapter, output_adapter = io_audit_env
    request = security_request("output", trace_id="trace-output-audit")

    response = CLIENT.post("/v1/output/check", json=request)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "rewrite"
    assert body["data"] == {"text": "Contact [EMAIL]"}
    assert output_adapter.calls == 1
    events = stored_events(destination)
    assert len(events) == 1
    event = events[0]
    assert event["trace_id"] == "trace-output-audit"
    assert event["stage"] == "output"
    assert event["source_module"] == "io_guard.output"
    assert event["action"] == "rewrite"
    assert event["content"] == request["payload"]
    assert event["metadata"]["modified_data"] == {
        "text": "Contact [EMAIL]"
    }


@pytest.mark.parametrize(
    ("endpoint", "stage", "expected_action"),
    [
        ("/v1/input/check", "input", "block"),
        ("/v1/output/check", "output", "rewrite"),
    ],
)
def test_audit_failure_does_not_change_security_decision(
    io_audit_env,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    stage: str,
    expected_action: str,
):
    destination, _input_adapter, _output_adapter = io_audit_env
    monkeypatch.setitem(registry._adapters, "audit", RaisingAuditAdapter())

    response = CLIENT.post(
        endpoint,
        json=security_request(stage, trace_id=f"trace-{stage}-audit-failure"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == expected_action
    assert all(item["module"] != "audit" for item in body["module_results"])
    assert not destination.exists()


def test_identical_blocked_input_retry_is_idempotent(io_audit_env):
    destination, input_adapter, _output_adapter = io_audit_env
    request = security_request("input", trace_id="trace-input-retry")

    first = CLIENT.post("/v1/input/check", json=request)
    retry = CLIENT.post("/v1/input/check", json=request)

    assert first.status_code == retry.status_code == 200
    assert first.json()["action"] == retry.json()["action"] == "block"
    assert input_adapter.calls == 2
    assert len(stored_events(destination)) == 1
