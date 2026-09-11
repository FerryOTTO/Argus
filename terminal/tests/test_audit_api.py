from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawguard.api.main import app
from clawguard.modules.audit.original import AuditStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "audit" / "phase6_events.synthetic.jsonl"
CLIENT = TestClient(app)


def _fixture_events() -> list[dict]:
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def audit_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "audit-events.jsonl"
    monkeypatch.setenv("CLAWGUARD_AUDIT_PATH", str(path))
    monkeypatch.setenv("CLAWGUARD_AUDIT_RISK_THRESHOLD", "0.5")
    monkeypatch.delenv("CLAWGUARD_AUDIT_RISK_REVIEW_PATH", raising=False)
    return path


@pytest.fixture
def seeded_path(audit_path: Path) -> Path:
    store = AuditStore(audit_path)
    for event in _fixture_events():
        store.append(event)
    return audit_path


def test_empty_log_returns_empty_trace_list(audit_path: Path):
    response = CLIENT.get("/v1/audit/traces")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_trace_list_is_newest_first_and_contains_display_fields(seeded_path: Path):
    response = CLIENT.get("/v1/audit/traces")
    assert response.status_code == 200
    body = response.json()
    assert [item["trace_id"] for item in body["items"]] == [
        "trace-ui-temporal",
        "trace-ui-risk",
        "trace-ui-normal",
    ]
    assert body["items"][1] == {
        "trace_id": "trace-ui-risk",
        "session_id": "session-ui-b",
        "user_id": "user-ui",
        "event_count": 4,
        "started_at": "2026-08-15T10:00:00+08:00",
        "ended_at": "2026-08-15T10:00:03+08:00",
        "direct_risk_source_count": 1,
        "user_input": "synthetic non-sensitive prompt",
        "display_name": "synthetic non-sensitive prompt",
        "source_modules": ["io_guard", "retrieval_guard", "tool_guard"],
        "actions": ["allow", "block"],
        "max_risk_score": 0.91,
        "blocked_event_count": 1,
        "human_review_event_count": 0,
        "confirmed_edge_count": 3,
        "temporal_edge_count": 0,
        "last_stage": "output",
        "last_action": "allow",
    }


def test_trace_list_never_invents_user_input_from_tool_fields(audit_path: Path):
    event = deepcopy(_fixture_events()[1])
    event["event_id"] = "tool-only-event"
    event["trace_id"] = "trace-tool-only"
    event["metadata"] = {"sequence": 1, "synthetic": True}
    AuditStore(audit_path).append(event)

    item = CLIENT.get("/v1/audit/traces").json()["items"][0]

    assert item["trace_id"] == "trace-tool-only"
    assert item["user_input"] is None
    assert item["display_name"] == "synthetic_reader"


def test_overview_aggregates_real_events_edges_and_modules(seeded_path: Path):
    response = CLIENT.get("/v1/audit/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["event_count"] == 10
    assert body["trace_count"] == 3
    assert body["risk_trace_count"] == 1
    assert body["direct_risk_source_count"] == 1
    assert body["blocked_event_count"] == 1
    assert body["human_review_event_count"] == 0
    assert body["confirmed_edge_count"] == 5
    assert body["temporal_edge_count"] == 2
    assert body["chain_integrity_rate"] == 0.714286
    assert body["risk_trend"] == [{"bucket": "2026-08-15", "count": 1}]
    assert body["module_distribution"] == [
        {"source_module": "io_guard", "count": 6},
        {"source_module": "tool_guard", "count": 3},
        {"source_module": "retrieval_guard", "count": 1},
    ]
    assert body["generated_at"].endswith("+00:00")


def test_empty_overview_treats_edge_free_store_as_complete(audit_path: Path):
    response = CLIENT.get("/v1/audit/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["event_count"] == body["trace_count"] == 0
    assert body["confirmed_edge_count"] == body["temporal_edge_count"] == 0
    assert body["chain_integrity_rate"] == 1.0
    assert body["risk_trend"] == []
    assert body["module_distribution"] == []


def test_trace_list_risk_and_session_filters(seeded_path: Path):
    risk = CLIENT.get("/v1/audit/traces", params={"risk_only": True}).json()
    session = CLIENT.get(
        "/v1/audit/traces", params={"session_id": "session-ui-a"}
    ).json()
    assert [item["trace_id"] for item in risk["items"]] == ["trace-ui-risk"]
    assert [item["trace_id"] for item in session["items"]] == ["trace-ui-normal"]


def test_trace_list_pagination(seeded_path: Path):
    body = CLIENT.get(
        "/v1/audit/traces", params={"limit": 1, "offset": 1}
    ).json()
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert [item["trace_id"] for item in body["items"]] == ["trace-ui-risk"]


def test_delete_selected_traces_removes_only_matching_events(seeded_path: Path):
    response = CLIENT.request(
        "DELETE",
        "/v1/audit/traces",
        json={"trace_ids": ["trace-ui-risk", "trace-ui-normal"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "requested_trace_count": 2,
        "deleted_trace_count": 2,
        "deleted_trace_ids": ["trace-ui-normal", "trace-ui-risk"],
        "missing_trace_ids": [],
        "deleted_event_count": 7,
    }
    remaining = AuditStore(seeded_path).load()
    assert {event["trace_id"] for event in remaining} == {"trace-ui-temporal"}
    assert len(remaining) == 3


def test_delete_traces_is_idempotent_and_reports_missing_ids(seeded_path: Path):
    first = CLIENT.request(
        "DELETE",
        "/v1/audit/traces",
        json={"trace_ids": ["trace-ui-risk", "trace-ui-risk"]},
    )
    second = CLIENT.request(
        "DELETE",
        "/v1/audit/traces",
        json={"trace_ids": ["trace-ui-risk"]},
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["deleted_event_count"] == 4
    assert second.json()["deleted_event_count"] == 0
    assert second.json()["missing_trace_ids"] == ["trace-ui-risk"]


@pytest.mark.parametrize("trace_ids", [[], [""], ["   "]])
def test_delete_traces_rejects_empty_identifiers(
    seeded_path: Path, trace_ids: list[str]
):
    response = CLIENT.request(
        "DELETE", "/v1/audit/traces", json={"trace_ids": trace_ids}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "trace_ids_required"


def test_trace_detail_is_stably_ordered_and_preserves_temporal_inference(
    seeded_path: Path,
):
    response = CLIENT.get("/v1/audit/traces/trace-ui-temporal")
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == "trace-ui-temporal"
    assert [node["event_id"] for node in body["nodes"]] == [
        "ui-temporal-001",
        "ui-temporal-002",
        "ui-temporal-003",
    ]
    assert body["risk_event_count"] == 0
    assert all(edge["inference"] == "temporal_sequence" for edge in body["edges"])


def test_trace_detail_never_mixes_traces(seeded_path: Path):
    body = CLIENT.get("/v1/audit/traces/trace-ui-risk").json()
    assert {node["trace_id"] for node in body["nodes"]} == {"trace-ui-risk"}
    assert {edge["trace_id"] for edge in body["edges"]} == {"trace-ui-risk"}


def test_event_detail_contains_complete_event_and_neighbors(seeded_path: Path):
    response = CLIENT.get("/v1/audit/events/ui-risk-002")
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == {"tool_name": "synthetic_blocked_tool"}
    assert body["metadata"]["synthetic"] is True
    assert body["direct_risk_source"] is True
    assert [item["event_id"] for item in body["parents"]] == ["ui-risk-001"]
    assert [item["event_id"] for item in body["children"]] == ["ui-risk-003"]
    assert body["incoming_edges"][0]["relation"] == "PARENT_OF"
    assert body["outgoing_edges"][0]["relation"] == "PARENT_OF"


def test_operator_can_dismiss_risk_without_mutating_audit_jsonl(
    seeded_path: Path,
):
    before = hashlib.sha256(seeded_path.read_bytes()).hexdigest()

    response = CLIENT.put(
        "/v1/audit/events/ui-risk-002/risk-review",
        json={"dismissed": True},
    )

    assert response.status_code == 200
    assert response.json()["direct_risk_source"] is False
    assert response.json()["original_direct_risk_source"] is True
    assert response.json()["risk_review_status"] == "dismissed"
    assert hashlib.sha256(seeded_path.read_bytes()).hexdigest() == before
    assert seeded_path.with_name("audit-events.risk-reviews.json").is_file()

    event = CLIENT.get("/v1/audit/events/ui-risk-002").json()
    assert event["direct_risk_source"] is False
    assert event["original_direct_risk_source"] is True
    assert event["risk_review_status"] == "dismissed"

    trace = CLIENT.get("/v1/audit/traces/trace-ui-risk").json()
    assert trace["risk_event_count"] == 0
    reviewed = next(node for node in trace["nodes"] if node["event_id"] == "ui-risk-002")
    assert reviewed["direct_risk_source"] is False
    assert reviewed["risk_review_status"] == "dismissed"

    summary = next(
        item
        for item in CLIENT.get("/v1/audit/traces").json()["items"]
        if item["trace_id"] == "trace-ui-risk"
    )
    assert summary["direct_risk_source_count"] == 0
    assert summary["max_risk_score"] == 0.0
    overview = CLIENT.get("/v1/audit/overview").json()
    assert overview["risk_trace_count"] == 0
    assert overview["direct_risk_source_count"] == 0
    assert overview["risk_trend"] == []


def test_risk_review_is_idempotent_and_can_be_restored(seeded_path: Path):
    for _ in range(2):
        response = CLIENT.put(
            "/v1/audit/events/ui-risk-002/risk-review",
            json={"dismissed": True},
        )
        assert response.status_code == 200
        assert response.json()["risk_review_status"] == "dismissed"

    restored = CLIENT.put(
        "/v1/audit/events/ui-risk-002/risk-review",
        json={"dismissed": False},
    )
    assert restored.status_code == 200
    assert restored.json()["direct_risk_source"] is True
    assert restored.json()["risk_review_status"] is None


def test_non_risk_event_cannot_be_dismissed(seeded_path: Path):
    response = CLIENT.put(
        "/v1/audit/events/ui-normal-002/risk-review",
        json={"dismissed": True},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "event_not_original_risk_source"


def test_causes_and_impacts_endpoints_reuse_evidence_paths(seeded_path: Path):
    causes = CLIENT.get("/v1/audit/events/ui-risk-002/causes").json()
    impacts = CLIENT.get("/v1/audit/events/ui-risk-002/impacts").json()
    assert causes["direction"] == "causes"
    assert {node["event_id"] for node in causes["nodes"]} == {
        "ui-risk-001",
        "ui-risk-002",
    }
    assert impacts["direction"] == "impacts"
    assert {node["event_id"] for node in impacts["nodes"]} == {
        "ui-risk-002",
        "ui-risk-003",
        "ui-risk-004",
    }
    assert causes["paths"] and impacts["paths"]


@pytest.mark.parametrize("direction", ["causes", "impacts"])
def test_non_risk_event_path_query_returns_clear_4xx(
    seeded_path: Path, direction: str
):
    response = CLIENT.get(f"/v1/audit/events/ui-normal-002/{direction}")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "event_not_direct_risk_source"


def test_missing_event_and_trace_return_404(seeded_path: Path):
    event = CLIENT.get("/v1/audit/events/does-not-exist")
    trace = CLIENT.get("/v1/audit/traces/does-not-exist")
    path = CLIENT.get("/v1/audit/events/does-not-exist/causes")
    assert event.status_code == trace.status_code == path.status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {"max_depth": 0},
        {"max_depth": 65},
        {"max_paths": 0},
        {"max_paths": 101},
    ],
)
def test_invalid_path_limits_return_422(seeded_path: Path, params: dict):
    response = CLIENT.get("/v1/audit/events/ui-risk-002/causes", params=params)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"offset": 100_001}],
)
def test_invalid_pagination_returns_422(seeded_path: Path, params: dict):
    assert CLIENT.get("/v1/audit/traces", params=params).status_code == 422


def test_damaged_jsonl_returns_sanitized_error(audit_path: Path):
    audit_path.write_text('{"event_id":"secret-fragment"', encoding="utf-8")
    response = CLIENT.get("/v1/audit/traces")
    serialized = json.dumps(response.json())
    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "audit_jsonl_invalid",
        "message": "Audit data is unavailable because the JSONL source is invalid.",
        "line_number": 1,
    }
    assert "secret-fragment" not in serialized
    assert str(audit_path) not in serialized


def test_delete_from_damaged_jsonl_returns_sanitized_error(audit_path: Path):
    audit_path.write_text('{"event_id":"secret-delete-fragment"', encoding="utf-8")
    response = CLIENT.request(
        "DELETE",
        "/v1/audit/traces",
        json={"trace_ids": ["trace-ui-risk"]},
    )
    serialized = json.dumps(response.json())
    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "audit_jsonl_invalid",
        "message": "Audit data is unavailable because the JSONL source is invalid.",
        "line_number": 1,
    }
    assert "secret-delete-fragment" not in serialized
    assert str(audit_path) not in serialized


@pytest.mark.parametrize("integrity_case", ["missing_parent", "cycle"])
def test_graph_integrity_errors_are_not_silently_repaired(
    audit_path: Path, integrity_case: str
):
    events = deepcopy(_fixture_events()[:3])
    if integrity_case == "missing_parent":
        events[1]["metadata"]["parent_event_id"] = "absent-event"
    else:
        events[0]["metadata"]["parent_event_id"] = events[-1]["event_id"]
    store = AuditStore(audit_path)
    for event in events:
        store.append(event)
    response = CLIENT.get("/v1/audit/traces")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "audit_graph_integrity_error"


def test_all_query_endpoints_leave_jsonl_sha256_unchanged(seeded_path: Path):
    before = hashlib.sha256(seeded_path.read_bytes()).hexdigest()
    endpoints = [
        "/v1/audit/overview",
        "/v1/audit/traces",
        "/v1/audit/traces/trace-ui-risk",
        "/v1/audit/events/ui-risk-002",
        "/v1/audit/events/ui-risk-002/causes",
        "/v1/audit/events/ui-risk-002/impacts",
    ]
    assert all(CLIENT.get(endpoint).status_code == 200 for endpoint in endpoints)
    after = hashlib.sha256(seeded_path.read_bytes()).hexdigest()
    assert before == after
