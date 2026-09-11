from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from io_guard.adapters.argus_adapter import IOGuardAdapter
from io_guard.argus_contracts import RequestContext, SecurityRequest
from io_guard.detectors.semantic import SemanticDetector
from io_guard.pipeline import IOGuard
from io_guard.service import GuardService


def request(stage: str, payload: dict) -> SecurityRequest:
    return SecurityRequest(
        context=RequestContext(
            trace_id=f"adapter-{stage}",
            session_id="session",
            user_id="user",
            stage=stage,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
        payload=payload,
    )


def test_adapter_preserves_input_contract() -> None:
    adapter = IOGuardAdapter(
        GuardService(IOGuard(semantic_detector=SemanticDetector()))
    )
    result = asyncio.run(adapter.run(request("input", {"text": "正常问题"})))

    assert result.module == "io_guard.input"
    assert result.action == "allow"
    assert result.modified_data is None


def test_adapter_returns_sanitized_data_only_for_rewrite() -> None:
    adapter = IOGuardAdapter(
        GuardService(IOGuard(semantic_detector=SemanticDetector()))
    )
    result = asyncio.run(
        adapter.run(request("output", {"text": "邮箱是 test@example.com"}))
    )

    assert result.action == "rewrite"
    assert result.modified_data == {"text": "邮箱是 [EMAIL]"}
    assert result.details["primary_label"] == (
        "unauthorized_information_disclosure"
    )
    assert result.details["mitigated"] is True


def test_adapter_rejects_unknown_stage_without_review_fallback() -> None:
    adapter = IOGuardAdapter(
        GuardService(IOGuard(semantic_detector=SemanticDetector())),
        on_error="block",
    )
    result = asyncio.run(adapter.run(request("tool_pre", {"text": "x"})))

    assert result.success is False
    assert result.action == "block"
    assert result.reason == "module_error"
