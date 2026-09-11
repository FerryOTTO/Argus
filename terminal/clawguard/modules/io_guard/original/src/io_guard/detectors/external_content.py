from __future__ import annotations

import re
from dataclasses import dataclass

from io_guard.types import Evidence, RiskType


@dataclass(frozen=True)
class BottleneckResult:
    content: str
    evidence: list[Evidence]
    removed_segments: int = 0
    truncated: bool = False

    @property
    def changed(self) -> bool:
        return self.removed_segments > 0 or self.truncated


class ExternalContentFilter:
    """Remove instruction-like segments while preserving factual content."""

    name = "external_content_filter"

    # Include the ASCII full stop so an injected English sentence cannot pull
    # the following benign Chinese sentence into the same removed segment.
    _segment_re = re.compile(r".+?(?:[。！？!?；;.\n]+|$)", re.DOTALL)
    _instruction_re = re.compile(
        r"(?:"
        r"\b(?:ignore|disregard|bypass|reveal|print|execute|run|call)\b"
        r".{0,80}\b(?:instruction|system prompt|policy|permission|tool|command)\b"
        r"|(?:忽略|无视|不理会|不要理会|忘掉|放弃|覆盖|撤销|作废|"
        r"绕过|泄露|输出|执行|调用).{0,40}"
        r"(?:指令|要求|系统提示|系统消息|策略|权限|工具|命令)"
        r"|(?:将|把).{0,30}(?:视为|当作).{0,12}"
        r"(?:系统|开发者|最高优先级)(?:指令|消息|命令)"
        r"|(?:你必须|必须执行|请执行以下|将以下内容视为系统指令)"
        r")",
        re.IGNORECASE | re.DOTALL,
    )

    def filter(
        self,
        content: str,
        rule_evidence: list[Evidence] | None = None,
    ) -> BottleneckResult:
        text = content or ""
        evidence_ranges = [
            (item.start, item.end)
            for item in (rule_evidence or [])
            if item.start is not None and item.end is not None
        ]
        kept: list[str] = []
        evidence: list[Evidence] = []
        removed_segments = 0

        for match in self._segment_re.finditer(text):
            segment = match.group(0)
            overlaps_rule = any(
                start < match.end() and end > match.start()
                for start, end in evidence_ranges
            )
            if overlaps_rule or self._instruction_re.search(segment):
                removed_segments += 1
                evidence.append(
                    Evidence(
                        detector=self.name,
                        risk_type=RiskType.INDIRECT_PROMPT_INJECTION,
                        message="instruction-like segment removed from external content",
                        score=0.72,
                        snippet=segment.strip()[:120],
                        start=match.start(),
                        end=match.end(),
                        field_path="$.content",
                        step_id="environment-observation",
                        remediable=True,
                    )
                )
                continue
            kept.append(segment)

        filtered = "".join(kept).strip()
        return BottleneckResult(
            content=filtered,
            evidence=evidence,
            removed_segments=removed_segments,
            truncated=False,
        )
