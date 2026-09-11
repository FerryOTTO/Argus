from __future__ import annotations

from collections.abc import Iterable

from io_guard.types import Decision, Evidence, GuardRequest, GuardResult, RiskType


class PolicyEngine:
    """Automatic policy engine: IO Guard never returns a review action."""

    def __init__(
        self,
        rewrite_threshold: float = 0.55,
        block_threshold: float = 0.85,
        policy_id: str = "io-guard-target-taxonomy-v1",
        sensitive_data_scopes: set[str] | None = None,
    ) -> None:
        self.rewrite_threshold = float(rewrite_threshold)
        self.block_threshold = float(block_threshold)
        self.policy_id = policy_id
        self.sensitive_data_scopes = sensitive_data_scopes or {
            "pii",
            "customer_support",
            "hr",
            "finance",
        }

    def decide(
        self,
        request: GuardRequest,
        evidence: Iterable[Evidence],
        sanitized_content: str | None = None,
    ) -> GuardResult:
        evidence_list = list(evidence)
        risk_score = max((item.score for item in evidence_list), default=0.0)
        risk_types = sorted(
            {item.risk_type for item in evidence_list},
            key=lambda item: item.value,
        )
        effective_content = (
            sanitized_content
            if sanitized_content is not None
            else request.content
        )
        decision = self._decision_for(
            request,
            evidence_list,
            risk_score,
            effective_content,
        )
        reason = self._reason_for(decision, risk_score, evidence_list)
        return GuardResult(
            decision=decision,
            risk_score=risk_score,
            risk_types=risk_types,
            sanitized_content=effective_content,
            evidence=evidence_list,
            reason=reason,
            trace_id=request.trace_id,
            policy_id=self.policy_id,
        )

    def _decision_for(
        self,
        request: GuardRequest,
        evidence: list[Evidence],
        risk_score: float,
        sanitized_content: str,
    ) -> Decision:
        if not evidence or risk_score < self.rewrite_threshold:
            return Decision.ALLOW

        risk_types = {item.risk_type for item in evidence}
        content_changed = sanitized_content != request.content

        if self._authorized_disclosure(request, evidence):
            return Decision.ALLOW

        if risk_types == {RiskType.INDIRECT_PROMPT_INJECTION}:
            return (
                Decision.REWRITE
                if content_changed and bool(sanitized_content.strip())
                else Decision.BLOCK
            )

        if any(
            item.risk_type
            == RiskType.UNAUTHORIZED_INFORMATION_DISCLOSURE
            and not item.remediable
            for item in evidence
        ):
            return Decision.BLOCK

        if content_changed and all(item.remediable for item in evidence):
            return Decision.REWRITE

        hard_block = {
            RiskType.MALICIOUS_USER_INSTRUCTION_OR_JAILBREAK,
            RiskType.DIRECT_PROMPT_INJECTION,
            RiskType.HARMFUL_OR_OFFENSIVE_CONTENT,
            RiskType.HARMFUL_OR_ILLEGAL_GUIDANCE,
            RiskType.MALICIOUS_EXECUTABLE_GENERATION,
        }
        if risk_types & hard_block:
            return Decision.BLOCK
        if risk_score >= self.block_threshold:
            return Decision.BLOCK
        return Decision.REWRITE if content_changed else Decision.BLOCK

    def _authorized_disclosure(
        self,
        request: GuardRequest,
        evidence: list[Evidence],
    ) -> bool:
        if not evidence or any(
            item.risk_type
            != RiskType.UNAUTHORIZED_INFORMATION_DISCLOSURE
            for item in evidence
        ):
            return False
        if any(not item.remediable for item in evidence):
            return False
        internal = (
            request.principal_type
            in {"employee", "privileged_employee", "service_account"}
            and request.target_audience == "internal"
            and request.channel_classification != "public"
        )
        return internal and bool(
            request.allowed_data_scopes & self.sensitive_data_scopes
        )

    @staticmethod
    def _reason_for(
        decision: Decision,
        risk_score: float,
        evidence: list[Evidence],
    ) -> str:
        if not evidence:
            return "no target risk detected"
        top = max(evidence, key=lambda item: item.score)
        return (
            f"{decision.value}: {top.risk_type.value}: {top.message} "
            f"(score={risk_score:.2f})"
        )
