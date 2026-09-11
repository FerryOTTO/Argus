"""Text-first node, trace, filter, cause, and impact queries."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Mapping

import networkx as nx

from .graph import (
    GraphIntegrityError,
    build_trace_graph,
    event_sort_key,
    graph_document,
)
from .reviews import AuditRiskReviewStore
from .storage import (
    AuditStore,
    get_risk_threshold,
    is_direct_risk_source,
    parse_timestamp,
)


MAX_DEPTH_CAP = 64
MAX_PATHS_CAP = 100


def _display_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split())
    if not compact:
        return None
    return compact if len(compact) <= 72 else f"{compact[:69]}..."


def _full_display_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split())
    return compact or None


def _trace_user_input(events: list[dict[str, Any]]) -> str | None:
    """Return only an explicitly recorded user input; never infer one from tools."""

    for event in events:
        content = event.get("content")
        if not isinstance(content, Mapping):
            continue
        arguments = content.get("arguments")
        sources = (content, arguments) if isinstance(arguments, Mapping) else (content,)
        for key in ("prompt", "message", "query"):
            for source in sources:
                text = _full_display_text(source.get(key))
                if text is not None:
                    return text

    input_stages = {"input", "user_input", "message_received"}
    for event in events:
        if event.get("stage") not in input_stages:
            continue
        content = event.get("content")
        if not isinstance(content, Mapping):
            continue
        for key in ("text", "content"):
            text = _full_display_text(content.get(key))
            if text is not None:
                return text
    return None


def _trace_display_name(events: list[dict[str, Any]]) -> str | None:
    """Return a compact real label, preferring explicitly recorded user input."""

    user_input = _trace_user_input(events)
    if user_input is not None:
        return _display_text(user_input)

    keys = ("original_tool_name", "tool_name")
    for event in events:
        content = event.get("content")
        if not isinstance(content, Mapping):
            continue
        arguments = content.get("arguments")
        sources = (content, arguments) if isinstance(arguments, Mapping) else (content,)
        for key in keys:
            for source in sources:
                text = _display_text(source.get(key))
                if text is not None:
                    return text
    return None


def _limits(max_depth: int, max_paths: int) -> None:
    if not 1 <= max_depth <= MAX_DEPTH_CAP:
        raise ValueError(f"max_depth must be in [1, {MAX_DEPTH_CAP}]")
    if not 1 <= max_paths <= MAX_PATHS_CAP:
        raise ValueError(f"max_paths must be in [1, {MAX_PATHS_CAP}]")


def _edge_document(
    source: str,
    target: str,
    key: str,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    return {"source": source, "target": target, "key": key, **dict(data)}


MODULE_CATEGORY_MAP = {
    "content": {
        "io_guard",
        "io_guard.input",
        "io_guard.output",
        "io_guard.context",
        "retrieval_guard",
        "media_input",
    },
    "content_guard": {
        "io_guard",
        "io_guard.input",
        "io_guard.output",
        "io_guard.context",
        "retrieval_guard",
        "media_input",
    },
    "access": {"access_control"},
    "access_control": {"access_control"},
    "tools": {"tool_guard"},
    "tool_guard": {"tool_guard"},
    "sandbox": {"sandbox", "sandbox_mcp"},
    "sandbox_mcp": {"sandbox", "sandbox_mcp"},
}


def event_matches_module(source_module: str, requested_module: str | None) -> bool:
    if not requested_module or requested_module in ("audit", "all", "*"):
        return True
    req = requested_module.lower().strip()
    if req in MODULE_CATEGORY_MAP:
        matches = MODULE_CATEGORY_MAP[req]
        return source_module in matches or any(
            source_module.startswith(prefix) for prefix in matches
        )
    return source_module == req or source_module.startswith(req)


class AuditQuery:
    def __init__(
        self,
        store: AuditStore | None = None,
        *,
        threshold: float | str | None = None,
        review_store: AuditRiskReviewStore | None = None,
    ) -> None:
        self.store = store or AuditStore()
        self.threshold = get_risk_threshold(threshold)
        self.review_store = review_store or AuditRiskReviewStore(
            audit_path=self.store.path
        )

    def _dismissed_event_ids(self, trace_id: str | None = None) -> set[str]:
        return self.review_store.dismissed_event_ids(trace_id)

    def _apply_risk_reviews(self, graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
        trace_id = graph.graph.get("trace_id")
        dismissed = self._dismissed_event_ids(
            str(trace_id) if trace_id is not None else None
        )
        for event_id, data in graph.nodes(data=True):
            original = data.get("direct_risk_source") is True
            reviewed = original and event_id in dismissed
            data["original_direct_risk_source"] = original
            data["risk_review_status"] = "dismissed" if reviewed else None
            data["direct_risk_source"] = original and not reviewed
        return graph

    def events(
        self,
        *,
        trace_id: str | None = None,
        session_id: str | None = None,
        source_module: str | None = None,
        stage: str | None = None,
        risk_score_min: float | None = None,
        direct_risk_sources_only: bool = False,
    ) -> list[dict[str, Any]]:
        if risk_score_min is not None and not 0.0 <= risk_score_min <= 1.0:
            raise ValueError("risk_score_min must be in [0, 1]")
        result = []
        dismissed = self._dismissed_event_ids()
        for event in self.store.load():
            if trace_id is not None and event["trace_id"] != trace_id:
                continue
            if session_id is not None and event["session_id"] != session_id:
                continue
            if source_module is not None and event["source_module"] != source_module:
                continue
            if stage is not None and event["stage"] != stage:
                continue
            if risk_score_min is not None and event["risk_score"] < risk_score_min:
                continue
            if direct_risk_sources_only:
                if not is_direct_risk_source(event, self.threshold):
                    continue
                if event["event_id"] in dismissed:
                    continue
            result.append(event)
        return sorted(result, key=event_sort_key)

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        matches = [event for event in self.store.load() if event["event_id"] == event_id]
        if len(matches) > 1:
            raise GraphIntegrityError(f"duplicate event_id: {event_id}")
        return matches[0] if matches else None

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        events = self.events(trace_id=trace_id)
        if not events:
            return None
        graph = build_trace_graph(events, self.threshold)
        return graph_document(self._apply_risk_reviews(graph))

    def list_traces(
        self,
        session_id: str | None = None,
        module: str | None = None,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in self.events(session_id=session_id):
            grouped[event["trace_id"]].append(event)
        traces = []
        for trace_id, events in sorted(grouped.items()):
            if module and not any(
                event_matches_module(ev["source_module"], module) for ev in events
            ):
                continue
            graph = self._apply_risk_reviews(build_trace_graph(events, self.threshold))
            user_input = _trace_user_input(events)
            active_risk_scores = [
                float(data["risk_score"])
                for _, data in graph.nodes(data=True)
                if data.get("direct_risk_source") is True
            ]
            confirmed_edges = sum(
                data.get("inference") != "temporal_sequence"
                for _, _, data in graph.edges(data=True)
            )
            temporal_edges = graph.number_of_edges() - confirmed_edges
            traces.append(
                {
                    "trace_id": trace_id,
                    "session_id": events[0]["session_id"],
                    "user_id": events[0]["user_id"],
                    "event_count": len(events),
                    "started_at": events[0]["timestamp"],
                    "ended_at": events[-1]["timestamp"],
                    "direct_risk_source_count": len(active_risk_scores),
                    "user_input": user_input,
                    "display_name": _trace_display_name(events),
                    "source_modules": sorted(
                        {event["source_module"] for event in events}
                    ),
                    "actions": sorted({event["action"] for event in events}),
                    "max_risk_score": max(active_risk_scores, default=0.0),
                    "blocked_event_count": sum(
                        event["action"] == "block" for event in events
                    ),
                    "human_review_event_count": sum(
                        event["action"] == "human_review" for event in events
                    ),
                    "confirmed_edge_count": confirmed_edges,
                    "temporal_edge_count": temporal_edges,
                    "last_stage": events[-1]["stage"],
                    "last_action": events[-1]["action"],
                }
            )
        traces.sort(
            key=lambda item: (
                parse_timestamp(item["ended_at"]),
                item["trace_id"],
            ),
            reverse=True,
        )
        return traces

    def overview(self, module: str | None = None) -> dict[str, Any]:
        """Aggregate the complete read-only store without loading every trace in the UI."""

        all_events = self.events()
        all_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in all_events:
            all_grouped[event["trace_id"]].append(event)

        if module and module not in ("audit", "all", "*"):
            matching_trace_ids = {
                trace_id
                for trace_id, trace_events in all_grouped.items()
                if any(event_matches_module(ev["source_module"], module) for ev in trace_events)
            }
            events = [
                ev
                for ev in all_events
                if event_matches_module(ev["source_module"], module)
            ]
        else:
            matching_trace_ids = set(all_grouped.keys())
            events = all_events

        confirmed_edge_count = 0
        temporal_edge_count = 0
        risk_trace_count = 0
        direct_risk_source_count = 0
        module_counts: Counter[str] = Counter()
        risk_buckets: Counter[str] = Counter()
        dismissed = self._dismissed_event_ids()

        for trace_id in matching_trace_ids:
            trace_events = all_grouped[trace_id]
            graph = self._apply_risk_reviews(
                build_trace_graph(trace_events, self.threshold)
            )
            trace_risk_count = sum(
                data.get("direct_risk_source") is True
                and (
                    not module
                    or module in ("audit", "all", "*")
                    or event_matches_module(data.get("source_module", ""), module)
                )
                for _, data in graph.nodes(data=True)
            )
            risk_trace_count += trace_risk_count > 0
            direct_risk_source_count += trace_risk_count
            for _, _, data in graph.edges(data=True):
                if data.get("inference") == "temporal_sequence":
                    temporal_edge_count += 1
                else:
                    confirmed_edge_count += 1

        for event in events:
            module_counts[event["source_module"]] += 1
            if (
                is_direct_risk_source(event, self.threshold)
                and event["event_id"] not in dismissed
            ):
                bucket = parse_timestamp(event["timestamp"]).astimezone(timezone.utc)
                risk_buckets[bucket.date().isoformat()] += 1

        edge_count = confirmed_edge_count + temporal_edge_count
        # A store containing only isolated single-event traces has no missing edge.
        integrity = confirmed_edge_count / edge_count if edge_count else 1.0
        return {
            "module": module or "all",
            "event_count": len(events),
            "trace_count": len(matching_trace_ids),
            "risk_trace_count": risk_trace_count,
            "direct_risk_source_count": direct_risk_source_count,
            "blocked_event_count": sum(
                event["action"] == "block" for event in events
            ),
            "human_review_event_count": sum(
                event["action"] == "human_review" for event in events
            ),
            "confirmed_edge_count": confirmed_edge_count,
            "temporal_edge_count": temporal_edge_count,
            "chain_integrity_rate": round(integrity, 6),
            "risk_trend": [
                {"bucket": bucket, "count": risk_buckets[bucket]}
                for bucket in sorted(risk_buckets)
            ],
            "module_distribution": [
                {"source_module": mod, "count": count}
                for mod, count in sorted(
                    module_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def direct_risk_sources(self, **filters: Any) -> list[dict[str, Any]]:
        return self.events(direct_risk_sources_only=True, **filters)

    def _graph_for_event(self, event_id: str) -> nx.MultiDiGraph:
        event = self.get_event(event_id)
        if event is None:
            raise KeyError(f"event_id not found: {event_id}")
        graph = self._apply_risk_reviews(
            build_trace_graph(
                self.events(trace_id=event["trace_id"]), self.threshold
            )
        )
        if not graph.nodes[event_id]["direct_risk_source"]:
            raise ValueError(f"event is not a direct risk source: {event_id}")
        return graph

    def causes(
        self, event_id: str, *, max_depth: int = 8, max_paths: int = 10
    ) -> dict[str, Any]:
        return self._traverse(
            self._graph_for_event(event_id),
            event_id,
            direction="causes",
            max_depth=max_depth,
            max_paths=max_paths,
        )

    def impacts(
        self, event_id: str, *, max_depth: int = 8, max_paths: int = 10
    ) -> dict[str, Any]:
        return self._traverse(
            self._graph_for_event(event_id),
            event_id,
            direction="impacts",
            max_depth=max_depth,
            max_paths=max_paths,
        )

    @staticmethod
    def _traverse(
        graph: nx.MultiDiGraph,
        start: str,
        *,
        direction: str,
        max_depth: int,
        max_paths: int,
    ) -> dict[str, Any]:
        _limits(max_depth, max_paths)
        reverse = direction == "causes"
        queue = deque([(start, [start], [])])
        visited = {start}
        paths: list[dict[str, Any]] = []
        edge_by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
        truncated = False

        while queue:
            current, node_path, edge_path = queue.popleft()
            depth = len(node_path) - 1
            if depth >= max_depth:
                if list(graph.predecessors(current) if reverse else graph.successors(current)):
                    truncated = True
                continue
            edge_view = (
                graph.in_edges(current, keys=True, data=True)
                if reverse
                else graph.out_edges(current, keys=True, data=True)
            )
            candidates = sorted(
                edge_view,
                key=lambda item: (
                    str(item[3].get("timestamp") or ""),
                    item[0],
                    item[1],
                    str(item[2]),
                ),
            )
            for source, target, key, data in candidates:
                neighbor = source if reverse else target
                if neighbor in visited:
                    continue
                if len(paths) >= max_paths:
                    truncated = True
                    break
                visited.add(neighbor)
                edge = _edge_document(source, target, str(key), data)
                edge_by_identity[(source, target, str(key))] = edge
                next_nodes = [*node_path, neighbor]
                next_edges = [*edge_path, edge]
                paths.append(
                    {
                        "nodes": next_nodes,
                        "edges": next_edges,
                        "length": len(next_edges),
                    }
                )
                queue.append((neighbor, next_nodes, next_edges))
            if truncated and len(paths) >= max_paths:
                break

        node_documents = [
            {"node_id": node_id, **dict(graph.nodes[node_id])}
            for node_id in visited
        ]
        node_documents.sort(key=lambda item: event_sort_key(item["raw_event"]))
        return {
            "event_id": start,
            "trace_id": graph.graph["trace_id"],
            "direction": direction,
            "nodes": node_documents,
            "edges": list(edge_by_identity.values()),
            "paths": paths,
            "truncated": truncated,
            "limits": {"max_depth": max_depth, "max_paths": max_paths},
        }
