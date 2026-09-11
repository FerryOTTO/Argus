from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from io_guard.audit import AuditLogger
from io_guard.detectors.external_content import ExternalContentFilter
from io_guard.detectors.input_safety import MaliciousUserInstructionDetector
from io_guard.detectors.output_leakage import OutputLeakageDetector
from io_guard.detectors.output_safety import OutputSafetyDetector
from io_guard.detectors.prompt_injection import PromptInjectionDetector
from io_guard.detectors.reliability import ReliabilityDetector
from io_guard.detectors.semantic import SemanticDetector
from io_guard.normalization import normalize_text
from io_guard.policy import PolicyEngine
from io_guard.preprocessors.decomposition import (
    DecompositionResult,
    DetectionView,
    QuestionDecomposer,
)
from io_guard.trajectory import TrajectoryStore
from io_guard.types import Evidence, GuardRequest, GuardResult, SourceType


class IOGuard:
    """Three-stage guard restricted to the nine requested risk categories."""

    def __init__(
        self,
        policy_engine: PolicyEngine | None = None,
        audit_logger: AuditLogger | None = None,
        prompt_detector: PromptInjectionDetector | None = None,
        input_detector: MaliciousUserInstructionDetector | None = None,
        output_detector: OutputLeakageDetector | None = None,
        output_safety_detector: OutputSafetyDetector | None = None,
        reliability_detector: ReliabilityDetector | None = None,
        external_content_filter: ExternalContentFilter | None = None,
        semantic_detector: SemanticDetector | None = None,
        question_decomposer: QuestionDecomposer | None = None,
        trajectory_store: TrajectoryStore | None = None,
    ) -> None:
        self.policy_engine = policy_engine or PolicyEngine()
        self.audit_logger = audit_logger
        self.prompt_detector = prompt_detector or PromptInjectionDetector()
        self.input_detector = (
            input_detector or MaliciousUserInstructionDetector()
        )
        self.output_detector = output_detector or OutputLeakageDetector()
        self.output_safety_detector = (
            output_safety_detector or OutputSafetyDetector()
        )
        self.reliability_detector = (
            reliability_detector or ReliabilityDetector()
        )
        self.external_content_filter = (
            external_content_filter or ExternalContentFilter()
        )
        self.semantic_detector = semantic_detector or SemanticDetector()
        self.question_decomposer = question_decomposer or QuestionDecomposer()
        self.trajectory_store = trajectory_store or TrajectoryStore()

    @classmethod
    def from_policy_file(
        cls,
        path: Path | str,
        *,
        audit_logger: AuditLogger | None = None,
        semantic_detector: SemanticDetector | None = None,
    ) -> "IOGuard":
        policy_path = Path(path)
        with policy_path.open(encoding="utf-8") as file:
            config = json.load(file)

        thresholds = config.get("decision_thresholds", {})
        semantic_config = config.get("semantic_detection", {})
        decomposition = config.get("question_decomposition", {})
        disclosure = config.get("disclosure", {})
        audit = config.get("audit", {})
        if audit_logger is not None:
            audit_logger.configure(
                content_storage=str(
                    audit.get("content_storage", "sanitized")
                ),
                max_content_chars=int(audit.get("max_content_chars", 2000)),
            )

        configured_semantic = semantic_detector
        if configured_semantic is None and semantic_config.get("enabled", False):
            configured_semantic = SemanticDetector.from_config(
                semantic_config,
                base_dir=policy_path.parent,
            )

        return cls(
            policy_engine=PolicyEngine(
                rewrite_threshold=float(
                    thresholds.get("rewrite", thresholds.get("review", 0.55))
                ),
                block_threshold=float(thresholds.get("block", 0.85)),
                policy_id=str(config.get("policy_id", policy_path.stem)),
                sensitive_data_scopes=set(
                    disclosure.get(
                        "authorized_scopes",
                        ["pii", "customer_support", "hr", "finance"],
                    )
                ),
            ),
            audit_logger=audit_logger,
            semantic_detector=configured_semantic,
            question_decomposer=QuestionDecomposer(
                enabled=bool(decomposition.get("enabled", True)),
                min_chars=int(decomposition.get("min_chars", 60)),
                max_parts=int(decomposition.get("max_parts", 8)),
            ),
        )

    def pre_check(self, request: GuardRequest) -> GuardResult:
        started_at = perf_counter()
        normalized_request = self._normalized_request(request)
        decomposition = self.question_decomposer.decompose(
            normalized_request.content
        )
        evidence: list[Evidence] = []
        evidence.extend(self.prompt_detector.detect(request))
        evidence.extend(self.input_detector.detect(normalized_request))
        evidence.extend(self.semantic_detector.detect(normalized_request))
        evidence.extend(
            self._detect_decomposed_views(
                normalized_request,
                decomposition,
                include_input=True,
            )
        )
        result = self.policy_engine.decide(normalized_request, evidence)
        return self._finalize(
            "prompt_guard",
            normalized_request,
            result,
            decomposition,
            started_at,
        )

    def check_retrieval_content(self, request: GuardRequest) -> GuardResult:
        started_at = perf_counter()
        raw_request = replace(
            request,
            source_type=(
                request.source_type
                if request.source_type
                in {
                    SourceType.RETRIEVAL_CHUNK,
                    SourceType.TOOL_RESULT,
                    SourceType.MEMORY,
                }
                else SourceType.RETRIEVAL_CHUNK
            ),
        )
        normalized_request = self._normalized_request(raw_request)
        decomposition = self.question_decomposer.decompose(
            normalized_request.content
        )
        rule_evidence = self.prompt_detector.detect(raw_request)
        rule_evidence.extend(
            self._detect_decomposed_views(
                normalized_request,
                decomposition,
                include_semantic=False,
            )
        )
        filtered = self.external_content_filter.filter(
            normalized_request.content,
            rule_evidence,
        )
        filtered_request = replace(
            normalized_request,
            content=filtered.content,
        )
        semantic_evidence = self.semantic_detector.detect(filtered_request)
        reliability_evidence = self.reliability_detector.detect(
            normalized_request
        )
        sanitized_content = filtered.content
        if reliability_evidence and all(
            item.remediable for item in reliability_evidence
        ):
            sanitized_content = self.reliability_detector.rewrite(
                normalized_request,
                sanitized_content,
            )
        evidence = (
            rule_evidence
            + filtered.evidence
            + semantic_evidence
            + reliability_evidence
        )
        result = self.policy_engine.decide(
            normalized_request,
            evidence,
            sanitized_content,
        )
        return self._finalize(
            "knowledge",
            normalized_request,
            result,
            decomposition,
            started_at,
        )

    def post_check(self, request: GuardRequest) -> GuardResult:
        started_at = perf_counter()
        output_request = replace(
            self._normalized_request(request),
            source_type=SourceType.MODEL_OUTPUT,
        )
        decomposition = self.question_decomposer.decompose(
            output_request.content
        )
        disclosure_evidence = self.output_detector.detect(output_request)
        redacted = self.output_detector.redact(output_request.content)
        safety_evidence = self.output_safety_detector.detect(output_request)
        reliability_evidence = self.reliability_detector.detect(output_request)
        semantic_request = replace(output_request, content=redacted)
        semantic_evidence = self.semantic_detector.detect(semantic_request)
        sanitized_content = redacted
        if reliability_evidence and all(
            item.remediable for item in reliability_evidence
        ):
            sanitized_content = self.reliability_detector.rewrite(
                output_request,
                sanitized_content,
            )
        evidence = (
            disclosure_evidence
            + safety_evidence
            + reliability_evidence
            + semantic_evidence
        )
        result = self.policy_engine.decide(
            output_request,
            evidence,
            sanitized_content,
        )
        return self._finalize(
            "output_guard",
            output_request,
            result,
            decomposition,
            started_at,
        )

    def _normalized_request(self, request: GuardRequest) -> GuardRequest:
        return replace(request, content=normalize_text(request.content))

    def _detect_decomposed_views(
        self,
        request: GuardRequest,
        decomposition: DecompositionResult,
        *,
        include_input: bool = False,
        include_rules: bool = True,
        include_semantic: bool = True,
    ) -> list[Evidence]:
        evidence: list[Evidence] = []
        for view in decomposition.parts:
            view_request = replace(request, content=view.text)
            part_evidence: list[Evidence] = []
            if include_rules:
                part_evidence.extend(self.prompt_detector.detect(view_request))
            if include_input:
                part_evidence.extend(self.input_detector.detect(view_request))
            if include_semantic and view.kind != "task":
                part_evidence.extend(self.semantic_detector.detect(view_request))
            evidence.extend(
                self._translate_evidence(item, view)
                for item in part_evidence
            )
        return evidence

    @staticmethod
    def _translate_evidence(
        evidence: Evidence,
        view: DetectionView,
    ) -> Evidence:
        return replace(
            evidence,
            message=(
                f"{evidence.message}; detection_view={view.view_id}; "
                f"view_kind={view.kind}"
            ),
            start=(
                view.start + evidence.start
                if evidence.start is not None
                else view.start
            ),
            end=(
                view.start + evidence.end
                if evidence.end is not None
                else view.end
            ),
        )

    def _finalize(
        self,
        stage: str,
        request: GuardRequest,
        result: GuardResult,
        decomposition: DecompositionResult,
        started_at: float,
    ) -> GuardResult:
        result = replace(
            result,
            processing_metadata={
                **result.processing_metadata,
                "decomposition": {
                    "applied": decomposition.applied,
                    "part_count": len(decomposition.parts),
                    "strategy": decomposition.strategy,
                    "part_types": [part.kind for part in decomposition.parts],
                },
                "latency_ms": round(
                    (perf_counter() - started_at) * 1000,
                    3,
                ),
            },
        )
        trajectory = self.trajectory_store.append(request, result)
        result = replace(
            result,
            processing_metadata={
                **result.processing_metadata,
                "trajectory": trajectory,
            },
        )
        if self.audit_logger is not None:
            self.audit_logger.log(stage, request, result)
        return result
