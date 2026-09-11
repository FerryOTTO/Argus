from __future__ import annotations

from io_guard.detectors.base import Detector
from io_guard.types import Evidence, GuardRequest, RiskType, SourceType


class ReliabilityDetector(Detector):
    """Evaluate explicit provenance signals without pretending to fact-check."""

    name = "reliability_detector"
    _BAD_STATUSES = {
        "false",
        "contradicted",
        "misinformation",
        "fabricated",
        "invalid",
    }
    _UNCERTAIN_STATUSES = {
        "unverified",
        "unknown",
        "unsupported",
        "incomplete",
        "noisy",
        "stale",
        "outdated",
    }

    def detect(self, request: GuardRequest) -> list[Evidence]:
        if request.source_type == SourceType.USER_PROMPT:
            return []
        metadata = request.metadata
        status = str(
            metadata.get("verification_status")
            or metadata.get("reliability_status")
            or ""
        ).strip().casefold()
        trust_level = str(metadata.get("trust_level") or "").strip().casefold()
        citations = metadata.get("citations")
        requires_verification = bool(metadata.get("requires_verification"))
        high_stakes = bool(metadata.get("high_stakes"))

        score = 0.0
        message = ""
        if status in self._BAD_STATUSES:
            score = 0.96
            message = f"source or claim is {status}"
        elif trust_level == "untrusted":
            score = 0.90
            message = "source is explicitly marked untrusted"
        elif status in self._UNCERTAIN_STATUSES:
            score = 0.88 if high_stakes else 0.70
            message = f"source or claim is {status}"
        elif requires_verification and not citations:
            score = 0.88 if high_stakes else 0.68
            message = "required supporting citations are missing"
        if score <= 0.0:
            return []

        risk_type = (
            RiskType.INACCURATE_MISLEADING_OR_UNVERIFIED_INFORMATION
            if request.source_type == SourceType.MODEL_OUTPUT
            else RiskType.UNRELIABLE_OR_MISINFORMATION
        )
        field_path = "$.text" if request.source_type == SourceType.MODEL_OUTPUT else "$.content"
        return [
            Evidence(
                detector=self.name,
                risk_type=risk_type,
                message=message,
                score=score,
                snippet="[provenance metadata]",
                field_path=field_path,
                step_id=str(
                    metadata.get("step_id")
                    or (
                        "model-output"
                        if request.source_type == SourceType.MODEL_OUTPUT
                        else "environment-observation"
                    )
                ),
                remediable=not high_stakes and score < 0.85,
            )
        ]

    @staticmethod
    def rewrite(request: GuardRequest, content: str) -> str:
        if request.source_type == SourceType.MODEL_OUTPUT:
            return "该结论缺少足够的可靠依据，暂不提供未经核实的信息。"
        marker = "[来源状态：未经验证，仅可作为线索，不得作为已确认事实]\n"
        return marker + content
