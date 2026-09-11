from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import networkx as nx
import pytest

from clawguard.modules.audit.original import (
    AuditQuery,
    AuditStore,
    GraphIntegrityError,
    build_trace_graph,
    build_trace_graphs,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "audit" / "events.synthetic.jsonl"


@pytest.fixture
def events():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def query(tmp_path, events):
    store = AuditStore(tmp_path / "query.jsonl")
    for event in events:
        store.append(event)
    return AuditQuery(store, threshold=0.5)


def test_same_trace_builds_one_dag_with_explicit_parent(events):
    graph = build_trace_graph(events[:3], threshold=0.5)
    assert graph.graph["trace_id"] == "trace-syn-a"
    assert set(graph.nodes) == {
        "audit-syn-001",
        "audit-syn-002",
        "audit-syn-003",
    }
    assert nx.is_directed_acyclic_graph(graph)
    edge = graph.get_edge_data("audit-syn-001", "audit-syn-002")
    assert edge["audit-syn-002:parent"]["relation"] == "PARENT_OF"
    assert "inference" not in edge["audit-syn-002:parent"]


def test_different_traces_are_never_mixed(events):
    graphs = build_trace_graphs(events)
    assert set(graphs) == {"trace-syn-a", "trace-syn-b"}
    assert all(
        {data["trace_id"] for _, data in graph.nodes(data=True)} == {trace_id}
        for trace_id, graph in graphs.items()
    )
    with pytest.raises(GraphIntegrityError, match="exactly one trace_id"):
        build_trace_graph(events)


def test_missing_parent_uses_temporal_edge_with_inference(events):
    first, second = deepcopy(events[0]), deepcopy(events[1])
    second["metadata"].pop("parent_event_id")
    second["timestamp"] = first["timestamp"]
    graph = build_trace_graph([second, first])

    edge = graph.get_edge_data("audit-syn-001", "audit-syn-002")
    assert edge["audit-syn-002:temporal"]["relation"] == "PRECEDES"
    assert edge["audit-syn-002:temporal"]["inference"] == "temporal_sequence"


def test_same_timestamp_without_sequence_uses_event_id_stable_order(events):
    first, second = deepcopy(events[0]), deepcopy(events[1])
    first["event_id"], second["event_id"] = "a-event", "b-event"
    first["metadata"] = {}
    second["metadata"] = {}
    second["timestamp"] = first["timestamp"]
    graph = build_trace_graph([second, first])
    assert graph.has_edge("a-event", "b-event")


def test_temporal_fallback_never_reverses_explicit_parent(events):
    parent, child = deepcopy(events[0]), deepcopy(events[1])
    parent["event_id"] = "z-parent"
    parent["metadata"] = {}
    child["event_id"] = "a-child"
    child["metadata"] = {"parent_event_id": "z-parent"}
    child["timestamp"] = parent["timestamp"]

    graph = build_trace_graph([child, parent])

    assert nx.is_directed_acyclic_graph(graph)
    assert graph.has_edge("z-parent", "a-child", key="a-child:parent")
    assert not graph.has_edge("a-child", "z-parent")


def test_direct_risk_source_uses_configured_threshold_without_levels(events):
    graph = build_trace_graph(events[:3], threshold=0.9)
    assert graph.nodes["audit-syn-001"]["direct_risk_source"] is False
    assert graph.nodes["audit-syn-002"]["direct_risk_source"] is True
    assert graph.nodes["audit-syn-002"]["risk_score"] == 0.92
    assert graph.nodes["audit-syn-002"]["reason"] == "synthetic upstream policy decision"
    assert "risk_level" not in graph.nodes["audit-syn-002"]


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("duplicate", "duplicate event_id"),
        ("missing_parent", "missing parent_event_id"),
        ("cycle", "contains a cycle"),
    ],
)
def test_integrity_errors_are_not_silently_repaired(events, mutation, match):
    trace = deepcopy(events[:3])
    if mutation == "duplicate":
        trace.append(deepcopy(trace[0]))
    elif mutation == "missing_parent":
        trace[1]["metadata"]["parent_event_id"] = "does-not-exist"
    else:
        trace[0]["metadata"]["parent_event_id"] = "audit-syn-003"
    with pytest.raises(GraphIntegrityError, match=match):
        build_trace_graph(trace)


def test_event_trace_session_and_filter_queries(query):
    assert query.get_event("audit-syn-002")["source_module"] == "tool_guard"
    assert query.get_event("missing") is None
    trace = query.get_trace("trace-syn-a")
    assert trace["trace_id"] == "trace-syn-a"
    assert len(trace["nodes"]) == 3
    assert trace["direct_risk_source_ids"] == ["audit-syn-002"]
    assert {item["trace_id"] for item in query.list_traces("session-syn")} == {
        "trace-syn-a",
        "trace-syn-b",
    }
    assert [event["event_id"] for event in query.events(source_module="tool_guard")] == [
        "audit-syn-002"
    ]
    assert [event["event_id"] for event in query.events(stage="output")] == [
        "audit-syn-003"
    ]
    assert [event["event_id"] for event in query.events(risk_score_min=0.9)] == [
        "audit-syn-002"
    ]
    assert [event["event_id"] for event in query.direct_risk_sources()] == [
        "audit-syn-002"
    ]


def test_cause_and_impact_queries_return_evidence_edges(query):
    causes = query.causes("audit-syn-002", max_depth=4, max_paths=4)
    impacts = query.impacts("audit-syn-002", max_depth=4, max_paths=4)

    assert {node["node_id"] for node in causes["nodes"]} == {
        "audit-syn-001",
        "audit-syn-002",
    }
    assert {node["node_id"] for node in impacts["nodes"]} == {
        "audit-syn-002",
        "audit-syn-003",
    }
    for result in (causes, impacts):
        assert result["paths"]
        assert all(
            {"relation", "event_id", "timestamp"} <= set(edge)
            for edge in result["edges"]
        )


def test_temporal_inference_is_preserved_in_trace_results(tmp_path, events):
    trace = deepcopy(events[:3])
    trace[1]["metadata"].pop("parent_event_id")
    store = AuditStore(tmp_path / "temporal.jsonl")
    for event in trace:
        store.append(event)
    result = AuditQuery(store).causes("audit-syn-002")
    assert any(
        edge.get("inference") == "temporal_sequence" for edge in result["edges"]
    )


def test_bounded_tracing_limits_are_enforced(query):
    result = query.causes("audit-syn-002", max_depth=1, max_paths=1)
    assert len(result["paths"]) <= 1
    with pytest.raises(ValueError, match="max_depth"):
        query.causes("audit-syn-002", max_depth=65)
    with pytest.raises(ValueError, match="max_paths"):
        query.causes("audit-syn-002", max_paths=101)


def test_runtime_audit_artifacts_are_git_ignored():
    result = subprocess.run(
        ["git", "check-ignore", "runtime/audit/audit-events.jsonl"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "runtime/audit/audit-events.jsonl"
