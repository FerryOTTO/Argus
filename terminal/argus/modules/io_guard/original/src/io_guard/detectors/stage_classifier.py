from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from io_guard.structured_content import extract_string_leaves
from io_guard.types import SourceType


class StageAwareCharClassifier:
    """Source-aware character n-gram safety heads trained for IO Guard v3."""

    _SOURCE_TO_HEAD = {
        SourceType.USER_PROMPT: "input",
        SourceType.MODEL_OUTPUT: "output",
        SourceType.RETRIEVAL_CHUNK: "content",
        SourceType.TOOL_RESULT: "content",
        SourceType.MEMORY: "content",
    }
    _SOURCE_MARKERS = {
        SourceType.USER_PROMPT: "[输入]",
        SourceType.MODEL_OUTPUT: "[输出]",
        SourceType.RETRIEVAL_CHUNK: "[检索内容]",
        SourceType.TOOL_RESULT: "[工具结果]",
        SourceType.MEMORY: "[工具结果]",
    }
    _HEAD_LABELS = {
        "input": "direct_prompt_injection",
        "output": "harmful_or_offensive_content",
        "content": "indirect_prompt_injection",
    }

    def __init__(
        self,
        *,
        model_dir: Path | str,
        policy_score: float = 0.90,
        threshold_overrides: dict[str, float] | None = None,
    ) -> None:
        try:
            import joblib
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "stage_char_classifier requires joblib; install the IO Guard "
                "package dependencies"
            ) from exc

        self.model_dir = Path(model_dir)
        self.policy_score = float(policy_score)
        self._lock = threading.Lock()
        if not 0.0 <= self.policy_score <= 1.0:
            raise ValueError("policy_score must be between 0 and 1")
        overrides = threshold_overrides or {}
        self.heads: dict[str, dict[str, Any]] = {}
        for head in ("input", "output", "content"):
            path = self.model_dir / f"{head}_char.joblib"
            if not path.is_file():
                raise FileNotFoundError(f"missing stage classifier head: {path}")
            payload = joblib.load(path)
            threshold = float(
                overrides.get(head, payload["unsafe_threshold"])
            )
            if not 0.0 <= threshold <= 1.0:
                raise ValueError(f"{head} threshold must be between 0 and 1")
            self.heads[head] = {
                **payload,
                "path": str(path),
                "unsafe_threshold": threshold,
            }

    def __call__(
        self,
        text: str,
        source_type: SourceType,
    ) -> tuple[bool, float, str]:
        head_name = self._SOURCE_TO_HEAD[source_type]
        head = self.heads[head_name]
        values = self._detection_values(text, source_type)
        marker = self._SOURCE_MARKERS[source_type]
        model_inputs = [f"{marker} {value}" for value in values]
        with self._lock:
            features = head["vectorizer"].transform(model_inputs)
            scores = head["classifier"].predict_proba(features)[:, 1]
        best_index = int(scores.argmax())
        probability = float(scores[best_index])
        threshold = float(head["unsafe_threshold"])
        unsafe = probability >= threshold
        score = (
            self._calibrated_policy_score(probability, threshold)
            if unsafe
            else probability
        )
        label = (
            f"{self._HEAD_LABELS[head_name]}; confidence={probability:.4f}; "
            f"head={head_name}; threshold={threshold:.4f}; "
            f"field={best_index + 1}/{len(values)}"
        )
        return unsafe, score, label

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "backend": "stage_char_classifier",
            "model_dir": str(self.model_dir),
            "heads": {
                name: {
                    "path": value["path"],
                    "unsafe_threshold": value["unsafe_threshold"],
                }
                for name, value in self.heads.items()
            },
            "structured_tool_fields": True,
        }

    @staticmethod
    def _detection_values(text: str, source_type: SourceType) -> list[str]:
        if source_type in {
            SourceType.TOOL_RESULT,
            SourceType.RETRIEVAL_CHUNK,
            SourceType.MEMORY,
        }:
            values = extract_string_leaves(text)
            if values:
                return values
        return [text]

    def _calibrated_policy_score(
        self,
        probability: float,
        threshold: float,
    ) -> float:
        if threshold >= 1.0:
            return self.policy_score
        margin = max(0.0, probability - threshold)
        scaled = margin / (1.0 - threshold)
        return min(
            1.0,
            self.policy_score + scaled * (1.0 - self.policy_score),
        )
