from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawguard.adapters.audit_adapter import AuditAdapter
from clawguard.api.main import app
from clawguard.common.models import ModuleResult, RequestContext, SecurityRequest
from clawguard.core.registry import registry
from clawguard.modules.audit.integration import emit_module_audit_event


CLIENT = TestClient(app)


class StaticModuleAdapter:
    def __init__(self, result: ModuleResult) -> None:
        self.result = result
        self.calls = 0

    async def run(self, _request: SecurityRequest) -> ModuleResult:
        self.calls += 1
        return self.result


class CapturingModuleAdapter(StaticModuleAdapter):
    def __init__(self, result: ModuleResult) -> None:
        super().__init__(result)
        self.requests: list[SecurityRequest] = []

    async def run(self, request: SecurityRequest) -> ModuleResult:
        self.requests.append(request)
        return await super().run(request)


class RaisingModuleAdapter:
    async def run(self, _request: SecurityRequest) -> ModuleResult:
        raise RuntimeError("synthetic retrieval failure")


class RaisingAuditAdapter:
    async def run(self, _request: SecurityRequest) -> ModuleResult:
        raise OSError("synthetic audit failure")


def content_request(
    *,
    trace_id: str = "trace-content",
    tool_call_id: str | None = "call-content-001",
    sequence: int | None = 0,
) -> dict:
    payload = {
        "tool_name": "web_fetch",
        "source": "web_fetch",
        "url": "https://example.test/synthetic",
        "content": "synthetic external page body",
        "metadata": {"hook": "agent_tool_result_middleware"},
    }
    if tool_call_id is not None:
        payload["tool_call_id"] = tool_call_id
    if sequence is not None:
        payload["sequence"] = sequence
    return {
        "context": {
            "trace_id": trace_id,
            "session_id": "session-content",
            "user_id": "user-content",
            "stage": "content",
            "timestamp": "2026-08-17T10:00:00+08:00",
        },
        "payload": payload,
    }


def stored_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def content_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    destination = tmp_path / "content-audit.jsonl"
    retrieval = StaticModuleAdapter(
        ModuleResult(
            module="retrieval_guard",
            success=True,
            action="allow",
            risk_score=0.12,
            reason="synthetic retrieval allow",
            details={"guard": "B", "hit_window": None},
            latency_ms=4.25,
        )
    )
    context = StaticModuleAdapter(
        ModuleResult(
            module="io_guard.context",
            success=True,
            action="rewrite",
            risk_score=0.72,
            reason="synthetic context rewrite",
            modified_data={"content": "synthetic sanitized page body"},
            details={
                "policy_id": "synthetic-policy",
                "risk_types": ["indirect_prompt_injection"],
                "evidence": [{"kind": "synthetic"}],
            },
            latency_ms=7.5,
        )
    )
    monkeypatch.setenv("CLAWGUARD_AUDIT_PATH", str(destination))
    monkeypatch.setenv("CLAWGUARD_AUDIT_RISK_THRESHOLD", "0.5")
    monkeypatch.setitem(registry._adapters, "retrieval_guard", retrieval)
    monkeypatch.setitem(registry._adapters, "io_guard_context", context)
    monkeypatch.setitem(registry._adapters, "audit", AuditAdapter())
    monkeypatch.setitem(
        registry.config["modules"]["io_guard_context"], "enabled", True
    )
    return destination, retrieval, context


def test_content_results_are_written_with_complete_mapping(content_env):
    destination, retrieval, context = content_env
    request = content_request()

    response = CLIENT.post("/v1/content/check", json=request)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "rewrite"
    assert body["data"] == {"content": "synthetic sanitized page body"}
    assert retrieval.calls == context.calls == 1
    assert [item["module"] for item in body["module_results"]] == [
        "retrieval_guard",
        "io_guard.context",
    ]

    events = stored_events(destination)
    assert len(events) == 2
    retrieval_event, context_event = events
    assert retrieval_event["content"] == {
        "tool_name": "web_fetch",
        "source": "web_fetch",
        "url": "https://example.test/synthetic",
        "tool_call_id": "call-content-001",
        "content": "synthetic external page body",
    }
    assert retrieval_event["source_module"] == "retrieval_guard"
    assert retrieval_event["action"] == "allow"
    assert retrieval_event["risk_score"] == 0.12
    assert retrieval_event["reason"] == "synthetic retrieval allow"
    assert retrieval_event["metadata"]["module_success"] is True
    assert retrieval_event["metadata"]["details"] == {
        "guard": "B",
        "hit_window": None,
    }
    assert retrieval_event["metadata"]["modified_data"] is None
    assert retrieval_event["metadata"]["latency_ms"] == 4.25
    assert retrieval_event["metadata"]["error"] is None
    assert retrieval_event["metadata"]["tool_call_id"] == "call-content-001"
    assert retrieval_event["metadata"]["correlation_quality"] == "tool_call_id"
    assert retrieval_event["metadata"]["sequence"] == 2

    assert context_event["source_module"] == "io_guard.context"
    assert context_event["action"] == "rewrite"
    assert context_event["risk_score"] == 0.72
    assert context_event["reason"] == "synthetic context rewrite"
    assert context_event["metadata"]["modified_data"] == {
        "content": "synthetic sanitized page body"
    }
    assert context_event["metadata"]["details"]["policy_id"] == (
        "synthetic-policy"
    )
    assert context_event["metadata"]["parent_event_id"] == (
        retrieval_event["event_id"]
    )
    assert context_event["metadata"]["sequence"] == 3


def test_retrieval_rewrite_is_forwarded_to_io_guard_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrieval = StaticModuleAdapter(
        ModuleResult(
            module="retrieval_guard",
            success=True,
            action="rewrite",
            reason="synthetic retrieval rewrite",
            modified_data={"content": "sanitized by retrieval"},
        )
    )
    context = CapturingModuleAdapter(
        ModuleResult(
            module="io_guard.context",
            success=True,
            action="allow",
            reason="synthetic context allow",
        )
    )
    audit = StaticModuleAdapter(
        ModuleResult(
            module="audit",
            success=True,
            action="allow",
            reason="stored",
        )
    )
    monkeypatch.setitem(registry._adapters, "retrieval_guard", retrieval)
    monkeypatch.setitem(registry._adapters, "io_guard_context", context)
    monkeypatch.setitem(registry._adapters, "audit", audit)
    monkeypatch.setitem(
        registry.config["modules"]["io_guard_context"], "enabled", True
    )

    response = CLIENT.post("/v1/content/check", json=content_request())

    assert response.status_code == 200
    assert context.calls == 1
    assert context.requests[0].payload["content"] == "sanitized by retrieval"


def test_retrieval_block_stops_before_io_guard_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrieval = StaticModuleAdapter(
        ModuleResult(
            module="retrieval_guard",
            success=True,
            action="block",
            risk_score=0.95,
            reason="synthetic retrieval block",
        )
    )
    context = CapturingModuleAdapter(
        ModuleResult(
            module="io_guard.context",
            success=True,
            action="allow",
            reason="must not run",
        )
    )
    audit = StaticModuleAdapter(
        ModuleResult(
            module="audit",
            success=True,
            action="allow",
            reason="stored",
        )
    )
    monkeypatch.setitem(registry._adapters, "retrieval_guard", retrieval)
    monkeypatch.setitem(registry._adapters, "io_guard_context", context)
    monkeypatch.setitem(registry._adapters, "audit", audit)
    monkeypatch.setitem(
        registry.config["modules"]["io_guard_context"], "enabled", True
    )

    response = CLIENT.post("/v1/content/check", json=content_request())

    assert response.status_code == 200
    assert response.json()["action"] == "block"
    assert context.calls == 0


def test_content_event_links_to_matching_tool_pre_event(content_env):
    destination, _retrieval, _context = content_env
    content_payload = content_request(trace_id="trace-linked")
    tool_request = SecurityRequest(
        context=RequestContext(
            trace_id="trace-linked",
            session_id="session-content",
            user_id="user-content",
            stage="tool_pre",
            timestamp="2026-08-17T09:59:59+08:00",
        ),
        payload={
            "tool_name": "http_request",
            "original_tool_name": "web_fetch",
            "arguments": {"url": "https://example.test/synthetic"},
            "tool_call_id": "call-content-001",
        },
    )
    asyncio.run(
        emit_module_audit_event(
            tool_request,
            ModuleResult(module="tool_guard", action="allow", reason="allowed"),
            sequence=1,
        )
    )

    response = CLIENT.post("/v1/content/check", json=content_payload)

    assert response.status_code == 200
    events = stored_events(destination)
    tool_event, retrieval_event, context_event = events
    assert retrieval_event["metadata"]["parent_event_id"] == tool_event["event_id"]
    assert context_event["metadata"]["parent_event_id"] == (
        retrieval_event["event_id"]
    )
    trace = CLIENT.get("/v1/audit/traces/trace-linked")
    assert trace.status_code == 200
    assert len(trace.json()["nodes"]) == 3


def test_second_tool_call_content_uses_later_global_sequence_slots(content_env):
    destination, _retrieval, _context = content_env

    response = CLIENT.post(
        "/v1/content/check",
        json=content_request(
            trace_id="trace-content-second-call",
            tool_call_id="call-content-002",
            sequence=1,
        ),
    )

    assert response.status_code == 200
    events = stored_events(destination)
    assert [event["metadata"]["sequence"] for event in events] == [6, 7]


def test_content_module_exception_is_audited_without_stopping_next_module(
    content_env,
    monkeypatch: pytest.MonkeyPatch,
):
    destination, _retrieval, context = content_env
    monkeypatch.setitem(
        registry._adapters, "retrieval_guard", RaisingModuleAdapter()
    )

    response = CLIENT.post(
        "/v1/content/check",
        json=content_request(trace_id="trace-content-error"),
    )

    assert response.status_code == 200
    assert context.calls == 1
    retrieval_event = stored_events(destination)[0]
    assert retrieval_event["source_module"] == "retrieval_guard"
    assert retrieval_event["action"] == "allow"
    assert retrieval_event["reason"] == "module_error"
    assert retrieval_event["metadata"]["module_success"] is False
    assert retrieval_event["metadata"]["error"] == "synthetic retrieval failure"


def test_audit_failure_does_not_change_content_security_response(
    content_env,
    monkeypatch: pytest.MonkeyPatch,
):
    destination, _retrieval, _context = content_env
    monkeypatch.setitem(registry._adapters, "audit", RaisingAuditAdapter())

    response = CLIENT.post(
        "/v1/content/check",
        json=content_request(trace_id="trace-content-audit-failure"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "rewrite"
    assert body["reason"] == "synthetic context rewrite"
    assert all(item["module"] != "audit" for item in body["module_results"])
    assert not destination.exists()


def test_identical_content_retry_is_idempotent(content_env):
    destination, retrieval, context = content_env
    request = content_request(trace_id="trace-content-retry")

    first = CLIENT.post("/v1/content/check", json=request)
    retry = CLIENT.post("/v1/content/check", json=request)

    assert first.status_code == retry.status_code == 200
    assert retrieval.calls == context.calls == 2
    events = stored_events(destination)
    assert len(events) == 2
    assert {event["source_module"] for event in events} == {
        "retrieval_guard",
        "io_guard.context",
    }


def test_disabled_context_guard_is_not_audited(
    content_env,
    monkeypatch: pytest.MonkeyPatch,
):
    destination, retrieval, context = content_env
    monkeypatch.setitem(
        registry.config["modules"]["io_guard_context"], "enabled", False
    )

    response = CLIENT.post(
        "/v1/content/check",
        json=content_request(trace_id="trace-context-disabled"),
    )

    assert response.status_code == 200
    assert retrieval.calls == 1
    assert context.calls == 0
    events = stored_events(destination)
    assert len(events) == 1
    assert events[0]["source_module"] == "retrieval_guard"


def test_missing_tool_call_id_uses_fallback_but_keeps_module_parent(content_env):
    destination, _retrieval, _context = content_env

    response = CLIENT.post(
        "/v1/content/check",
        json=content_request(
            trace_id="trace-content-fallback",
            tool_call_id=None,
        ),
    )

    assert response.status_code == 200
    retrieval_event, context_event = stored_events(destination)
    assert retrieval_event["metadata"]["correlation_quality"] == "fallback"
    assert context_event["metadata"]["correlation_quality"] == "fallback"
    assert context_event["metadata"]["parent_event_id"] == (
        retrieval_event["event_id"]
    )


def test_content_response_shape_remains_compatible(content_env):
    _destination, _retrieval, _context = content_env

    body = CLIENT.post("/v1/content/check", json=content_request()).json()

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
