from __future__ import annotations

from enum import Enum


class TaxonomyDimension(str, Enum):
    """The two AgentDoG dimensions intentionally retained by IO Guard."""

    RISK_SOURCE = "risk_source"
    FAILURE_MODE = "failure_mode"


class RiskCategory(str, Enum):
    """The complete and deliberately narrow IO Guard risk taxonomy."""

    MALICIOUS_USER_INSTRUCTION_OR_JAILBREAK = (
        "malicious_user_instruction_or_jailbreak"
    )
    DIRECT_PROMPT_INJECTION = "direct_prompt_injection"
    INDIRECT_PROMPT_INJECTION = "indirect_prompt_injection"
    UNRELIABLE_OR_MISINFORMATION = "unreliable_or_misinformation"
    HARMFUL_OR_OFFENSIVE_CONTENT = "harmful_or_offensive_content"
    HARMFUL_OR_ILLEGAL_GUIDANCE = "harmful_or_illegal_guidance"
    MALICIOUS_EXECUTABLE_GENERATION = "malicious_executable_generation"
    UNAUTHORIZED_INFORMATION_DISCLOSURE = (
        "unauthorized_information_disclosure"
    )
    INACCURATE_MISLEADING_OR_UNVERIFIED_INFORMATION = (
        "inaccurate_misleading_or_unverified_information"
    )

    @property
    def dimension(self) -> TaxonomyDimension:
        if self in {
            RiskCategory.MALICIOUS_USER_INSTRUCTION_OR_JAILBREAK,
            RiskCategory.DIRECT_PROMPT_INJECTION,
            RiskCategory.INDIRECT_PROMPT_INJECTION,
            RiskCategory.UNRELIABLE_OR_MISINFORMATION,
        }:
            return TaxonomyDimension.RISK_SOURCE
        return TaxonomyDimension.FAILURE_MODE


TARGET_CATEGORIES = tuple(RiskCategory)
