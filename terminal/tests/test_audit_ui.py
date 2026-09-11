from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clawguard.api.audit_routes import router as audit_router
from clawguard.api.main import app


CLIENT = TestClient(app)


@pytest.fixture
def empty_audit_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "empty.jsonl"
    monkeypatch.setenv("CLAWGUARD_AUDIT_PATH", str(path))
    monkeypatch.delenv("CLAWGUARD_AUDIT_RISK_REVIEW_PATH", raising=False)
    return path


def _html() -> str:
    response = CLIENT.get("/audit")
    assert response.status_code == 200
    return response.text


def test_audit_page_is_dependency_free_v2(empty_audit_path: Path):
    html = _html()
    assert not re.search(r"(?:src|href)=[\"']https?://", html, re.I)
    assert "cdn" not in html.lower()
    assert "审计概览" in html
    assert "工具调用链" in html
    assert 'id="graphViewBtn"' not in html
    assert 'id="graphShell"' not in html
    assert 'data-view="graph"' not in html
    assert "drawer" in html.lower()
    assert "<svg" in html


def test_kpi_filter_label_is_hidden_and_sidebar_ambient_layers_are_richer(
    empty_audit_path: Path,
):
    html = _html()
    assert "筛选中" not in html
    assert html.count('class="ambient-stream stream-') == 8
    assert html.count('class="ambient-particles particles-') == 6
    assert ".ambient-stream::before" in html
    assert ".ambient-stream::after" in html
    assert ".nav-ambient" in html and "pointer-events:none" in html
    assert "@media (prefers-reduced-motion:reduce)" in html


def test_formal_page_contains_no_mock_or_prototype_data(empty_audit_path: Path):
    html = _html()
    lowered = html.lower()
    assert "synthetic" not in lowered
    assert "prototype" not in lowered
    assert "const traces =" not in html
    assert "tr-9a71f0c2" not in html
    assert "evt-001" not in html
    assert "AUDIT API" in html
    assert "LIVE DATA" in html


def test_page_uses_real_api_flow_and_explicit_adapters(empty_audit_path: Path):
    html = _html()
    for function_name in (
        "adaptTraceSummary",
        "adaptTraceDetail",
        "adaptEventNode",
        "adaptEdge",
    ):
        assert f"function {function_name}" in html
    assert 'requestJson("/v1/audit/overview")' in html
    assert 'requestJson("/v1/audit/traces?limit=200&offset=0")' in html
    assert "/v1/audit/traces/${encodeURIComponent(traceId)}" in html
    assert "/v1/audit/events/${encodeURIComponent(eventId)}" in html
    assert "/${direction}?${PATH_QUERY}" in html
    assert "runtime/audit" not in html


def test_risk_impact_and_edge_semantics_come_from_backend(empty_audit_path: Path):
    html = _html()
    assert "source.direct_risk_source === true" in html
    assert 'source.relation === "PARENT_OF" && !source.inference' in html
    assert 'source.inference === "temporal_sequence"' in html
    assert "markImpacts(nodes, edges)" in html
    assert "if (usedTemporal) target.possibly_impacted = true" in html
    assert "else target.impacted = true" in html
    assert "可能受影响" in html
    assert "时序推断，非确定因果" in html
    assert "node.risk_score >=" not in html


def test_drawer_uses_event_api_and_independent_folds(empty_audit_path: Path):
    html = _html()
    assert "state.expandedDetailKeys.has(key)" in html
    assert "state.expandedDetailKeys.add(details.dataset.detailKey)" in html
    assert "state.expandedDetailKeys.delete(details.dataset.detailKey)" in html
    assert "content（展开查看）" in html
    assert "metadata（展开查看）" in html
    assert "完整 AuditEvent JSON（展开查看）" in html
    assert "event.parents" in html
    assert "event.children" in html
    assert "event.incoming_edges" in html
    assert "event.outgoing_edges" in html
    assert "该事件不是后端标记的直接风险源" in html


def test_api_text_is_escaped_before_html_rendering(empty_audit_path: Path):
    html = _html()
    assert "const escapeHtml =" in html
    assert "/[&<>\"']/g" in html
    assert "escapeHtml(JSON.stringify(value,null,2))" in html
    assert "escapeHtml(event.reason" in html
    assert "escapeHtml(timelineReason(node.reason))" in html


def test_refresh_preserves_state_and_trace_replay_is_removed(
    empty_audit_path: Path,
):
    html = _html()
    assert "selectedTraceId" in html
    assert "selectedEventId" in html
    assert "expandedDetailKeys:new Set()" in html
    assert 'viewMode:"timeline"' in html
    assert 'pathMode:"all"' in html
    assert "refreshGeneration" in html
    assert "已保留上一次成功数据" in html
    assert "window.setInterval(()=>refreshAll(),REFRESH_MS)" in html
    assert "REPLAY_STEP_MS" not in html
    assert "function startReplay" not in html
    assert "function replayClass" not in html
    assert "state.replay" not in html
    assert "loadTrace(state.selectedTraceId,{refreshEvent:!initial})" in html


def test_global_kpi_is_separate_from_workspace_filters(empty_audit_path: Path):
    html = _html()
    assert "function renderStats()" in html
    assert "const overview = state.overview" in html
    assert "function matchingTraces()" in html
    render_stats = html.split("function renderStats()", maxsplit=1)[1].split(
        "function renderTraceList", maxsplit=1
    )[0]
    assert "matchingTraces" not in render_stats
    assert "module_distribution" in html
    assert "risk_trend" in html


def test_overview_is_four_kpis_followed_directly_by_workspace(
    empty_audit_path: Path,
):
    html = _html()
    stats = html.split('<section class="stats"', maxsplit=1)[1].split(
        "</section>", maxsplit=1
    )[0]
    assert stats.count('<button class="stat"') == 4
    assert "事件总数" in stats
    assert "风险任务数" in stats
    assert "已拦截事件" in stats
    assert "待处理事件" in stats
    assert "链路完整率" not in html
    assert "真实风险事件趋势" not in html
    assert "安全模块事件分布" not in html
    assert "trendCanvas" not in html
    assert "moduleBars" not in html
    assert "function drawCharts" not in html
    assert "workspace-shell" not in html
    assert "workspace-header" not in html
    assert "审计工作台" not in html
    assert '<section class="workspace" aria-label="审计分析工作区">' in html
    assert "grid-template-columns:repeat(4,minmax(210px,1fr))" in html


def test_trace_cards_omit_fingerprint_and_event_titles_omit_tool_suffix(
    empty_audit_path: Path,
):
    html = _html()
    assert "function traceFingerprint" not in html
    assert "${traceFingerprint(trace)}" not in html
    assert "function eventToolName(event)" in html
    tool_name = html.split("function eventToolName(event)", maxsplit=1)[1].split(
        "function eventTitle", maxsplit=1
    )[0]
    assert tool_name.index("content.original_tool_name") < tool_name.index(
        "content.tool_name"
    )
    assert tool_name.index("content.tool_name,") < tool_name.index(
        "content.tool,"
    )
    assert tool_name.index("content.tool,") < tool_name.index(
        "args.original_tool_name"
    )
    assert tool_name.index("args.original_tool_name") < tool_name.index(
        "args.tool_name"
    )
    assert tool_name.index("args.tool_name,") < tool_name.index("args.tool,")
    assert tool_name.index("args.tool,") < tool_name.index("args.name,")
    assert tool_name.index("args.name,") < tool_name.index(
        "metadata.original_tool_name"
    )
    assert tool_name.index("metadata.original_tool_name") < tool_name.index(
        "metadata.tool_name"
    )
    assert "function eventTitle(event)" in html
    event_title = html.split("function eventTitle(event)", maxsplit=1)[1].split(
        "function displayOperation", maxsplit=1
    )[0]
    assert "return stageLabel(event.stage)" in event_title
    assert "eventToolName" not in event_title
    assert "timelineGroupToolName(group)" in html
    assert "步骤 ${stepNumber} · ${escapeHtml(title)}" in html
    assert "compact(eventTitle(node), 30)" in html
    assert '<div class="big">${escapeHtml(eventTitle(event))}</div>' in html


def test_timeline_groups_real_tool_call_ids_after_stable_ordering(
    empty_audit_path: Path,
):
    html = _html()
    call_id = html.split("function timelineToolCallId(node)", maxsplit=1)[1].split(
        "function isTimelineInput", maxsplit=1
    )[0]
    assert call_id.index("asObject(node.metadata).tool_call_id") < call_id.index(
        "asObject(node.content).tool_call_id"
    )
    assert "function groupTimelineNodes(nodes)" in html
    assert "const groups = groupTimelineNodes(nodes)" in html
    assert "const toolGroups = new Map()" in html
    assert "const toolCallId = timelineToolCallId(node)" in html
    assert "if (!toolGroups.has(toolCallId))" in html
    assert "toolGroups.get(toolCallId).items.push(item)" in html
    assert 'key:`tool:${toolCallId}`' in html
    assert 'key:`fallback:${node.event_id}`' in html
    assert 'key:`tool:${node.event_id}`' not in html
    assert "timelineGroupRank(left) - timelineGroupRank(right) || left.order - right.order" in html


def test_input_output_and_unlinked_events_are_independent_timeline_stages(
    empty_audit_path: Path,
):
    html = _html()
    assert 'node.stage === "input" || node.source_module === "io_guard.input"' in html
    assert 'node.stage === "output" || node.source_module === "io_guard.output"' in html
    assert 'kind:"input", key:`input:${node.event_id}`' in html
    assert 'kind:"output", key:`output:${node.event_id}`' in html
    assert 'kind:"fallback", key:`fallback:${node.event_id}`' in html
    assert "缺少工具调用关联信息（可能来自旧版上报）" in html
    assert "旧版事件：缺少工具调用关联信息" not in html
    assert "时序推断，不代表确定关联" in html
    assert "function timelineGroupHasTemporalRelation(group)" in html
    assert "任务输入" in html
    assert "最终输出" in html
    assert "function timelineGroupRank(group)" in html
    assert 'if (group.kind === "input") return 0' in html
    assert 'if (group.kind === "output") return 2' in html
    assert "timelineGroupRank(left) - timelineGroupRank(right) || left.order - right.order" in html


def test_timeline_tool_name_and_operation_summary_priorities(
    empty_audit_path: Path,
):
    html = _html()
    event_tool_name = html.split("function eventToolName(event)", maxsplit=1)[1].split(
        "function eventTitle", maxsplit=1
    )[0]
    candidates = [
        "content.original_tool_name,",
        "content.tool_name,",
        "content.tool,",
        "args.original_tool_name,",
        "args.tool_name,",
        "args.tool,",
        "args.name,",
        "metadata.original_tool_name,",
        "metadata.tool_name,",
    ]
    assert all(candidate in event_tool_name for candidate in candidates)
    assert [event_tool_name.index(candidate) for candidate in candidates] == sorted(
        event_tool_name.index(candidate) for candidate in candidates
    )
    assert 'typeof value === "string" && value.trim()' in event_tool_name
    operation = html.split("function timelineOperationSummary(group)", maxsplit=1)[
        1
    ].split("function timelineGroupAction", maxsplit=1)[0]
    for field in (
        '"query"',
        '"url"',
        '"endpoint"',
        '"path"',
        '"file_path"',
        '"command"',
        '"cmd"',
        '"message"',
        '"text"',
    ):
        assert field in operation
    assert operation.index('"query"') < operation.index('"url"')
    assert operation.index('"url"') < operation.index('"path"')


def test_timeline_group_action_risk_and_impact_aggregation(
    empty_audit_path: Path,
):
    html = _html()
    action = html.split("function timelineGroupAction(group)", maxsplit=1)[1].split(
        "function timelineGroupRisk", maxsplit=1
    )[0]
    assert '["block","human_review","rewrite","allow"]' in action
    assert "Math.max(0,...group.items.map" in html
    assert "node.direct_risk_source" in html
    assert "node.impacted" in html
    assert "node.possibly_impacted" in html
    assert "直接风险源" in html
    assert "已受影响" in html
    assert "可能受影响" in html


def test_timeline_steps_keep_relation_selection_and_api_escaping_without_replay(
    empty_audit_path: Path,
):
    html = _html()
    step = html.split("function renderTimelineStep(item,stepNumber)", maxsplit=1)[
        1
    ].split("function renderTimelineGroup", maxsplit=1)[0]
    assert "replayClass" not in step
    assert "data-event-row" in step
    assert "data-event=" in step
    assert "node.event_id === state.selectedEventId" in step
    assert "incomingRelation(node)" in step
    assert "时序推断，不代表确定因果" in html
    assert "escapeHtml(node.event_id)" in step
    assert "escapeHtml(node.timestamp)" in step
    assert "escapeHtml(moduleLabel(node.source_module))" in step
    assert "escapeHtml(timelineReason(node.reason))" in step
    assert "selectEvent(button.dataset.event)" in html
    assert "expandedDetailKeys:new Set()" in html
    assert "state.expandedDetailKeys.has(key)" in html


def test_timeline_steps_are_bounded_semantic_cards_with_larger_text(
    empty_audit_path: Path,
):
    html = _html()
    step = html.split("function renderTimelineStep(item,stepNumber)", maxsplit=1)[
        1
    ].split("function renderTimelineGroup", maxsplit=1)[0]
    assert "const title = timelineStepLabel(node)" in step
    assert "eventToolName(node)" not in step
    assert "判定结果" not in step
    assert "风险分" not in step
    assert "actionShort[node.action]" in step
    assert "<b>Risk</b>" in step
    assert '<span class="seq">' not in step
    assert ".timeline-group-steps { display:grid; gap:11px" in html
    assert ".timeline-step.event::before { content:none!important" in html
    assert "border-left:4px solid var(--cg-primary)" in html
    assert ".timeline-step-heading strong { min-width:0; font-size:15px" in html
    assert ".timeline-step-card.event-card.direct" in html
    assert ".timeline-step-card.event-card.impacted" in html
    assert ".timeline-step-card.event-card.direct.selected" in html
    assert "box-shadow:0 0 0 2px var(--cg-danger)" in html
    assert ".timeline-step-card.event-card.possibly-impacted.selected:not(.direct)" in html
    assert "box-shadow:0 0 0 2px var(--cg-warning)" in html


def test_direct_risk_step_supports_persistent_right_click_review(
    empty_audit_path: Path,
):
    html = _html()
    assert 'id="riskReviewMask"' in html
    assert 'id="confirmRiskReview"' in html
    assert 'button.addEventListener("contextmenu"' in html
    assert 'button.dataset.directRisk !== "true"' in html
    assert "openRiskReview(node)" in html
    assert "/risk-review`" in html
    assert 'method:"PUT"' in html
    assert 'body:JSON.stringify({dismissed:true})' in html
    assert "await refreshAll()" in html


def test_dismissed_risk_is_blue_and_recomputes_impacts_from_active_sources_only(
    empty_audit_path: Path,
):
    html = _html()
    assert 'event.risk_review_status = source.risk_review_status === "dismissed"' in html
    assert 'const dismissed = node.risk_review_status === "dismissed"' in html
    assert 'node.action === "block" && !dismissed ? "blocked-event"' in html
    assert ".timeline-step-card.event-card.risk-dismissed" in html
    assert "border-left:4px solid var(--cg-primary)!important" in html
    assert "已人工标记无风险" in html
    impacts = html.split("function markImpacts(nodes, edges)", maxsplit=1)[1].split(
        "function adaptTraceDetail", maxsplit=1
    )[0]
    assert "nodes.filter(node => node.direct_risk_source)" in impacts
    assert "target && !target.direct_risk_source" in impacts


def test_graph_wraps_long_chains_inside_the_viewport(empty_audit_path: Path):
    html = _html()
    graph_model = html.split("function graphModel(availableWidth,compactLayout=false)", maxsplit=1)[
        1
    ].split("function graphEdgePath", maxsplit=1)[0]
    render_graph = html.split("function renderEvidenceGraph()", maxsplit=1)[1].split(
        "function renderGraph()", maxsplit=1
    )[0]
    graph_dispatch = html.split("function renderGraph()", maxsplit=1)[1].split(
        "function setViewMode", maxsplit=1
    )[0]
    assert "const columns=Math.max(1" in graph_model
    assert "const rowCount=Math.max(1" in graph_model
    assert "row%2===0 ? index : rowNodes.length-1-index" in graph_model
    assert "x:startX+visualColumn*(nodeW+gapX)" in graph_model
    assert "function graphEdgePath(from,to)" in html
    assert "const sameRow=from.row===to.row" in html
    assert "const downward=to.y>from.y" in html
    assert "const viewportWidth=Math.max(620" in render_graph
    assert 'svg.setAttribute("width", "100%")' in render_graph
    assert 'svg.style.width = "100%"' in render_graph
    assert "graphEdgePath(from,to)" in render_graph
    assert 'state.graph.mode === "evidence"' in graph_dispatch
    assert "renderEvidenceGraph()" in graph_dispatch
    assert "renderTaskFlowGraph()" in graph_dispatch
    assert ".graph-viewport-wrap { flex:1 1 auto; overflow-x:auto; }" in html


def test_graph_ui_is_temporarily_removed(empty_audit_path: Path):
    html = _html()
    assert 'id="graphViewBtn"' not in html
    assert 'id="graphShell"' not in html
    assert 'id="traceGraph"' not in html
    assert 'data-view="graph"' not in html
    assert "initializeGraphModeControls();" not in html
    assert 'state.graph.mode=button.dataset.graphMode' not in html


def test_task_flow_projection_groups_real_events_without_inventing_resources(
    empty_audit_path: Path,
):
    html = _html()
    projection = html.split("function buildTaskFlowProjection(trace)", maxsplit=1)[1].split(
        "function taskFlowExpandedSet", maxsplit=1
    )[0]
    assert "const nodes = orderedNodes(trace)" in projection
    assert "const eventToGroup = new Map()" in projection
    assert 'key:"flow:input"' in projection
    assert 'key:"flow:output"' in projection
    assert "`flow:tool:${toolCallId}`" in projection
    assert "`flow:fallback:${node.event_id}`" in projection
    assert "eventToGroup.set(item.node.event_id,group.key)" in projection
    assert "if (!source || !target || source === target) return" in projection
    assert "resource" not in projection.lower()


def test_task_flow_uses_required_tool_id_name_and_operation_priorities(
    empty_audit_path: Path,
):
    html = _html()
    tool_id = html.split("function timelineToolCallId(node)", maxsplit=1)[1].split(
        "function isTimelineInput", maxsplit=1
    )[0]
    assert tool_id.index("metadataValue") < tool_id.index("contentValue")
    operation = html.split("function timelineOperationSummary(group)", maxsplit=1)[
        1
    ].split("function timelineGroupAction", maxsplit=1)[0]
    assert "for (const source of [args,content])" in operation
    for key in ("query", "url", "endpoint", "path", "file_path", "command", "cmd", "message", "text"):
        assert f'"{key}"' in operation


def test_task_flow_aggregates_action_risk_flags_and_real_edges(
    empty_audit_path: Path,
):
    html = _html()
    projection = html.split("function buildTaskFlowProjection(trace)", maxsplit=1)[1].split(
        "function taskFlowExpandedSet", maxsplit=1
    )[0]
    assert "action:timelineGroupAction(group)" in projection
    assert "risk:timelineGroupRisk(group)" in projection
    assert "directRiskSource:flags.direct" in projection
    assert "impacted:flags.impacted" in projection
    assert "possiblyImpacted:flags.possible" in projection
    assert "asArray(trace?.edges).forEach" in projection
    assert "projected.edgeKeys.push" in projection
    assert "projected.confirmed ||= Boolean(edge.confirmed)" in projection
    assert 'edge.inference === "temporal_sequence"' in projection
    assert "temporal:!edge.confirmed && edge.hasTemporal" in projection
    assert "时序推断，非确定因果" in projection


def test_task_flow_layout_is_left_to_right_layered_and_supports_branches(
    empty_audit_path: Path,
):
    html = _html()
    layout = html.split("function taskFlowLayout(projection)", maxsplit=1)[1].split(
        "function taskFlowEdgePath", maxsplit=1
    )[0]
    assert "const depth=new Map" in layout
    assert "if (!layers.has(layer)) layers.set(layer,[])" in layout
    assert "layers.get(layer).push(group)" in layout
    assert "x:padX+layer*(width+gapX)" in layout
    assert "y,width,height:heights[index],layer" in layout
    assert "row%2" not in layout
    assert "snake" not in layout.lower()
    assert "taskFlowEdgePath(from,to)" in html


def test_task_flow_steps_keep_real_event_selection_and_path_projection(
    empty_audit_path: Path,
):
    html = _html()
    render = html.split("function renderTaskFlowGraph()", maxsplit=1)[1].split(
        "function timelineReason", maxsplit=1
    )[0]
    assert "const highlighted=pathSets()" in render
    assert "edge.edgeKeys.some(key => highlighted.edges.has(key))" in render
    assert "highlighted.nodes.has(node.event_id)" in html
    assert 'data-task-step="${escapeHtml(node.event_id)}"' in html
    assert "selectEvent(button.dataset.taskStep)" in render
    assert "escapeHtml(node.reason" in html
    assert "escapeHtml(group.operation.value)" in html
    assert "escapeHtml(group.toolCallId)" in html
    path_sets = html.split("function pathSets()", maxsplit=1)[1].split(
        "function renderEvidenceGraph", maxsplit=1
    )[0]
    assert "state.pathResult.paths" in path_sets
    assert "paths.flatMap(path => asArray(path.nodes))" in path_sets
    assert "paths.flatMap(path => asArray(path.edges))" in path_sets
    assert 'typeof node === "string" ? node' in path_sets
    assert "state.graph.pathMode=mode" in html


def test_task_flow_risk_semantics_override_impacted_styling(
    empty_audit_path: Path,
):
    html = _html()
    assert ".task-flow-card.is-risk-source,.task-flow-card.is-blocked" in html
    assert ".task-flow-card.is-impacted:not(.is-risk-source):not(.is-blocked)" in html
    assert ".task-flow-step.impacted:not(.risk-source):not(.blocked)" in html


def test_dormant_task_flow_expansion_state_is_preserved_for_future_restore(
    empty_audit_path: Path,
):
    html = _html()
    assert "expandedByTrace:new Map()" in html
    assert "function taskFlowExpandedSet" in html
    assert "state.graph.expandedByTrace.has(key)" in html
    assert "state.graph.expandedByTrace.set(key,new Set())" in html
    assert 'const isExpanded=expanded.has(group.key)' in html
    assert 'const expanded=taskFlowExpandedSet().has(group.key)' in html
    assert 'data-task-group="${escapeHtml(group.key)}"' in html
    assert "expanded.delete(button.dataset.taskGroup)" in html
    assert "expanded.add(button.dataset.taskGroup)" in html
    assert "150+group.items.length*96" in html
    assert "const scale=state.graph.fit?Math.min" in html


def test_task_flow_hides_temporal_and_backward_edges_but_evidence_keeps_them(
    empty_audit_path: Path,
):
    html = _html()
    task_render = html.split("function renderTaskFlowGraph()", maxsplit=1)[1].split(
        "function timelineReason", maxsplit=1
    )[0]
    evidence_render = html.split("function renderEvidenceGraph()", maxsplit=1)[1].split(
        "function renderGraph()", maxsplit=1
    )[0]
    assert "projection.edges.filter(edge => edge.confirmed)" in task_render
    assert "to.x<=from.x" in task_render
    assert "task-flow-edge-label" not in task_render
    assert 'edge.temporal ? "temporal" : "direct"' in evidence_render
    assert "时序推断，不代表确定因果" in evidence_render


def test_trace_list_and_tool_chain_are_independent_scroll_regions(
    empty_audit_path: Path,
):
    html = _html()
    assert "height:clamp(560px,calc(100vh - 190px),1040px)" in html
    assert ".trace-panel { grid-template-rows:auto auto minmax(0,1fr); }" in html
    assert ".timeline-panel { grid-template-rows:auto minmax(0,1fr); }" in html
    assert "min-width:0" in html
    assert "grid-template-columns:minmax(0,1fr)" in html
    assert ".trace-panel > .scroll,.timeline,.graph-viewport-wrap" in html
    assert "overflow-y:auto" in html
    assert "overscroll-behavior-y:contain" in html
    assert "scrollbar-gutter:stable" in html
    assert "touch-action:pan-y" in html


def test_trace_cards_are_bounded_and_expand_full_values_in_popover(
    empty_audit_path: Path,
):
    html = _html()
    render_trace_list = html.split("function renderTraceList()", maxsplit=1)[1].split(
        "function replayClass", maxsplit=1
    )[0]
    assert "trace.session" not in render_trace_list
    assert "Integrity" not in render_trace_list
    assert "<b>Trace ID:</b>" in render_trace_list
    assert "shortTraceId(trace.id)" in render_trace_list
    assert "compact(trace.name, 13)" in render_trace_list
    assert "const titleMarkup = selected" in render_trace_list
    assert "const idMarkup = selected" in render_trace_list
    assert 'data-trace-popup="input"' in render_trace_list
    assert 'data-trace-popup="id"' in render_trace_list
    assert "function openTracePopover(trigger)" in html
    assert "完整用户输入" in html
    assert "完整 Trace ID" in html
    assert "未记录用户输入。该 Trace 可能来自旧版上报或关联字段缺失" in html
    assert "function missingTraceInputNotice()" in html
    assert ".trace { display:block; height:88px; min-height:88px; max-height:88px;" in html
    assert ".trace-popover.open" in html


def test_trace_header_shows_full_id_and_clickable_input_without_session(
    empty_audit_path: Path,
):
    html = _html()
    render_header = html.split("function renderTraceHeader()", maxsplit=1)[1].split(
        "function renderTimeline", maxsplit=1
    )[0]
    assert 'state.viewMode === "nebula" ? "审计星云图" : "工具调用链"' in render_header
    assert 'id="timelineViewBtn"' in html
    assert 'id="nebulaViewBtn"' in html
    assert "<b>Trace ID：</b><code>${escapeHtml(summary.id)}</code>" in render_header
    assert "shortId(summary.id)" not in render_header
    assert "summary.session" not in render_header
    assert "summary.user_input || missingTraceInputNotice()" in render_header
    assert "summary.name ||" not in render_header
    assert "<b>输入内容：</b>" in render_header
    assert "compact(inputText,62)" in render_header
    assert 'data-trace-popup="input"' in render_header
    assert "openTracePopover(inputTrigger)" in render_header


def test_nebula_entry_keeps_existing_tool_chain(empty_audit_path: Path):
    html = _html()
    assert 'id="timelineViewBtn"' in html
    assert 'data-view="timeline"' in html
    assert 'id="nebulaViewBtn"' in html
    assert 'data-view="nebula"' in html
    assert 'id="nebulaShell"' in html
    assert 'id="timeline"' in html
    assert "工具调用链" in html
    assert "星云图" in html


def test_nebula_uses_real_trace_and_event_apis(empty_audit_path: Path):
    html = _html()
    assert "/v1/audit/traces/${encodeURIComponent(traceId)}" in html
    assert "/v1/audit/events/${encodeURIComponent(eventId)}" in html
    assert "/v1/audit/events/${encodeURIComponent(source.event_id)}/${direction}?${PATH_QUERY}" in html
    assert 'const direction=mode==="impact"?"impacts":"causes"' in html
    assert "buildNebulaProjection(trace,width,height)" in html
    assert "orderedNodes(trace)" in html


def test_nebula_groups_only_real_tool_call_ids_and_keeps_trace_events(
    empty_audit_path: Path,
):
    html = _html()
    projection = html.split(
        "function buildNebulaProjection(trace,width,height)", maxsplit=1
    )[1].split("function nebulaPathSets", maxsplit=1)[0]
    assert "const toolCallId=timelineToolCallId(event)" in projection
    assert "toolGroups.set(toolCallId" in projection
    assert 'groupKey:toolCallId?`tool:${toolCallId}`:"trace"' in projection
    assert 'id:`nebula:tool:${group.id}`' in projection
    assert "tool_call_id" not in projection.lower().replace("toolcallid", "")


def test_nebula_projects_only_explicit_resources_and_keeps_projection_semantics(
    empty_audit_path: Path,
):
    html = _html()
    extract = html.split("function extractNebulaResources(event)", maxsplit=1)[1].split(
        "function buildNebulaProjection", maxsplit=1
    )[0]
    assert 'new Set(["file","file_path","filepath","path","filename"])' in extract
    assert 'new Set(["url","uri","endpoint"])' in extract
    assert 'new Set(["database","database_name","db","db_name","dsn"])' in extract
    assert "visit(asObject(event.content)" in extract
    assert "visit(asObject(event.metadata)" in extract
    node_markup = html.split("const nodeMarkup=(node,index) =>", maxsplit=1)[1].split(
        "const tooltipMarkup=node =>", maxsplit=1
    )[0]
    assert "投影视图" not in node_markup
    assert "该节点不是 AuditEvent，也不表示确定因果" in html


def test_nebula_canvas_uses_short_technical_codes_without_long_chinese_labels(
    empty_audit_path: Path,
):
    html = _html()
    code_mapper = html.split("function nebulaEventCode(event,kind)", maxsplit=1)[1].split(
        "function nebulaToolVerb", maxsplit=1
    )[0]
    for code in ("IN", "OUT", "ACL", "TOOL", "RAG", "CTX", "IO-IN", "IO-OUT", "RESULT"):
        assert f'return "{code}"' in code_mapper
    node_markup = html.split("const nodeMarkup=(node,index) =>", maxsplit=1)[1].split(
        "const tooltipMarkup=node =>", maxsplit=1
    )[0]
    for long_label in ("权限检查", "工具意图检查", "检索内容检查", "上下文安全检查", "投影视图"):
        assert long_label not in node_markup
    assert "node.subLabel" not in node_markup


def test_nebula_deduplicates_resources_inside_each_tool_cluster(
    empty_audit_path: Path,
):
    html = _html()
    collector = html.split("function collectNebulaResources(events)", maxsplit=1)[1].split(
        "function nebulaEventCode", maxsplit=1
    )[0]
    projection = html.split(
        "function buildNebulaProjection(trace,width,height)", maxsplit=1
    )[1].split("function nebulaPathSets", maxsplit=1)[0]
    assert "const resourcesByIdentity=new Map()" in collector
    assert 'const identity=`${resource.type}:${normalizedValue}`' in collector
    assert "collected.eventIds.add(event.event_id)" in collector
    assert "group.resources=collectNebulaResources(group.events)" in projection
    assert "resource.eventIds.forEach" in projection
    assert "eventNode.id" not in projection


def test_nebula_cluster_radius_and_placement_follow_actual_node_counts(
    empty_audit_path: Path,
):
    html = _html()
    radius = html.split("function nebulaOrbitRadius", maxsplit=1)[1].split(
        "function placeNebulaToolGroups", maxsplit=1
    )[0]
    placement = html.split("function placeNebulaToolGroups", maxsplit=1)[1].split(
        "function buildNebulaProjection", maxsplit=1
    )[0]
    projection = html.split(
        "function buildNebulaProjection(trace,width,height)", maxsplit=1
    )[1].split("function nebulaPathSets", maxsplit=1)[0]
    assert "minimum+(actualCount-1)*6" in radius
    assert "group.innerEvents.length" in projection
    assert "group.outerEvents.length+group.resources.length" in projection
    assert "group.radius=collapsed.has(group.id)?54:group.outerOrbit+48" in projection
    assert "coreRadius+group.radius+82" in placement
    assert "group.radius+other.radius+72" in placement
    assert "placeNebulaToolGroups([...toolGroups.values()],center,core.radius)" in projection


def test_nebula_is_dark_orbital_map_and_has_fullscreen_control(
    empty_audit_path: Path,
):
    html = _html()
    assert '.nebula-shell { --nebula-bg:#020914' in html
    assert ".nebula-orbit-boundary" in html
    assert ".nebula-orbit-arc" in html
    assert ".nebula-scan-ring" in html
    assert ".nebula-flow-particle" in html
    assert 'id="nebulaFullscreenBtn"' in html
    assert "async function toggleNebulaFullscreen()" in html
    assert 'document.addEventListener("fullscreenchange",syncNebulaFullscreen)' in html
    assert "prefers-reduced-motion:reduce" in html


def test_nebula_fullscreen_resize_preserves_graph_and_coalesces_events(
    empty_audit_path: Path,
):
    html = _html()
    graph = html.split("function createNebulaGraph()", maxsplit=1)[1].split(
        "function destroyNebulaGraph()", maxsplit=1
    )[0]
    resize = graph.split("const resize=() =>", maxsplit=1)[1].split(
        "return {setTrace", maxsplit=1
    )[0]
    assert 'svg.setAttribute("viewBox",`0 0 ${size.width} ${size.height}`)' in resize
    assert "projection.viewportWidth=size.width" in resize
    assert "fit();" in resize
    assert "setTrace(" not in resize
    assert "function scheduleNebulaResize()" in html
    assert "nebulaResizeFrame=requestAnimationFrame" in html
    assert "nebulaResizeSettleFrame" not in html
    assert "scheduleNebulaResize();" in html.split(
        "function syncNebulaFullscreen()", maxsplit=1
    )[1].split("async function toggleNebulaFullscreen()", maxsplit=1)[0]
    assert "nebulaResizeTimer" not in html


def test_nebula_view_switch_settles_before_reveal_without_replaying_same_trace(
    empty_audit_path: Path,
):
    html = _html()
    set_trace = html.split("const setTrace=(trace", maxsplit=1)[1].split(
        "const onWheel", maxsplit=1
    )[0]
    switch = html.split("function setViewMode(mode)", maxsplit=1)[1].split(
        "function initializeGraphModeControls", maxsplit=1
    )[0]
    render = html.split("function renderNebula(", maxsplit=1)[1].split(
        "async function loadNebulaPath", maxsplit=1
    )[0]
    assert "for(let step=0;step<150;step+=1)tick()" in set_trace
    assert "else{fit();" in set_trace
    assert "animate(150)" not in set_trace
    assert 'shell.classList.add("is-preparing")' in switch
    assert "nebulaViewFrame=requestAnimationFrame" in switch
    assert "nebulaRevealFrame=requestAnimationFrame" in switch
    assert "renderNebula()" in switch
    assert 'shell.classList.remove("is-preparing")' in switch
    assert "lastDisplayedTraceId!==traceId" in render
    assert "setTrace(state.trace,{animateEntrance,clusterEntrance:animateEntrance})" in render
    assert ".nebula-shell.is-preparing .nebula-viewport" in html


def test_nebula_tooltips_retain_full_event_tool_and_resource_information(
    empty_audit_path: Path,
):
    html = _html()
    tooltip = html.split("const tooltipMarkup=node =>", maxsplit=1)[1].split(
        "const styleScene", maxsplit=1
    )[0]
    assert "node.event.event_id" in tooltip
    assert "node.toolCallId" in tooltip
    assert "node.event.reason" in tooltip
    assert "node.resource.keyPaths" in tooltip
    assert "node.resource.eventIds.length" in tooltip
    assert "该节点不是 AuditEvent，也不表示确定因果" in tooltip


def test_nebula_hover_activates_first_order_neighborhood_and_dims_others(
    empty_audit_path: Path,
):
    html = _html()
    styles = html.split("/* Audit Nebula V1", maxsplit=1)[1].split("</style>", maxsplit=1)[0]
    scene = html.split("const styleScene=() =>", maxsplit=1)[1].split(
        "const setHoverNode", maxsplit=1
    )[0]
    assert ".nebula-node.is-hovered .nebula-node-visual { transform:scale(1.12); }" in styles
    assert ".nebula-node.is-hover-muted { opacity:.12!important; }" in styles
    assert ".nebula-edge.is-hover-muted { opacity:.12!important; }" in styles
    assert "edge.source===hoverNode.id||edge.target===hoverNode.id" in scene
    assert "hoverEdges.flatMap(edge=>[edge.source,edge.target])" in scene
    assert 'classList.toggle("is-hover-neighbor"' in scene
    assert 'classList.toggle("is-hover-related"' in scene


def test_nebula_hover_particles_keep_direction_and_preview_risk_sides(
    empty_audit_path: Path,
):
    html = _html()
    scene = html.split("const styleScene=() =>", maxsplit=1)[1].split(
        "const setHoverNode", maxsplit=1
    )[0]
    assert 'classList.toggle("is-hover-in",Boolean(hoverRelated&&edge.target===hoverNodeId))' in scene
    assert 'classList.toggle("is-hover-out",Boolean(hoverRelated&&edge.source===hoverNodeId))' in scene
    assert "edge.target===hoverNodeId" in scene
    assert "edge.source===hoverNodeId" in scene
    assert 'classList.toggle("is-risk-cause-preview"' in scene
    assert 'classList.toggle("is-risk-impact-preview"' in scene
    assert ".nebula-flow-particle.is-risk-cause-preview" in html
    assert ".nebula-flow-particle.is-risk-impact-preview" in html


def test_nebula_tool_hover_reveals_hull_and_runs_one_scan(
    empty_audit_path: Path,
):
    html = _html()
    hover = html.split("const setHoverNode=nodeId =>", maxsplit=1)[1].split(
        "const renderScene", maxsplit=1
    )[0]
    assert ".nebula-orbit-group.is-hovered" in html
    assert ".nebula-orbit-group.is-scanning .nebula-orbit-arc" in html
    assert "node?.kind===\"tool\"&&!reducedMotion" in hover
    assert 'classList.add("is-scanning")' in hover
    assert "setTimeout" in hover
    assert "920" in hover


def test_nebula_first_click_focuses_second_click_opens_drawer_and_trace_assembles_under_limit(
    empty_audit_path: Path,
):
    html = _html()
    focus = html.split("const focusOnNode=(node,complete) =>", maxsplit=1)[1].split(
        "const setTrace", maxsplit=1
    )[0]
    activation = html.split("const activateNode=node =>", maxsplit=1)[1].split(
        "const onPointerUp", maxsplit=1
    )[0]
    assert "duration=390" in focus
    assert "requestAnimationFrame(step)" in focus
    assert "alreadyFocused=focusedNodeId===node.id" in activation
    assert "if(!alreadyFocused)" in activation
    assert "focusedNodeId=node.id" in activation
    assert "focusOnNode(node" in activation
    assert "focusOnNode(node);return;" in activation
    assert activation.index("focusOnNode(node);return;") < activation.index(
        "selectEvent(eventId)"
    )
    assert "再次点击查看详情" in html
    assert "Math.min(entranceIndex*34,620)" in html
    assert "nebula-node-assemble .68s" in html


def test_nebula_trace_core_click_focuses_exactly_in_viewport_center(
    empty_audit_path: Path,
):
    html = _html()
    node_markup = html.split("const nodeMarkup=(node,index) =>", maxsplit=1)[1].split(
        "const tooltipMarkup", maxsplit=1
    )[0]
    focus = html.split("const focusOnNode=(node,complete) =>", maxsplit=1)[1].split(
        "const preserveToolTransitionLayout", maxsplit=1
    )[0]
    activation = html.split("const activateNode=node =>", maxsplit=1)[1].split(
        "const onPointerUp", maxsplit=1
    )[0]
    assert 'node.kind==="core"' in node_markup
    assert 'tabindex="0" role="button"' in node_markup
    assert 'targetY=node.kind==="core"?.5:.48' in focus
    assert 'if(node.kind==="core")' in activation
    assert "focusedNodeId=node.id" in activation
    assert "focusOnNode(node);return;" in activation


def test_nebula_initial_reveal_is_sequential_and_clusters_expand_from_tool_centers(
    empty_audit_path: Path,
):
    html = _html()
    prepare = html.split("const prepareInitialClusterEntrance=next =>", maxsplit=1)[
        1
    ].split("const setTrace", maxsplit=1)[0]
    set_trace = html.split("const setTrace=(trace", maxsplit=1)[1].split(
        "const onWheel", maxsplit=1
    )[0]
    assert 'node.kind==="core"?0' in prepare
    assert 'node.kind==="tool"?2' in prepare
    assert "node.entranceOrder=index" in prepare
    assert "node.x=tool.x" in prepare
    assert "node.y=tool.y" in prepare
    assert "node.ax=node.x" in prepare
    assert "node.ay=node.y" in prepare
    assert "prepareInitialClusterEntrance(projection)" in set_trace
    assert "clusterEntrance:animateEntrance" in html
    assert "if(clusterEntrance&&!reducedMotion)entranceTimer=setTimeout" in set_trace
    assert "projection?.signature===signature" in set_trace
    assert "},220)" in set_trace
    assert "*1.12" in html
    assert ".nebula-edge-group.is-entering" in html


def test_nebula_tool_cluster_toggle_preserves_view_and_animates_locally(
    empty_audit_path: Path,
):
    html = _html()
    toggle = html.split("const toggleToolGroup=node =>", maxsplit=1)[1].split(
        "const activateNode", maxsplit=1
    )[0]
    set_trace = html.split("const setTrace=(trace", maxsplit=1)[1].split(
        "const onWheel", maxsplit=1
    )[0]
    assert "preserveView:true" in toggle
    assert "transitionToolId:groupId" in toggle
    assert 'classList.toggle("is-cluster-closing"' in toggle
    assert "clusterTimer=setTimeout" in toggle
    assert "preserveToolTransitionLayout" in html
    assert "previousTransform={...transform}" in set_trace
    assert "transform=preserveView&&previous?previousTransform" in set_trace
    assert "fitAfterLayout=false" in set_trace
    assert ".nebula-node.is-cluster-closing .nebula-node-visual" in html
    assert ".nebula-node.is-entering .nebula-node-visual" in html
    assert ".nebula-orbit-group.is-entering" in html


def test_nebula_motion_is_idle_by_default_reduced_and_fully_cleaned_up(
    empty_audit_path: Path,
):
    html = _html()
    base_particle = html.split(".nebula-flow-particle {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    tool_ring = html.split(".nebula-tool-ring {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "opacity:0" in base_particle
    assert "animation:" not in base_particle
    assert "animation:" not in tool_ring
    assert ".nebula-flow-particle.is-hover-flow" in html
    assert ".nebula-flow-particle.is-cause" in html
    assert ".nebula-flow-particle.is-impact" in html
    assert 'window.matchMedia?.("(prefers-reduced-motion: reduce)")' in html
    cleanup = html.split("const cancelInteractiveWork=() =>", maxsplit=1)[1].split(
        "const dimensions", maxsplit=1
    )[0]
    for work in (
        "focusFrame",
        "pointerFieldFrame",
        "scanTimer",
        "clusterTimer",
        "entranceTimer",
        "ignoreClickTimer",
    ):
        assert work in cleanup
    destroy = html.split("destroy:()=>", maxsplit=1)[1].split("};", maxsplit=1)[0]
    assert "cancelAnimationFrame(frame)" in destroy
    assert "cancelInteractiveWork()" in destroy
    assert "replaceChildren()" in destroy


def test_nebula_distinguishes_edges_risk_impact_review_and_block(
    empty_audit_path: Path,
):
    html = _html()
    assert ".nebula-edge.confirmed" in html
    assert ".nebula-edge.temporal" in html
    assert "stroke-dasharray:7 7" in html
    assert 'edge.inference==="temporal_sequence"?"temporal":"confirmed"' in html
    assert ".nebula-node.risk-source .nebula-node-body" in html
    assert ".nebula-node.impacted:not(.risk-source) .nebula-impact-ring" in html
    assert ".nebula-node.review .nebula-node-body" in html
    assert ".nebula-node.blocked .nebula-block-ring" in html


def test_nebula_path_modes_highlight_backend_causes_and_impacts(
    empty_audit_path: Path,
):
    html = _html()
    assert 'data-nebula-path="all"' in html
    assert 'data-nebula-path="cause"' in html
    assert 'data-nebula-path="impact"' in html
    assert 'mode:state.nebula.pathMode' in html
    assert 'classList.toggle("is-cause"' in html
    assert 'classList.toggle("is-impact"' in html
    assert "state.pathResult=await requestJson" in html


def test_nebula_click_reuses_event_drawer_and_risk_focus(empty_audit_path: Path):
    html = _html()
    activation = html.split("const activateNode=node =>", maxsplit=1)[1].split(
        "const onPointerUp", maxsplit=1
    )[0]
    assert "state.nebula.focusRiskId=eventId" in activation
    assert "focusOnNode(node" in activation
    assert "selectEvent(eventId)" in activation
    assert "if(completed.node&&!completed.moved)activateNode(completed.node)" in html
    assert "state.drawerOpen=true" in html
    assert "/v1/audit/events/${encodeURIComponent(eventId)}" in html


def test_nebula_empty_error_and_instance_lifecycle(empty_audit_path: Path):
    html = _html()
    render = html.split("function renderNebula(", maxsplit=1)[1].split(
        "async function loadNebulaPath", maxsplit=1
    )[0]
    assert "暂无审计任务" in render
    assert "当前 Trace 没有事件" in render
    assert "浏览器不支持 SVG" in render
    assert "state.nebula.instance=createNebulaGraph()" in render
    assert (
        "state.nebula.instance.setTrace(state.trace,{animateEntrance,clusterEntrance:animateEntrance})"
        in render
    )
    assert "function destroyNebulaGraph()" in html
    assert "state.nebula.instance?.destroy()" in html
    before_unload = html.split(
        'window.addEventListener("beforeunload",', maxsplit=1
    )[1].split(",{once:true})", maxsplit=1)[0]
    assert "cancelAnimationFrame(nebulaResizeFrame)" in before_unload
    assert "destroyNebulaGraph()" in before_unload
    assert "已保留上一次成功数据" in html


def test_nebula_has_no_external_runtime_or_hardcoded_business_trace(
    empty_audit_path: Path,
):
    html = _html()
    assert not re.search(r'(?:src|href)=["\']https?://', html, re.I)
    assert "@antv" not in html.lower()
    assert "g6.min.js" not in html.lower()
    assert "tr-9a71f0c2" not in html
    assert "evt-001" not in html
    assert "未生成任何演示节点" in html


def test_empty_error_unknown_stage_and_module_have_safe_fallbacks(
    empty_audit_path: Path,
):
    html = _html()
    assert "暂无审计任务" in html
    assert "审计数据暂不可用" in html
    assert "stageText[stage] ||" in html
    assert "moduleText[module] ||" in html
    assert 'event.stage = String(event.stage ?? "unknown")' in html
    assert 'event.source_module = String(event.source_module ?? "unknown")' in html


def test_browser_export_and_explicit_trace_deletion_flow(
    empty_audit_path: Path,
):
    html = _html()
    assert "new Blob([JSON.stringify(state.trace.raw" in html
    assert "URL.createObjectURL" in html
    assert 'id="selectTraces"' in html
    assert 'id="deleteTraces"' in html
    assert 'id="cancelTraceSelection"' in html
    assert "function toggleTraceSelection(traceId)" in html
    assert "function deleteSelectedTraces()" in html
    assert 'requestJson("/v1/audit/traces",{' in html
    assert 'method:"DELETE"' in html
    assert "JSON.stringify({trace_ids:traceIds})" in html
    assert "window.confirm" in html
    assert "清空筛选" not in html
    assert "只看风险任务" in html
    assert "white-space:nowrap" in html


def test_audit_routes_only_expose_the_explicit_operator_mutations(
    empty_audit_path: Path,
):
    methods_by_path = {
        (route.path, tuple(sorted(route.methods))) for route in audit_router.routes
    }
    assert ("/v1/audit/traces", ("DELETE",)) in methods_by_path
    assert ("/v1/audit/events/{event_id}/risk-review", ("PUT",)) in methods_by_path
    allowed_mutations = {
        ("/v1/audit/traces", ("DELETE",)),
        ("/v1/audit/events/{event_id}/risk-review", ("PUT",)),
    }
    assert all(
        methods == ("GET",) or (path, methods) in allowed_mutations
        for path, methods in methods_by_path
    )
