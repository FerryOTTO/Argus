from __future__ import annotations

import base64
import binascii
import re

from io_guard.config import PROMPT_INJECTION_PATTERNS
from io_guard.detectors.base import Detector
from io_guard.normalization import normalize_text, safe_snippet
from io_guard.types import Evidence, GuardRequest, RiskType, SourceType


class PromptInjectionDetector(Detector):
    name = "prompt_injection_detector"

    def __init__(self) -> None:
        self._patterns = [
            (re.compile(pattern, re.IGNORECASE), message, score)
            for pattern, message, score in PROMPT_INJECTION_PATTERNS
        ]
        self._base64_re = re.compile(r"\b[A-Za-z0-9+/]{24,}={0,2}\b")
        # ZWJ/ZWNJ are valid emoji/script shaping characters. Treat only
        # zero-width space/directional marks/BOM as possible obfuscation.
        self._zero_width_re = re.compile(r"[\u200b\u200e\u200f\ufeff]")

    def detect(self, request: GuardRequest) -> list[Evidence]:
        text = normalize_text(request.content)
        evidence: list[Evidence] = []

        for pattern, message, score in self._patterns:
            for match in pattern.finditer(text):
                evidence.append(
                    Evidence(
                        detector=self.name,
                        risk_type=self._risk_type_for(message, request.source_type),
                        message=message,
                        score=self._score_for_source(score, request.source_type),
                        snippet=safe_snippet(text, match.start(), match.end()),
                        start=match.start(),
                        end=match.end(),
                        field_path=self._field_path(request.source_type),
                        step_id=self._step_id(request),
                    )
                )

        zero_width_matches = list(
            self._zero_width_re.finditer(request.content)
        )
        normalized_without_zero_width = normalize_text(request.content)
        zero_width_splits_risk_phrase = (
            bool(zero_width_matches)
            and any(
                pattern.search(normalized_without_zero_width)
                for pattern, _message, _score in self._patterns
            )
        )
        suspicious_zero_width = (
            len(zero_width_matches) >= 2
            or zero_width_splits_risk_phrase
        )
        if suspicious_zero_width:
            evidence.append(
                Evidence(
                    detector=self.name,
                    risk_type=self._injection_type(request.source_type),
                    message="zero-width character obfuscation",
                    score=0.62,
                    snippet="[zero-width characters removed during normalization]",
                    field_path=self._field_path(request.source_type),
                    step_id=self._step_id(request),
                )
            )

        evidence.extend(self._detect_base64_payloads(text, request))
        return evidence

    def _detect_base64_payloads(
        self,
        text: str,
        request: GuardRequest,
    ) -> list[Evidence]:
        evidence: list[Evidence] = []
        for match in self._base64_re.finditer(text):
            token = match.group(0)
            try:
                decoded = base64.b64decode(token + "==", validate=False)
                decoded_text = decoded.decode("utf-8", errors="ignore")
            except (binascii.Error, ValueError):
                continue
            normalized = normalize_text(decoded_text)
            if not normalized:
                continue
            for pattern, message, score in self._patterns:
                if pattern.search(normalized):
                    evidence.append(
                        Evidence(
                            detector=self.name,
                            risk_type=self._injection_type(request.source_type),
                            message=f"base64 encoded prompt injection: {message}",
                            score=max(score, 0.88),
                            snippet=safe_snippet(token, 0, len(token)),
                            start=match.start(),
                            end=match.end(),
                            field_path=self._field_path(request.source_type),
                            step_id=self._step_id(request),
                        )
                    )
                    break
        return evidence

    def _risk_type_for(
        self,
        message: str,
        source_type: SourceType,
    ) -> RiskType:
        if source_type in {
            SourceType.RETRIEVAL_CHUNK,
            SourceType.TOOL_RESULT,
            SourceType.MEMORY,
        }:
            return RiskType.INDIRECT_PROMPT_INJECTION
        if "jailbreak" in message.lower() or "越狱" in message:
            return RiskType.MALICIOUS_USER_INSTRUCTION_OR_JAILBREAK
        return RiskType.DIRECT_PROMPT_INJECTION

    @staticmethod
    def _injection_type(source_type: SourceType) -> RiskType:
        if source_type in {
            SourceType.RETRIEVAL_CHUNK,
            SourceType.TOOL_RESULT,
            SourceType.MEMORY,
        }:
            return RiskType.INDIRECT_PROMPT_INJECTION
        return RiskType.DIRECT_PROMPT_INJECTION

    @staticmethod
    def _field_path(source_type: SourceType) -> str:
        return "$.text" if source_type == SourceType.USER_PROMPT else "$.content"

    @staticmethod
    def _step_id(request: GuardRequest) -> str:
        default = (
            "user-input"
            if request.source_type == SourceType.USER_PROMPT
            else "environment-observation"
        )
        return str(request.metadata.get("step_id") or default)

    def _score_for_source(self, base_score: float, source_type: SourceType) -> float:
        if source_type in {
            SourceType.RETRIEVAL_CHUNK,
            SourceType.TOOL_RESULT,
            SourceType.MEMORY,
        }:
            return min(base_score + 0.04, 0.99)
        return base_score
