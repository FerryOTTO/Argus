"""Clawguard adapter for the integrated IO Guard implementation."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from clawguard.adapters.base import BaseAdapter
from clawguard.common.models import ModuleResult, SecurityRequest
from clawguard.modules.media_input import extract_attachments
from clawguard.modules.media_input.config import load_media_config


MODULE_ROOT = Path(__file__).resolve().parents[1] / "modules" / "io_guard"
DEFAULT_POLICY_PATH = (
    MODULE_ROOT / "original" / "configs" / "default_policy.json"
)

_ACTION_RANK = {"allow": 0, "human_review": 1, "rewrite": 2, "block": 3}


class IoGuardAdapter(BaseAdapter):
    """Translate Clawguard requests to the original IO Guard service API.

    The original package is installed from ``modules/io_guard/original`` as an
    editable dependency.  Service construction is lazy so importing the
    Clawguard API remains cheap and a missing optional model is reported as a
    normal module error instead of crashing application startup.
    """

    name = "io_guard"
    _STAGE_MODULES = {
        "input": "io_guard.input",
        "content": "io_guard.context",
        "output": "io_guard.output",
    }

    def __init__(self, service: Any | None = None) -> None:
        self._service = service
        self._delegate: Any | None = None

    async def run(self, request: SecurityRequest) -> ModuleResult:
        started = perf_counter()
        try:
            delegate = self._get_delegate()
            if self._has_attachments(request):
                return await self._run_with_attachments(
                    request, delegate, started
                )
            return await delegate.run(request)
        except Exception as exc:
            stage = str(request.context.stage)
            return ModuleResult(
                module=self._STAGE_MODULES.get(stage, f"io_guard.{stage}"),
                success=False,
                action="allow",
                reason="module_error",
                details={"stage": stage},
                latency_ms=round((perf_counter() - started) * 1000, 3),
                error=str(exc),
            )

    def _has_attachments(self, request: SecurityRequest) -> bool:
        if str(request.context.stage) != "input":
            return False
        if not self._media_enabled():
            return False
        attachments = request.payload.get("attachments")
        return isinstance(attachments, list) and len(attachments) > 0

    def _media_enabled(self) -> bool:
        try:
            from clawguard.core.registry import registry

            if not registry.module_config("io_guard_input").get(
                "media_extraction", False
            ):
                return False
            return bool(
                load_media_config(DEFAULT_POLICY_PATH).get("enabled", True)
            )
        except Exception:
            return False

    async def _run_with_attachments(
        self,
        request: SecurityRequest,
        delegate: Any,
        started: float,
    ) -> ModuleResult:
        cfg = load_media_config(DEFAULT_POLICY_PATH)
        extracted = await asyncio.to_thread(
            extract_attachments, request.payload["attachments"], cfg
        )
        main_result = await delegate.run(request)

        verdicts: list[dict[str, Any]] = []
        strictest = main_result
        strictest_name: str | None = None
        for item in extracted:
            verdict: dict[str, Any] = {
                "name": item.name,
                "path": item.path,
                "url": item.url,
                "mime_type": item.mime_type,
                "action": "skipped",
            }
            if item.error is not None:
                verdict["action"] = "error"
                verdict["error"] = item.error
            elif item.text:
                sub_payload = dict(request.payload)
                sub_payload["text"] = item.text
                sub_request = request.model_copy(
                    update={"payload": sub_payload}
                )
                sub_result = await delegate.run(sub_request)
                verdict["action"] = sub_result.action
                verdict["risk_score"] = sub_result.risk_score
                verdict["primary_label"] = sub_result.details.get(
                    "primary_label"
                )
                verdict["reason"] = sub_result.reason
                if _ACTION_RANK[sub_result.action] > _ACTION_RANK[
                    strictest.action
                ]:
                    strictest = sub_result
                    strictest_name = item.name
            else:
                verdict["action"] = "empty"
            verdicts.append(verdict)

        details = dict(strictest.details)
        details["attachment_verdicts"] = verdicts
        reason = (
            f"附件 {strictest_name} 命中安全策略: {strictest.reason}"
            if strictest_name is not None
            else strictest.reason
        )
        return ModuleResult(
            module=strictest.module,
            success=strictest.success,
            action=strictest.action,
            risk_score=strictest.risk_score,
            reason=reason,
            modified_data=strictest.modified_data,
            details=details,
            latency_ms=round((perf_counter() - started) * 1000, 3),
        )

    def _get_delegate(self) -> Any:
        if self._delegate is not None:
            return self._delegate

        import sys
        src_path = str(MODULE_ROOT / "original" / "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from io_guard.adapters.clawguard_adapter import (
            IOGuardAdapter as OriginalIOGuardAdapter,
        )
        from io_guard.service import build_service

        if self._service is None:
            configured_policy = os.getenv("IO_GUARD_POLICY")
            policy_path = (
                Path(configured_policy)
                if configured_policy
                else DEFAULT_POLICY_PATH
            )
            configured_audit = os.getenv("IO_GUARD_AUDIT_PATH")
            audit_path = Path(configured_audit) if configured_audit else None
            self._service = build_service(policy_path, audit_path)

        self._delegate = OriginalIOGuardAdapter(self._service)
        return self._delegate
