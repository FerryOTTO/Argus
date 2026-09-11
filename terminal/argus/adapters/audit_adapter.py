"""Adapter for the in-process Argus Audit implementation."""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any, Callable

from argus.adapters.base import BaseAdapter
from argus.common.models import AuditEvent, ModuleResult, SecurityRequest


class AuditAdapter(BaseAdapter):
    name = "audit"

    def __init__(
        self,
        recorder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._recorder = recorder

    async def run(self, request: SecurityRequest) -> ModuleResult:
        started = perf_counter()
        try:
            event = AuditEvent.model_validate(request.payload)
            recorder = self._get_recorder()
            receipt = await asyncio.to_thread(
                recorder, event.model_dump(mode="json")
            )
            return ModuleResult(
                module=self.name,
                success=True,
                action="allow",
                risk_score=event.risk_score,
                reason="audit_recorded",
                details=receipt,
                latency_ms=round((perf_counter() - started) * 1000, 3),
            )
        except Exception as exc:
            return ModuleResult(
                module=self.name,
                success=False,
                action="allow",
                reason="audit_write_error",
                latency_ms=round((perf_counter() - started) * 1000, 3),
                error=str(exc),
            )

    def _get_recorder(self) -> Callable[[dict[str, Any]], dict[str, Any]]:
        if self._recorder is None:
            from argus.modules.audit.original import record_audit_event

            self._recorder = record_audit_event
        return self._recorder
