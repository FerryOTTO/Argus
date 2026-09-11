from __future__ import annotations

from io_guard.detectors.semantic import SemanticDetector
from io_guard.pipeline import IOGuard
from io_guard.service import GuardService


def service() -> GuardService:
    return GuardService(IOGuard(semantic_detector=SemanticDetector()))


def test_service_keeps_original_stage_interface_and_enriches_response() -> None:
    result = service().check(
        "input",
        {
            "content": "请总结这份会议纪要",
            "trace_id": "service-safe",
            "metadata": {"step_id": "step-1"},
        },
    )

    assert result["decision"] == "allow"
    assert result["verdict"] == "safe"
    assert result["primary_label"] is None
    assert result["event"]["trace_id"] == "service-safe"
    assert result["processing_metadata"]["trajectory"]["step_count"] == 1


def test_context_source_metadata_keeps_tool_result_routing() -> None:
    result = service().check(
        "context",
        {
            "content": "工具返回的普通内容",
            "trace_id": "service-tool",
            "metadata": {"tool_name": "search", "source": "tool_result"},
        },
    )

    assert result["event"]["content"]["source_type"] == "tool_result"


def test_service_never_returns_manual_review() -> None:
    values = [
        service().check("input", {"content": "普通输入"}),
        service().check(
            "context",
            {
                "content": "来源不确定",
                "metadata": {"verification_status": "unverified"},
            },
        ),
        service().check("output", {"content": "邮箱 test@example.com"}),
    ]

    assert {item["decision"] for item in values} <= {
        "allow",
        "rewrite",
        "block",
    }
