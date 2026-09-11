from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from io_guard.pipeline import IOGuard
from io_guard.types import Decision, GuardRequest, GuardResult, SourceType


AgentHandler = Callable[[str, list[str], dict[str, Any]], str]


@dataclass
class GuardedRunResult:
    """Final result of one input-to-output guarded agent run."""

    trace_id: str
    decision: Decision
    output: str
    stages: list[GuardResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "decision": self.decision.value,
            "output": self.output,
            "stages": [stage.to_dict() for stage in self.stages],
        }


class GuardedAgentRunner:
    """Framework-neutral minimal closed loop around an Agent/OpenClaw call."""

    def __init__(self, guard: IOGuard, agent_handler: AgentHandler) -> None:
        self.guard = guard
        self.agent_handler = agent_handler

    def run(
        self,
        user_input: str,
        *,
        retrieval_chunks: Iterable[str] = (),
        user_context: dict[str, Any] | None = None,
    ) -> GuardedRunResult:
        context = dict(user_context or {})
        trace_id = str(context.get("trace_id") or uuid4())
        context["trace_id"] = trace_id
        parent_event_id = context.get("parent_event_id")
        stages: list[GuardResult] = []

        pre_result = self.guard.pre_check(
            self._request(
                user_input,
                SourceType.USER_PROMPT,
                context,
                parent_event_id,
            )
        )
        stages.append(pre_result)
        stop = self._stop_result(pre_result, stages)
        if stop is not None:
            return stop
        parent_event_id = pre_result.event_id

        safe_chunks: list[str] = []
        for chunk in retrieval_chunks:
            retrieval_result = self.guard.check_retrieval_content(
                self._request(
                    chunk,
                    SourceType.RETRIEVAL_CHUNK,
                    context,
                    parent_event_id,
                )
            )
            stages.append(retrieval_result)
            stop = self._stop_result(retrieval_result, stages)
            if stop is not None:
                return stop
            safe_chunks.append(retrieval_result.sanitized_content)
            parent_event_id = retrieval_result.event_id

        draft_output = self.agent_handler(
            pre_result.sanitized_content,
            safe_chunks,
            context,
        )
        post_result = self.guard.post_check(
            self._request(
                draft_output,
                SourceType.MODEL_OUTPUT,
                context,
                parent_event_id,
            )
        )
        stages.append(post_result)
        stop = self._stop_result(post_result, stages)
        if stop is not None:
            return stop

        return GuardedRunResult(
            trace_id=trace_id,
            decision=post_result.decision,
            output=post_result.sanitized_content,
            stages=stages,
        )

    def _request(
        self,
        content: str,
        source_type: SourceType,
        context: dict[str, Any],
        parent_event_id: str | None,
    ) -> GuardRequest:
        return GuardRequest(
            content=content,
            source_type=source_type,
            trace_id=context["trace_id"],
            session_id=str(context.get("session_id", "")),
            user_id=str(context.get("user_id", "")),
            role_level=int(context.get("role_level", 0)),
            principal_type=str(
                context.get("principal_type", "external_user")
            ),
            target_audience=str(
                context.get("target_audience", "external")
            ),
            channel_classification=str(
                context.get("channel_classification", "public")
            ),
            purpose=str(context.get("purpose", "")),
            allowed_data_scopes=set(context.get("allowed_data_scopes", [])),
            metadata=dict(context.get("metadata", {})),
            parent_event_id=parent_event_id,
        )

    def _stop_result(
        self,
        result: GuardResult,
        stages: list[GuardResult],
    ) -> GuardedRunResult | None:
        if result.decision == Decision.BLOCK:
            return GuardedRunResult(
                trace_id=result.trace_id,
                decision=result.decision,
                output="请求被安全策略阻断。",
                stages=stages.copy(),
            )
        return None
