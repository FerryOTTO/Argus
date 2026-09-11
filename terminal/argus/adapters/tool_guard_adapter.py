"""工具安全模块 Adapter:对接意图匹配裁判(LLM 打分)。

职责(翻译官):收统一 ``SecurityRequest`` → 从会话存储取用户原始意图与已执行工具链
→ 调用 ``IntentMatchDetector`` 对本次调用打分 → 按阈值映射为统一动作:
- ``score >= review_threshold``(默认 0.7)→ allow
- ``block_threshold <= score < review_threshold``(默认 0.4~0.7)→ human_review
- ``score < block_threshold`` → block

审计:判定结果由 API 层统一通过 audit 模块进程内写入(``emit_module_audit_event``),
Adapter 自身不直接对接审计,避免与审计模块重复。

兜底语义:
- LLM 未配置 / 调用异常 → 按 ``on_error`` 配置(默认 block)返回 ``module_error``;
- 会话无上下文(OpenClaw 未接补丁)→ 放行并标记 ``no_session_context``,
  避免联调期误伤,接入补丁后自动进入真实判定。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from argus.adapters.base import BaseAdapter
from argus.common.models import ModuleResult, SecurityRequest
from argus.modules.tool_guard import session_store
from argus.modules.tool_guard.intent_match import IntentMatchDetector
from argus.modules.tool_guard.llm_config import ToolGuardLLMConfig


class ToolGuardAdapter(BaseAdapter):
    name = "tool_guard"

    def __init__(
        self,
        *,
        config: ToolGuardLLMConfig | None = None,
        store: session_store.ToolSessionStore | None = None,
        on_error: str | None = None,
        detector: IntentMatchDetector | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._on_error = on_error
        self._detector = detector

    async def run(self, request: SecurityRequest) -> ModuleResult:
        started = perf_counter()
        try:
            result = await self._run_checked(request, started)
        except Exception as exc:
            # 兜底:LLM 调用失败、响应异常等,按 on_error 处理
            blocking = self._on_error == "block"
            result = ModuleResult(
                module=self.name,
                success=False,
                action="block" if blocking else "allow",
                risk_score=1.0 if blocking else 0.0,
                reason="module_error",
                latency_ms=round((perf_counter() - started) * 1000, 3),
                error=str(exc),
            )
        return result

    async def _run_checked(
        self, request: SecurityRequest, started: float
    ) -> ModuleResult:
        session_id = request.context.session_id
        tool_name = str(request.payload.get("tool_name", ""))
        arguments = request.payload.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}

        config = self._config or ToolGuardLLMConfig.instance()
        store = self._store or session_store.store
        session = store.get(session_id)

        # 会话无上下文:OpenClaw 尚未接入补丁,联调期放行并提示
        if session is None or not session.original_prompt.strip():
            return ModuleResult(
                module=self.name,
                success=False,
                action="allow",
                reason="no_session_context",
                details={
                    "hint": "call POST /v1/tool/session/prompt to bind original prompt",
                    "session_id": session_id,
                },
                latency_ms=round((perf_counter() - started) * 1000, 3),
            )

        # LLM 未配置:按 on_error 语义处理(默认 block)
        if not config.configured():
            blocking = self._on_error == "block"
            return ModuleResult(
                module=self.name,
                success=False,
                action="block" if blocking else "allow",
                risk_score=1.0 if blocking else 0.0,
                reason="llm_unconfigured",
                details={"hint": "set TOOL_GUARD_LLM_* env or PUT /v1/tool_guard/config"},
                latency_ms=round((perf_counter() - started) * 1000, 3),
            )

        detector = self._detector or IntentMatchDetector.from_config(config)
        result = await detector.detect(
            original_prompt=session.original_prompt,
            tool_chain=list(session.tool_calls),
            tool_name=tool_name,
            arguments=arguments,
        )

        block_threshold = float(config.get("block_threshold", 0.4))
        review_threshold = float(config.get("review_threshold", 0.7))

        if result.score < block_threshold:
            action: str = "block"
            risk_score = 1.0
        elif result.score < review_threshold:
            action = "human_review"
            risk_score = 0.6
        else:
            action = "allow"
            risk_score = 0.0

        # 判定反馈写回会话,供 Web 管理界面复盘意图漂移/劫持过程
        store.record_verdict(
            session_id,
            tool_name,
            arguments,
            score=result.score,
            reason=result.reason,
            deviation=result.deviation,
            action=action,
        )

        return ModuleResult(
            module=self.name,
            success=True,
            action=action,  # type: ignore[arg-type]
            risk_score=risk_score,
            reason=f"intent_score={result.score:.2f}; {result.reason}",
            details={
                "score": round(result.score, 4),
                "block_threshold": block_threshold,
                "review_threshold": review_threshold,
                "deviation": result.deviation,
                "tool_name": tool_name,
                "chain_length": len(session.tool_calls),
                "chain_truncated": session.chain_truncated,
            },
            latency_ms=round((perf_counter() - started) * 1000, 3),
        )
