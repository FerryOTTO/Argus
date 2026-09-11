from __future__ import annotations

import re

from io_guard.config import CLASSIFICATION_LEVELS, OUTPUT_LEAKAGE_PATTERNS
from io_guard.detectors.base import Detector
from io_guard.normalization import normalize_text, safe_snippet
from io_guard.types import Evidence, GuardRequest, RiskType


class OutputLeakageDetector(Detector):
    name = "output_leakage_detector"

    def __init__(self) -> None:
        self._patterns = [
            (re.compile(pattern, re.IGNORECASE), message, score, replacement)
            for pattern, message, score, replacement in OUTPUT_LEAKAGE_PATTERNS
        ]
        labels = "|".join(
            re.escape(label)
            for label in sorted(
                CLASSIFICATION_LEVELS,
                key=len,
                reverse=True,
            )
        )
        self._classification_re = re.compile(labels, re.IGNORECASE)
        self._classification_prefix_re = re.compile(
            r"(?:"
            r"密级|保密等级|安全等级|信息等级|分级标签|分类标签|"
            r"标记(?:为)?|标注(?:为)?|列为|归类为|"
            r"该(?:内容|文件|文档|资料|报告)\s*(?:为|属于)|"
            r"classification|security\s+level|sensitivity|"
            r"classified\s+as|marked\s+as|labelled\s+as"
            r")\s*[:：=]?\s*$",
            re.IGNORECASE,
        )
        self._classification_suffix_re = re.compile(
            r"^\s*(?:"
            r"级|文件|文档|资料|材料|报告|信息|数据|项目|计划|"
            r"档案|邮件|消息|附件|备忘录|仅限|禁止外传|不得外泄|"
            r"classification|classified|document|file|data|report|"
            r"material|memo|message|email|attachment"
            r")",
            re.IGNORECASE,
        )
        self._classification_delimiter_re = re.compile(
            r"^\s*(?:$|[，。；、,.;:：)）\]】])"
        )

    def detect(self, request: GuardRequest) -> list[Evidence]:
        text = normalize_text(request.content)
        evidence: list[Evidence] = []

        for pattern, message, score, _replacement in self._patterns:
            for match in pattern.finditer(text):
                evidence.append(
                    Evidence(
                        detector=self.name,
                        risk_type=(
                            RiskType.UNAUTHORIZED_INFORMATION_DISCLOSURE
                        ),
                        message=message,
                        score=score,
                        snippet=safe_snippet(text, match.start(), match.end()),
                        start=match.start(),
                        end=match.end(),
                        field_path="$.text",
                        step_id=str(
                            request.metadata.get("step_id") or "model-output"
                        ),
                        remediable=message
                        not in {
                            "API key",
                            "JWT-like token",
                            "system prompt leakage",
                            "系统提示泄露",
                        },
                    )
                )

        evidence.extend(self._detect_classification_leakage(text, request.role_level))
        return evidence

    def redact(self, content: str) -> str:
        redacted = content
        for pattern, _message, _score, replacement in self._patterns:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    def _detect_classification_leakage(
        self, text: str, role_level: int
    ) -> list[Evidence]:
        evidence: list[Evidence] = []
        for match in self._classification_re.finditer(text):
            if not self._has_classification_context(text, match):
                continue
            label = match.group(0)
            required_level = CLASSIFICATION_LEVELS.get(label.lower(), None)
            if required_level is None:
                required_level = CLASSIFICATION_LEVELS.get(label, 0)
            if required_level > role_level:
                evidence.append(
                    Evidence(
                        detector=self.name,
                        risk_type=(
                            RiskType.UNAUTHORIZED_INFORMATION_DISCLOSURE
                        ),
                        message=f"classification '{label}' requires role level {required_level}",
                        score=0.90,
                        snippet=safe_snippet(text, match.start(), match.end()),
                        start=match.start(),
                        end=match.end(),
                        field_path="$.text",
                        step_id=str(
                            request.metadata.get("step_id") or "model-output"
                        ),
                    )
                )
        return evidence

    def _has_classification_context(
        self,
        text: str,
        match: re.Match[str],
    ) -> bool:
        """Distinguish data-classification labels from ordinary words.

        Chinese words such as ``内部`` and ``秘密`` are common in benign prose
        (for example ``内部结构`` and ``秘密花园``). A label is actionable only
        when nearby wording marks it as a classification, or when it directly
        modifies a document/data noun.
        """

        before = text[max(0, match.start() - 48) : match.start()]
        after = text[match.end() : match.end() + 32]
        prefix_context = self._classification_prefix_re.search(before)
        suffix_context = self._classification_suffix_re.match(after)
        return bool(
            suffix_context
            or (
                prefix_context
                and self._classification_delimiter_re.match(after)
            )
        )
