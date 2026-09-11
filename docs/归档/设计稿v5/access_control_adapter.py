"""访问控制模块 Adapter:对接审计实时风险评分,动态升级防线与二次审批。

职责(翻译官):收统一 ``SecurityRequest`` → 调访问控制核心 ``check_v4`` 判定
→ 从审计模块读取用户实时风险评分 → 按风险动态升级防线(penalty 提高所需等级)
→ 升级后本应拦截的请求转 ``human_review`` 二次审批。

联动语义:
- 无审计事件 / 风险低于阈值 → 维持访问控制原始判定(allow/block);
- 风险达到阈值 → 动态提高资源所需等级重新判定:
  - 原始拦截 → 保持 block(最高防线);
  - 升级后仍放行 → allow(防线已收紧但依然够格);
  - 升级后本应拦截 → human_review(二次审批);
- 审计模块不可用 / 读取异常 → fail-open,按原始判定返回,不阻断正常流程。
"""

from __future__ import annotations

import os
from time import perf_counter
from typing import Any

from argus.adapters.base import BaseAdapter
from argus.common.models import ModuleResult, SecurityRequest
from argus.modules.access_control.original.auth_gateway import check_v4
from argus.modules.access_control.risk_link import (
    AuditRiskMonitor,
    DynamicLinePolicy,
)


class AccessControlAdapter(BaseAdapter):
    name = "access_control"

    def __init__(
        self,
        *,
        risk_monitor: AuditRiskMonitor | None = None,
        risk_policy: DynamicLinePolicy | None = None,
        risk_link_enabled: bool | None = None,
    ) -> None:
        # 审计联动默认开启；可用 ARGUS_AC_RISK_LINK=0 关闭
        self._risk_link_enabled = (
            risk_link_enabled
            if risk_link_enabled is not None
            else os.getenv("ARGUS_AC_RISK_LINK", "1") != "0"
        )
        self._risk_monitor = risk_monitor or AuditRiskMonitor()
        self._risk_policy = risk_policy or DynamicLinePolicy()

    def run_sync(self, request: SecurityRequest | dict[str, Any]) -> ModuleResult | dict[str, Any]:
        started = perf_counter()
        is_dict_input = isinstance(request, dict)

        try:
            if is_dict_input:
                context = request.get("context", {})
                payload = request.get("payload", {})
                user_id = str(context.get("user_id", "default_user"))
                session_id = str(context.get("session_id", ""))
            else:
                context = request.context
                payload = request.payload or {}
                user_id = str(context.user_id)
                session_id = str(context.session_id)

            tool_name = str(payload.get("tool_name", ""))
            if tool_name and not tool_name.startswith("tool:"):
                tool_name = f"tool:{tool_name}"
            arguments = payload.get("arguments", {})
            path = ""
            if isinstance(arguments, dict):
                path = str(arguments.get("path", ""))
            if path:
                path = os.path.normpath(path)

            database = str(payload.get("database", ""))

            res_dict = self._decide(
                user_id=user_id,
                session_id=session_id,
                path=path,
                tool=tool_name,
                database=database,
            )

            latency = (perf_counter() - started) * 1000
            res_dict["latency_ms"] = round(latency, 3)

            if is_dict_input:
                return res_dict
            return ModuleResult(**res_dict)

        except Exception as exc:
            latency = (perf_counter() - started) * 1000
            err_dict = {
                "module": self.name,
                "success": False,
                "action": "block",
                "risk_score": 1.0,
                "reason": "module_error",
                "modified_data": None,
                "details": {},
                "latency_ms": round(latency, 3),
                "error": str(exc),
            }
            if is_dict_input:
                return err_dict
            return ModuleResult(**err_dict)

    def _decide(
        self,
        *,
        user_id: str,
        session_id: str,
        path: str,
        tool: str,
        database: str,
    ) -> dict[str, Any]:
        """原始判定 → 审计风险评估 → 防线升级决策。"""
        result = check_v4(user_id=user_id, path=path, tool=tool, database=database)
        allowed = bool(result.get("allowed", False))
        reason = str(result.get("reason", ""))

        # 审计联动关闭或用户无判定依据时，直接返回原始判定
        if not self._risk_link_enabled:
            return {
                "module": self.name,
                "success": True,
                "action": "allow" if allowed else "block",
                "risk_score": 0.0 if allowed else 1.0,
                "reason": reason,
                "modified_data": None,
                "details": {
                    "user_id": user_id,
                    "tool": tool,
                    "path": path,
                    "database": database,
                    "risk": {
                        "score": 0.0,
                        "block_count": 0,
                        "event_count": 0,
                        "probe_likely": False,
                    },
                    "escalated": False,
                    "penalty": 0,
                },
                "error": None,
            }

        # 读取审计实时风险评分（fail-open：异常时按原始判定返回）
        try:
            assessment = self._risk_monitor.assess(user_id, session_id)
        except Exception:
            assessment = {"risk_score": 0.0, "escalated": False}

        penalty = self._risk_policy.penalty_for(assessment)
        escalated_allowed = allowed
        if penalty > 0:
            # 用升级后的等级重新判定
            escalated = check_v4(
                user_id=user_id,
                path=path,
                tool=tool,
                database=database,
                penalty=penalty,
            )
            escalated_allowed = bool(escalated.get("allowed", False))

        decision = self._risk_policy.decide(
            allowed=allowed,
            escalated_allowed=escalated_allowed,
            reason=reason,
            assessment=assessment,
        )

        return {
            "module": self.name,
            "success": True,
            "action": decision["action"],
            "risk_score": decision["risk_score"],
            "reason": decision["reason"],
            "modified_data": None,
            "details": {
                "user_id": user_id,
                "tool": tool,
                "path": path,
                "database": database,
                "risk": {
                    "score": assessment.get("risk_score", 0.0),
                    "block_count": assessment.get("block_count", 0),
                    "event_count": assessment.get("event_count", 0),
                    "probe_likely": assessment.get("probe_likely", False),
                },
                "escalated": decision["escalated"],
                "penalty": decision["penalty"],
            },
            "error": None,
        }

    async def run(self, request: SecurityRequest | dict[str, Any]) -> ModuleResult:
        res = self.run_sync(request)
        if isinstance(res, dict):
            return ModuleResult(**res)
        return res
