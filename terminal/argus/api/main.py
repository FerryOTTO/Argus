"""Argus 第一版统一 FastAPI 接口。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel, Field

from argus.api.audit_routes import router as audit_router
from argus.api.quarantine_routes import router as quarantine_router
from argus.api.tool_guard_routes import router as tool_guard_router
from argus.api.local_config_routes import router as local_config_router
from argus.api.openclaw_providers_routes import router as openclaw_providers_router
from argus.api.remote_routes import router as remote_router
from argus.api.skills_routes import router as skills_router
from argus.api.usage_routes import router as usage_router
from argus.common.models import (
    Action,
    AuditEvent,
    ModuleResult,
    RequestContext,
    SecurityRequest,
    SecurityResponse,
)
from argus.core.registry import AdapterRegistry, registry
from argus.modules.audit.original import AuditStore
from argus.modules.audit.integration import (
    emit_module_audit_event,
    emitted_event_id,
    latest_tool_pre_event_id,
)
from argus.modules.tool_guard import session_store
from argus.modules.tool_guard.llm_config import ToolGuardLLMConfig


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        from argus.api.remote_sync import start_remote_sync
        start_remote_sync(app)
    except Exception:
        pass
    yield
    try:
        from argus.api.remote_sync import stop_remote_sync
        await stop_remote_sync()
    except Exception:
        pass


app = FastAPI(
    lifespan=_lifespan,
    title="Argus API",
    version="0.1.0",
    description="Argus 各安全模块的统一测试入口。",
)
app.include_router(audit_router)
app.include_router(quarantine_router)
app.include_router(tool_guard_router)
app.include_router(local_config_router)
app.include_router(openclaw_providers_router)
app.include_router(remote_router)
app.include_router(skills_router)
app.include_router(usage_router)

AUDIT_EVENTS_PER_TOOL_CALL = 4



def _desktop_number(value: Any) -> float:
    """Accept the common provider usage field names without trusting malformed data."""
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _desktop_usage_fields(event: dict[str, Any]) -> tuple[str, dict[str, float]]:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    content = event.get("content") if isinstance(event.get("content"), dict) else {}
    details = metadata.get("details") if isinstance(metadata.get("details"), dict) else {}
    raw_usage = metadata.get("usage") or metadata.get("token_usage") or content.get("usage") or {}
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    model = str(metadata.get("model") or content.get("model") or details.get("model") or "tool_guard")
    return model, {
        "input": _desktop_number(usage.get("input_tokens", usage.get("prompt_tokens", usage.get("input", 0)))),
        "output": _desktop_number(usage.get("output_tokens", usage.get("completion_tokens", usage.get("output", 0)))),
        "cacheCreate": _desktop_number(usage.get("cache_creation_input_tokens", usage.get("cache_write_tokens", usage.get("cache_create", 0)))),
        "cacheRead": _desktop_number(usage.get("cache_read_input_tokens", usage.get("cached_tokens", usage.get("cache_read", 0)))),
        "cost": _desktop_number(usage.get("cost", usage.get("total_cost", 0))),
    }


def _desktop_usage_bucket(days: int, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0) if days == 1 else (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    count = max(1, int((now - start).total_seconds() // 3600) + 1) if days == 1 else days
    points = []
    for index in range(count):
        moment = start + (timedelta(hours=index) if days == 1 else timedelta(days=index))
        points.append({"time": moment.strftime("%H:00" if days == 1 else "%m/%d"), "input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0, "cost": 0, "requests": 0})
    for event in events:
        try:
            timestamp = datetime.fromisoformat(str(event.get("timestamp", "")).replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            continue
        index = int((timestamp - start).total_seconds() // (3600 if days == 1 else 86400))
        if not 0 <= index < len(points):
            continue
        _, fields = _desktop_usage_fields(event)
        point = points[index]
        for key, value in fields.items():
            point[key] += value
        point["requests"] += 1
    for point in points:
        point["cost"] = round(point["cost"], 6)
    return points


@app.get("/v1/desktop/runtime")
def get_desktop_runtime() -> dict[str, Any]:
    """用量看板数据源：插件 token 账本（llm_output 钩子记的真实消耗）。

    不再返回供应商列表（个人版首页已改为整文件编辑 openclaw.json，用量下拉框
    走 /v1/local/openclaw-providers）。usage 结构保持 {today,7d,30d} 不变，前端零改。
    无账本数据时返回全零刻度，不编数。
    """
    from argus.api import usage_routes as _usage

    data = _usage.read_usage_buckets()
    return {
        "source": "argus-usage-ledger",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "usage": {"today": data["today"], "7d": data["7d"], "30d": data["30d"]},
    }


def _audit_sequence(request: SecurityRequest, offset: int) -> int | None:
    """Expand a zero-based tool-call sequence into stable module event slots."""

    tool_sequence = request.payload.get("sequence")
    if (
        isinstance(tool_sequence, bool)
        or not isinstance(tool_sequence, int)
        or tool_sequence < 0
    ):
        return None
    return tool_sequence * AUDIT_EVENTS_PER_TOOL_CALL + offset


def _select_action(results: Iterable[ModuleResult]) -> Action:
    """按照 policy.yaml 中的优先级选择最终动作。"""

    result_list = list(results)
    priorities = registry.action_priority
    for action in priorities:
        if any(result.action == action for result in result_list):
            return action
    return "allow"


def _build_response(
    request: SecurityRequest,
    results: list[ModuleResult],
) -> SecurityResponse:
    """将一个或多个 Adapter 的结果转换为统一响应。"""

    action = _select_action(results)
    risk_score = max((item.risk_score for item in results), default=0.0)
    selected = next((item for item in results if item.action == action), None)

    data = None if action in {"rewrite", "human_review"} else request.payload
    for result in results:
        if (
            result.action in {"rewrite", "human_review"}
            and result.modified_data is not None
        ):
            data = result.modified_data

    return SecurityResponse(
        trace_id=request.context.trace_id,
        stage=request.context.stage,
        action=action,
        risk_score=risk_score,
        reason=selected.reason if selected else "passed",
        data=data,
        module_results=results,
    )


async def _run_adapter(
    adapter_registry: AdapterRegistry,
    adapter_name: str,
    request: SecurityRequest,
) -> ModuleResult:
    """运行单个 Adapter，并按 modules.yaml 处理模板阶段的异常。"""

    adapter = adapter_registry.get(adapter_name)
    try:
        return await adapter.run(request)
    except Exception as exc:  # 模板兜底，真实 Adapter 仍应自行记录错误
        on_error = adapter_registry.on_error(adapter_name)
        action: Action = "block" if on_error == "block" else "allow"
        return ModuleResult(
            module=adapter_name,
            success=False,
            action=action,
            risk_score=1.0 if action == "block" else 0.0,
            reason="module_error",
            error=str(exc),
        )


@app.get("/health")
async def health() -> dict:
    """返回统一服务和各 Adapter 的启用状态。"""

    return {"status": "ok", "modules": registry.health()}


@app.post("/v1/input/check", response_model=SecurityResponse)
async def check_input(request: SecurityRequest) -> SecurityResponse:
    """输入安全检查测试接口。"""

    result = await _run_adapter(registry, "io_guard_input", request)
    await emit_module_audit_event(
        request,
        result,
        audit_adapter=registry.get("audit"),
    )
    return _build_response(request, [result])


@app.post("/v1/tool/pre_check", response_model=SecurityResponse)
async def check_tool_pre(request: SecurityRequest) -> SecurityResponse:
    """依次执行访问控制和工具安全检查。"""

    results: list[ModuleResult] = []
    access_sequence = _audit_sequence(request, 0)
    tool_sequence = _audit_sequence(request, 1)

    access_result = await _run_adapter(registry, "access_control", request)
    results.append(access_result)
    access_audit_result = await emit_module_audit_event(
        request,
        access_result,
        audit_adapter=registry.get("audit"),
        sequence=access_sequence,
    )
    if access_result.action == "block":
        return _build_response(request, results)

    if not registry.is_enabled("tool_guard"):
        return _build_response(request, results)

    tool_result = await _run_adapter(registry, "tool_guard", request)
    results.append(tool_result)
    await emit_module_audit_event(
        request,
        tool_result,
        audit_adapter=registry.get("audit"),
        parent_event_id=emitted_event_id(access_audit_result),
        sequence=tool_sequence,
    )
    return _build_response(request, results)


@app.post("/v1/content/check", response_model=SecurityResponse)
async def check_content(request: SecurityRequest) -> SecurityResponse:
    """检查检索或工具返回的外部内容。"""

    results: list[ModuleResult] = []
    retrieval_result = await _run_adapter(registry, "retrieval_guard", request)
    results.append(retrieval_result)
    retrieval_audit_result = await emit_module_audit_event(
        request,
        retrieval_result,
        audit_adapter=registry.get("audit"),
        parent_event_id=latest_tool_pre_event_id(request),
        sequence=_audit_sequence(request, 2),
    )

    if retrieval_result.action == "block":
        return _build_response(request, results)

    if registry.is_enabled("io_guard_context"):
        context_request = request
        modified = retrieval_result.modified_data
        if retrieval_result.action == "rewrite" and isinstance(modified, dict):
            rewritten_content = modified.get("content", modified.get("text"))
            if isinstance(rewritten_content, str):
                payload = dict(request.payload)
                payload["content"] = rewritten_content
                context_request = request.model_copy(update={"payload": payload})
        context_result = await _run_adapter(
            registry,
            "io_guard_context",
            context_request,
        )
        results.append(context_result)
        await emit_module_audit_event(
            context_request,
            context_result,
            audit_adapter=registry.get("audit"),
            parent_event_id=emitted_event_id(retrieval_audit_result),
            sequence=_audit_sequence(request, 3),
        )

    return _build_response(request, results)


@app.post("/v1/output/check", response_model=SecurityResponse)
async def check_output(request: SecurityRequest) -> SecurityResponse:
    """输出安全检查测试接口。"""

    result = await _run_adapter(registry, "io_guard_output", request)
    await emit_module_audit_event(
        request,
        result,
        audit_adapter=registry.get("audit"),
    )
    return _build_response(request, [result])


@app.post("/v1/audit/event", response_model=ModuleResult)
async def write_audit_event(event: AuditEvent) -> ModuleResult:
    """接收一条统一审计事件。"""

    request = SecurityRequest(
        context=RequestContext(
            trace_id=event.trace_id,
            session_id=event.session_id,
            user_id=event.user_id,
            stage="audit",
            timestamp=event.timestamp,
        ),
        payload=event.model_dump(),
    )
    return await _run_adapter(registry, "audit", request)


class ToolSessionPromptRequest(BaseModel):
    """绑定会话的用户原始输入。"""

    session_id: str
    prompt: str
    trace_id: str = ""


class ToolSessionCallRequest(BaseModel):
    """回写一次已执行的工具调用。"""

    session_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""


@app.post("/v1/tool/session/prompt")
async def bind_tool_session_prompt(body: ToolSessionPromptRequest) -> dict:
    """OpenClaw 收到用户输入时调用,记录意图锚点。"""

    session = session_store.store.set_prompt(body.session_id, body.prompt)
    return {"status": "ok", "session": session.to_dict()}


@app.post("/v1/tool/session/call")
async def record_tool_session_call(body: ToolSessionCallRequest) -> dict:
    """OpenClaw 工具执行完成后调用,追加工具链记录。"""

    session = session_store.store.record_call(
        body.session_id, body.tool_name, body.arguments
    )
    return {"status": "ok", "session": session.to_dict()}


@app.get("/v1/tool_guard/config")
async def get_tool_guard_config() -> dict:
    """查看 Tool Guard LLM 裁判配置(api_key 脱敏)。"""

    return {"config": ToolGuardLLMConfig.instance().snapshot()}


@app.put("/v1/tool_guard/config")
async def update_tool_guard_config(body: dict[str, Any]) -> dict:
    """运行期更新 Tool Guard LLM 裁判配置,仅内存生效。"""

    return {"config": ToolGuardLLMConfig.instance().update(body)}

