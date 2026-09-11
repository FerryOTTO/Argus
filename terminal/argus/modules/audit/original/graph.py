"""Trace-isolated temporal provenance graphs derived from AuditEvent JSONL."""

from __future__ import annotations

from collections import defaultdict
from datetime import timezone
from typing import Any, Iterable, Mapping

import networkx as nx

from .storage import (
    get_risk_threshold,
    normalize_audit_event,
    parse_timestamp,
)


class GraphIntegrityError(ValueError):
    """Raised instead of silently repairing ambiguous or cyclic evidence."""


def _metadata(event: Mapping[str, Any]) -> Mapping[str, Any]:
    value = event.get("metadata")
    return value if isinstance(value, Mapping) else {}


def _sequence(event: Mapping[str, Any]) -> int | None:
    value = _metadata(event).get("sequence")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise GraphIntegrityError(
            f"event {event['event_id']} metadata.sequence must be an integer"
        )
    return value


def event_sort_key(event: Mapping[str, Any]) -> tuple[Any, ...]:
    sequence = _sequence(event)
    timestamp = parse_timestamp(str(event["timestamp"])).astimezone(timezone.utc)
    return (
        sequence is None,
        sequence if sequence is not None else 0,
        timestamp,
        str(event["event_id"]),
    )


def _validated_unique(
    events: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in events:
        event = normalize_audit_event(payload)
        event_id = event["event_id"]
        if event_id in seen:
            raise GraphIntegrityError(f"duplicate event_id: {event_id}")
        seen.add(event_id)
        validated.append(event)
    return validated


def build_trace_graph(
    events: Iterable[Mapping[str, Any]],
    threshold: float | str | None = None,
) -> nx.MultiDiGraph:
    """Build one DAG; input spanning traces is an integrity error."""

    validated = _validated_unique(events)
    graph = nx.MultiDiGraph(schema_version="1.0")
    if not validated:
        graph.graph.update(trace_id=None, risk_threshold=get_risk_threshold(threshold))
        return graph

    trace_ids = {event["trace_id"] for event in validated}
    if len(trace_ids) != 1:
        raise GraphIntegrityError(
            "a task graph must contain exactly one trace_id"
        )
    trace_id = next(iter(trace_ids))
    configured_threshold = get_risk_threshold(threshold)
    graph.graph.update(
        trace_id=trace_id,
        risk_threshold=configured_threshold,
        source="AuditEvent JSONL",
    )

    ordered = sorted(validated, key=event_sort_key)
    by_id = {event["event_id"]: event for event in ordered}
    for event in ordered:
        event_id = event["event_id"]
        graph.add_node(
            event_id,
            node_id=event_id,
            node_type="AuditEvent",
            direct_risk_source=(
                float(event["risk_score"]) >= configured_threshold
            ),
            sequence=_sequence(event),
            raw_event=event,
            **event,
        )

    # Establish all explicit provenance edges before adding temporal fallbacks.
    # The stable event sort key is only a tie-breaker; it must never override an
    # explicit parent relationship when timestamps and sequences are ambiguous.
    for event in ordered:
        event_id = event["event_id"]
        parent_id = _metadata(event).get("parent_event_id")
        if parent_id is not None:
            if not isinstance(parent_id, str) or not parent_id:
                raise GraphIntegrityError(
                    f"event {event_id} parent_event_id must be a non-empty string"
                )
            if parent_id not in by_id:
                raise GraphIntegrityError(
                    f"event {event_id} references missing parent_event_id: {parent_id}"
                )
            graph.add_edge(
                parent_id,
                event_id,
                key=f"{event_id}:parent",
                relation="PARENT_OF",
                event_id=event_id,
                trace_id=trace_id,
                timestamp=event["timestamp"],
                sequence=_sequence(event),
            )

    if not nx.is_directed_acyclic_graph(graph):
        raise GraphIntegrityError(f"trace {trace_id} contains a cycle")

    # Use a stable topological order for inferred temporal edges. This keeps
    # explicit parents before their children even if a child event_id sorts
    # first and both events lack sequence information.
    topological_ids = list(
        nx.lexicographical_topological_sort(
            graph,
            key=lambda node_id: event_sort_key(by_id[node_id]),
        )
    )
    for index, event_id in enumerate(topological_ids):
        event = by_id[event_id]
        if _metadata(event).get("parent_event_id") is None and index > 0:
            previous_id = topological_ids[index - 1]
            graph.add_edge(
                previous_id,
                event_id,
                key=f"{event_id}:temporal",
                relation="PRECEDES",
                event_id=event_id,
                trace_id=trace_id,
                timestamp=event["timestamp"],
                sequence=_sequence(event),
                inference="temporal_sequence",
            )

    if not nx.is_directed_acyclic_graph(graph):
        raise GraphIntegrityError(f"trace {trace_id} contains a cycle")
    return graph


def build_trace_graphs(
    events: Iterable[Mapping[str, Any]],
    threshold: float | str | None = None,
) -> dict[str, nx.MultiDiGraph]:
    """Build one independent graph per trace and reject global duplicate IDs."""

    validated = _validated_unique(events)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in validated:
        grouped[event["trace_id"]].append(event)
    return {
        trace_id: build_trace_graph(group, threshold)
        for trace_id, group in sorted(grouped.items())
    }


def _node_document(node_id: str, data: Mapping[str, Any]) -> dict[str, Any]:
    return {"node_id": node_id, **dict(data)}


def _edge_document(
    source: str,
    target: str,
    key: str,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    return {"source": source, "target": target, "key": key, **dict(data)}


def graph_document(graph: nx.MultiDiGraph) -> dict[str, Any]:
    nodes = [_node_document(node, data) for node, data in graph.nodes(data=True)]
    nodes.sort(key=lambda item: event_sort_key(item["raw_event"]))
    edges = [
        _edge_document(source, target, str(key), data)
        for source, target, key, data in graph.edges(keys=True, data=True)
    ]
    edges.sort(
        key=lambda item: (
            str(item.get("timestamp") or ""),
            item["source"],
            item["target"],
            item["key"],
        )
    )
    return {
        "trace_id": graph.graph.get("trace_id"),
        "risk_threshold": graph.graph.get("risk_threshold"),
        "nodes": nodes,
        "edges": edges,
        "direct_risk_source_ids": sorted(
            node
            for node, data in graph.nodes(data=True)
            if data.get("direct_risk_source") is True
        ),
    }
