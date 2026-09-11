from __future__ import annotations

from pathlib import Path

from io_guard.detectors.stage_classifier import StageAwareCharClassifier
from io_guard.types import SourceType


MODEL_DIR = (
    Path(__file__).resolve().parents[1]
    / "model_heads"
    / "io-guard-stage-char-v3"
)


def test_retained_stage_classifier_loads_all_three_heads() -> None:
    classifier = StageAwareCharClassifier(model_dir=MODEL_DIR)
    status = classifier.status()

    assert set(status["heads"]) == {"input", "content", "output"}
    assert status["structured_tool_fields"] is True


def test_retained_classifier_emits_only_target_taxonomy_labels() -> None:
    classifier = StageAwareCharClassifier(model_dir=MODEL_DIR)
    expected = {
        SourceType.USER_PROMPT: "direct_prompt_injection",
        SourceType.RETRIEVAL_CHUNK: "indirect_prompt_injection",
        SourceType.MODEL_OUTPUT: "harmful_or_offensive_content",
    }

    for source_type, label in expected.items():
        _unsafe, _score, actual = classifier("普通测试文本", source_type)
        assert actual.startswith(label + ";")
