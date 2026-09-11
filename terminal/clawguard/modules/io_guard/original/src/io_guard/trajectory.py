from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from io_guard.types import Decision, GuardRequest, GuardResult


@dataclass
class TrajectoryState:
    trace_id: str
    steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return (
            "unsafe"
            if any(step["decision"] == Decision.BLOCK.value for step in self.steps)
            else "safe"
        )


class TrajectoryStore:
    """Small in-process trajectory index keyed by the existing trace id."""

    def __init__(self, max_steps_per_trace: int = 64) -> None:
        self.max_steps_per_trace = max_steps_per_trace
        self._states: dict[str, TrajectoryState] = {}
        self._lock = Lock()

    def append(self, request: GuardRequest, result: GuardResult) -> dict[str, Any]:
        primary = result.primary_risk
        step = {
            "event_id": result.event_id,
            "source_type": request.source_type.value,
            "decision": result.decision.value,
            "primary_label": primary.value if primary else None,
            "dimension": primary.dimension.value if primary else None,
            "mitigated": result.decision == Decision.REWRITE,
        }
        with self._lock:
            state = self._states.setdefault(
                request.trace_id,
                TrajectoryState(trace_id=request.trace_id),
            )
            state.steps.append(step)
            if len(state.steps) > self.max_steps_per_trace:
                state.steps[:] = state.steps[-self.max_steps_per_trace :]
            return {
                "trace_id": state.trace_id,
                "verdict": state.verdict,
                "step_count": len(state.steps),
                "unsafe_step_ids": [
                    item["event_id"]
                    for item in state.steps
                    if item["decision"] == Decision.BLOCK.value
                ],
            }
