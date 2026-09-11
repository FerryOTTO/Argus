"""访问控制 ↔ 审计联动：接收审计实时风险评分，动态升级防线与二次审批。

设计原则：
  - 访问控制核心算法（auth_gateway）不改，联动逻辑独立成模块；
  - 审计事件可读写，本模块只读：从 AuditStore 读取用户近期事件计算实时风险；
  - 联动失败时 fail-open，按原始判定返回，不阻断正常流程。

两条联动能力：
  1. 动态升级防线：检测到用户频发试探（时间窗内多次被拦截），临时提升
     资源所需等级（penalty），让原本"刚好够"的请求也被拦截；
  2. 二次审批：防线升级后原本 allow 的请求若变为 deny，不直接 block，
     而是返回 human_review，交由 OpenClaw 侧人工审批。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from argus.modules.audit.original import AuditStore
from argus.modules.audit.original.storage import parse_timestamp

# 默认配置（可用环境变量覆盖）
DEFAULT_WINDOW_SECONDS = int(os.getenv("ARGUS_RISK_WINDOW_SECONDS", "300"))
DEFAULT_RISK_THRESHOLD = float(os.getenv("ARGUS_RISK_THRESHOLD", "0.6"))
DEFAULT_PROBE_BLOCK_COUNT = int(os.getenv("ARGUS_RISK_PROBE_BLOCK_COUNT", "3"))
DEFAULT_ESCALATION_THRESHOLD = float(os.getenv("ARGUS_RISK_ESCALATION_THRESHOLD", "0.5"))


class AuditRiskMonitor:
    """从审计事件中计算用户实时风险评分，识别频发试探行为。

    可注入自定义 store（测试用临时文件），默认使用全局 AuditStore。
    """

    def __init__(
        self,
        store: AuditStore | Callable[[], AuditStore] | None = None,
        *,
        window_seconds: int | None = None,
        risk_threshold: float | None = None,
        probe_block_count: int | None = None,
    ) -> None:
        self._store = store
        self.window_seconds = (
            window_seconds if window_seconds is not None else DEFAULT_WINDOW_SECONDS
        )
        self.risk_threshold = (
            risk_threshold if risk_threshold is not None else DEFAULT_RISK_THRESHOLD
        )
        self.probe_block_count = (
            probe_block_count
            if probe_block_count is not None
            else DEFAULT_PROBE_BLOCK_COUNT
        )

    def _resolve_store(self) -> AuditStore:
        if self._store is None:
            return AuditStore()
        if isinstance(self._store, AuditStore):
            return self._store
        return self._store()

    def assess(self, user_id: str, session_id: str = "") -> dict[str, Any]:
        """返回该用户在时间窗内的实时风险评估。"""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.window_seconds)

        recent: list[dict[str, Any]] = []
        for event in self._resolve_store().load():
            if event.get("user_id") != user_id:
                continue
            if session_id and event.get("session_id") != session_id:
                continue
            try:
                ts = parse_timestamp(event["timestamp"])
            except Exception:
                continue
            if ts >= cutoff:
                recent.append(event)

        block_count = sum(1 for e in recent if e.get("action") == "block")
        high_risk_count = sum(
            1 for e in recent if e.get("risk_score", 0.0) >= self.risk_threshold
        )
        scores = [e.get("risk_score", 0.0) for e in recent]
        max_risk = max(scores) if scores else 0.0
        avg_risk = sum(scores) / len(scores) if scores else 0.0

        # 综合风险：平均风险 + 拦截密度 + 高风险事件密度（均归一化到 0-1）
        probe_den = max(self.probe_block_count, 1)
        risk_score = 0.0
        if scores:
            risk_score = min(
                1.0,
                0.4 * avg_risk
                + 0.3 * (block_count / probe_den)
                + 0.3 * (high_risk_count / probe_den),
            )

        return {
            "user_id": user_id,
            "session_id": session_id,
            "window_seconds": self.window_seconds,
            "event_count": len(recent),
            "block_count": block_count,
            "high_risk_count": high_risk_count,
            "max_risk": round(max_risk, 4),
            "avg_risk": round(avg_risk, 4),
            "risk_score": round(risk_score, 4),
            "probe_likely": block_count >= self.probe_block_count,
        }


class DynamicLinePolicy:
    """基于风险评估动态升级防线，并决定是否二次审批。

    决策流程（由调用方配合执行）：
      1. penalty_for(assessment) 计算防线升级等级；
      2. 调用方用该 penalty 重新执行访问控制判定 escalated_allowed；
      3. decide() 综合原始判定、升级后判定与风险，输出最终动作。

    最终动作语义：
      - 原始拦截 → block（本来就拦，最高防线）
      - 升级后仍放行 → allow（防线已收紧但依然够格）
      - 升级后本应拦截 → human_review（二次审批，给人工确认机会）
    """

    def __init__(
        self,
        *,
        escalation_threshold: float | None = None,
        review_action: str = "human_review",
        max_penalty: int = 2,
    ) -> None:
        self.escalation_threshold = (
            escalation_threshold
            if escalation_threshold is not None
            else DEFAULT_ESCALATION_THRESHOLD
        )
        self.review_action = review_action
        self.max_penalty = max_penalty

    def penalty_for(self, assessment: dict[str, Any]) -> int:
        """根据风险评分计算防线升级的 penalty 等级。"""
        import math

        risk = assessment.get("risk_score", 0.0)
        if risk < self.escalation_threshold:
            return 0
        # 越接近 1 惩罚越重（向上取整），但不超过 max_penalty
        span = max(1.0 - self.escalation_threshold, 1e-9)
        scaled = math.ceil((risk - self.escalation_threshold) / span * self.max_penalty)
        return min(max(scaled, 1), self.max_penalty)

    def decide(
        self,
        allowed: bool,
        escalated_allowed: bool,
        reason: str,
        assessment: dict[str, Any],
    ) -> dict[str, Any]:
        """把原始判定 + 防线升级后判定合并为最终动作。

        Args:
            allowed: 原始判定（penalty=0）是否放行
            escalated_allowed: 防线升级后（penalty>0）是否放行
            reason: 原始判定原因
            assessment: AuditRiskMonitor.assess() 的返回

        Returns:
            {action, reason, risk_score, escalated, penalty}
        """
        risk = assessment.get("risk_score", 0.0)
        penalty = self.penalty_for(assessment)

        # 防线不升级：维持原判定
        if penalty == 0:
            return {
                "action": "allow" if allowed else "block",
                "reason": reason,
                "risk_score": 0.0 if allowed else 1.0,
                "escalated": False,
                "penalty": 0,
            }

        if not allowed:
            # 原本就拦截：保持 block（最高防线），并标注升级原因
            return {
                "action": "block",
                "reason": (
                    f"{reason}; risk_escalated(risk={risk:.2f}, "
                    f"penalty={penalty})"
                ),
                "risk_score": 1.0,
                "escalated": True,
                "penalty": penalty,
            }

        if escalated_allowed:
            # 防线升级后仍放行：允许，但标注风险与收紧后的等级
            return {
                "action": "allow",
                "reason": (
                    f"{reason}; risk_escalated(risk={risk:.2f}, "
                    f"penalty={penalty}) 升级后仍允许"
                ),
                "risk_score": risk,
                "escalated": True,
                "penalty": penalty,
            }

        # 升级后本应拦截 → 二次审批
        return {
            "action": self.review_action,
            "reason": (
                f"risk_escalated: 用户风险评分 {risk:.2f} ≥ "
                f"{self.escalation_threshold:.2f}，防线升级(penalty={penalty})后"
                f"本应拦截，转人工审批(block_count={assessment.get('block_count', 0)})"
            ),
            "risk_score": risk,
            "escalated": True,
            "penalty": penalty,
        }
