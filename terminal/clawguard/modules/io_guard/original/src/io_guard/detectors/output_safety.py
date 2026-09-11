from __future__ import annotations

import re

from io_guard.detectors.base import Detector
from io_guard.normalization import normalize_text, safe_snippet
from io_guard.types import Evidence, GuardRequest, RiskType, SourceType


class OutputSafetyDetector(Detector):
    """Fine-grained output checks for the four non-disclosure categories."""

    name = "output_safety_detector"

    _SAFE_CONTEXT = re.compile(
        r"(?:我不能|无法协助|不会提供|应当拒绝|请勿|不要尝试|防止|"
        r"防范|检测|缓解|安全建议|危害|风险|违法|"
        r"I\s+(?:cannot|can't|won't)|do\s+not|avoid|prevent|detect|"
        r"mitigate|safety|illegal|harmful)",
        re.IGNORECASE,
    )
    _HARMFUL = re.compile(
        r"(?:都(?:是|该死|应该).{0,16}(?:垃圾|去死|杀掉|消灭)|"
        r"杀死他们|弄死他|去死吧|你这个(?:废物|垃圾)|"
        r"仇恨|种族清洗|鼓励自杀|值得自残|"
        r"kill\s+(?:them|him|her|yourself)|go\s+die|racial\s+cleansing|"
        r"hate\s+speech)",
        re.IGNORECASE,
    )
    _GUIDANCE_TOPIC = re.compile(
        r"(?:炸弹|炸药|爆炸物|枪支|武器|毒品|毒气|入侵账号|"
        r"窃取密码|绕过认证|自杀|自残|绑架|勒索|"
        r"bomb|explosive|weapon|drug|poison|hack\s+an?\s+account|"
        r"steal\s+(?:passwords?|credentials?)|suicide|self-harm|kidnap)",
        re.IGNORECASE,
    )
    _GUIDANCE_FORM = re.compile(
        r"(?:详细步骤|具体步骤|操作步骤|第一步|步骤\s*[1一]|教程|配方|"
        r"所需材料|执行以下|照着做|step[- ]?by[- ]?step|instructions?|"
        r"recipe|first,|step\s*1)",
        re.IGNORECASE,
    )
    _CODE_MARKER = re.compile(
        r"(?:```(?:python|powershell|bash|sh|javascript|typescript|cmd)?|"
        r"\b(?:import\s+os|import\s+subprocess|from\s+subprocess|"
        r"Invoke-Expression|IEX\s*\(|powershell\s+-enc|#!/bin/(?:ba)?sh)\b)",
        re.IGNORECASE,
    )
    _DANGEROUS_CODE = re.compile(
        r"(?:os\.system\s*\(|subprocess\.(?:run|Popen|call)\s*\(|"
        r"rm\s+-rf\s+[/~]|curl\s+[^\n|]+\|\s*(?:ba)?sh|"
        r"Invoke-WebRequest.{0,160}Invoke-Expression|"
        r"requests?\.post\s*\(.{0,120}(?:password|token|credential)|"
        r"CreateRemoteThread|WriteProcessMemory|keylogger|ransomware|"
        r"credential\s*(?:stealer|dump)|reverse\s+shell)",
        re.IGNORECASE | re.DOTALL,
    )

    def detect(self, request: GuardRequest) -> list[Evidence]:
        if request.source_type != SourceType.MODEL_OUTPUT:
            return []
        text = normalize_text(request.content)
        if not text:
            return []
        safe_context = bool(self._SAFE_CONTEXT.search(text))
        evidence: list[Evidence] = []

        if not safe_context:
            harmful = self._HARMFUL.search(text)
            if harmful:
                evidence.append(
                    self._evidence(
                        request,
                        text,
                        harmful,
                        RiskType.HARMFUL_OR_OFFENSIVE_CONTENT,
                        "harmful or offensive model output",
                        0.92,
                    )
                )

            topic = self._GUIDANCE_TOPIC.search(text)
            form = self._GUIDANCE_FORM.search(text)
            if topic and form:
                start = min(topic.start(), form.start())
                end = max(topic.end(), form.end())
                evidence.append(
                    Evidence(
                        detector=self.name,
                        risk_type=RiskType.HARMFUL_OR_ILLEGAL_GUIDANCE,
                        message="actionable harmful or illegal guidance",
                        score=0.96,
                        snippet=safe_snippet(text, start, end),
                        start=start,
                        end=end,
                        field_path="$.text",
                        step_id=self._step_id(request),
                    )
                )

        code_marker = self._CODE_MARKER.search(text)
        dangerous_code = self._DANGEROUS_CODE.search(text)
        if code_marker and dangerous_code and not safe_context:
            start = min(code_marker.start(), dangerous_code.start())
            end = max(code_marker.end(), dangerous_code.end())
            evidence.append(
                Evidence(
                    detector=self.name,
                    risk_type=RiskType.MALICIOUS_EXECUTABLE_GENERATION,
                    message="malicious executable code or script generated",
                    score=0.98,
                    snippet=safe_snippet(text, start, end),
                    start=start,
                    end=end,
                    field_path="$.text",
                    step_id=self._step_id(request),
                )
            )
        return evidence

    def _evidence(
        self,
        request: GuardRequest,
        text: str,
        match: re.Match[str],
        risk_type: RiskType,
        message: str,
        score: float,
    ) -> Evidence:
        return Evidence(
            detector=self.name,
            risk_type=risk_type,
            message=message,
            score=score,
            snippet=safe_snippet(text, match.start(), match.end()),
            start=match.start(),
            end=match.end(),
            field_path="$.text",
            step_id=self._step_id(request),
        )

    @staticmethod
    def _step_id(request: GuardRequest) -> str:
        return str(request.metadata.get("step_id") or "model-output")
