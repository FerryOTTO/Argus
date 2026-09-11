from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.preprocessing import StandardScaler


LABELS = (
    "normal",
    "prompt_injection",
    "jailbreak",
    "credential_leak",
    "dangerous_command",
    "resource_abuse",
    "external_content_poisoning",
    "unsafe_content",
)
STAGE_TO_HEAD = {
    "user_prompt": "input",
    "model_output": "output",
    "retrieval_chunk": "content",
    "tool_result": "content",
}


@dataclass(frozen=True)
class Candidate:
    c: float
    class_weight: str | None

    @property
    def name(self) -> str:
        return f"c={self.c:g};class_weight={self.class_weight or 'none'}"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def head_rows(rows: list[dict[str, Any]], head: str) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if STAGE_TO_HEAD[str(row["source_type"])] == head
    ]


def model_text(row: dict[str, Any]) -> str:
    source_type = str(row["source_type"])
    marker = {
        "user_prompt": "[输入]",
        "model_output": "[输出]",
        "retrieval_chunk": "[检索内容]",
        "tool_result": "[工具结果]",
    }[source_type]
    return f"{marker} {row['text']}"


def load_encoder(model_name_or_path: str, device: str):
    import torch
    from sentence_transformers import SentenceTransformer

    resolved_device = device
    if device == "auto":
        resolved_device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(
        model_name_or_path,
        device=resolved_device,
        local_files_only=True,
    )
    return model, resolved_device


def encode_rows(model, rows: list[dict[str, Any]], batch_size: int) -> np.ndarray:
    if not rows:
        return np.empty((0, model.get_sentence_embedding_dimension()))
    return np.asarray(
        model.encode(
            [model_text(row) for row in rows],
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=True,
        ),
        dtype=np.float32,
    )


def fit_temperature(probabilities: np.ndarray, labels: np.ndarray) -> float:
    clipped = np.clip(probabilities, 1e-7, 1.0)
    logits = np.log(clipped)
    candidates = np.linspace(0.55, 3.0, 100)
    best_temperature = 1.0
    best_nll = math.inf
    for temperature in candidates:
        scaled = logits / temperature
        scaled -= scaled.max(axis=1, keepdims=True)
        exp = np.exp(scaled)
        calibrated = exp / exp.sum(axis=1, keepdims=True)
        nll = -float(
            np.log(np.clip(calibrated[np.arange(len(labels)), labels], 1e-9, 1.0)).mean()
        )
        if nll < best_nll:
            best_nll = nll
            best_temperature = float(temperature)
    return best_temperature


def apply_temperature(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    logits = np.log(np.clip(probabilities, 1e-7, 1.0)) / temperature
    logits -= logits.max(axis=1, keepdims=True)
    exp = np.exp(logits)
    return exp / exp.sum(axis=1, keepdims=True)


def unsafe_scores(probabilities: np.ndarray, classes: np.ndarray) -> np.ndarray:
    normal_indexes = np.flatnonzero(classes == "normal")
    if len(normal_indexes) != 1:
        raise ValueError("each stage head must contain exactly one normal class")
    return 1.0 - probabilities[:, int(normal_indexes[0])]


def binary_stats(
    labels: np.ndarray,
    scores: np.ndarray,
    threshold: float,
) -> dict[str, float | int]:
    actual = labels != "normal"
    predicted = scores >= threshold
    tp = int(np.sum(actual & predicted))
    fp = int(np.sum(~actual & predicted))
    fn = int(np.sum(actual & ~predicted))
    tn = int(np.sum(~actual & ~predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "threshold": round(float(threshold), 6),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": fpr,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def select_threshold(
    *,
    labels: np.ndarray,
    scores: np.ndarray,
    max_fpr: float,
    min_recall: float,
) -> tuple[float, dict[str, Any]]:
    candidates = np.unique(
        np.concatenate(
            [np.linspace(0.05, 0.95, 181), scores.astype(float)]
        )
    )
    metrics = [binary_stats(labels, scores, float(value)) for value in candidates]
    feasible = [
        item
        for item in metrics
        if item["false_positive_rate"] <= max_fpr
        and item["recall"] >= min_recall
    ]
    if feasible:
        best = max(
            feasible,
            key=lambda item: (item["f1"], item["recall"], -item["threshold"]),
        )
    else:
        best = max(
            metrics,
            key=lambda item: (
                item["recall"] - 5.0 * max(0.0, item["false_positive_rate"] - max_fpr),
                item["f1"],
            ),
        )
    return float(best["threshold"]), best


def multiclass_metrics(
    labels: np.ndarray,
    probabilities: np.ndarray,
    classes: np.ndarray,
) -> dict[str, Any]:
    predicted = classes[probabilities.argmax(axis=1)]
    present_labels = sorted(set(labels) | set(predicted))
    return {
        "macro_f1": float(
            f1_score(labels, predicted, average="macro", zero_division=0)
        ),
        "classification_report": classification_report(
            labels,
            predicted,
            labels=present_labels,
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix_labels": present_labels,
        "confusion_matrix": confusion_matrix(
            labels, predicted, labels=present_labels
        ).tolist(),
    }


def stage_metrics(
    rows: list[dict[str, Any]],
    labels: np.ndarray,
    scores: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source_type in sorted({str(row["source_type"]) for row in rows}):
        indexes = np.array(
            [index for index, row in enumerate(rows) if row["source_type"] == source_type]
        )
        result[source_type] = binary_stats(
            labels[indexes], scores[indexes], threshold
        )
    return result


def candidate_score(
    *,
    multiclass_macro_f1: float,
    binary: dict[str, Any],
    max_fpr: float,
) -> float:
    return (
        0.45 * multiclass_macro_f1
        + 0.55 * float(binary["f1"])
        - 8.0 * max(0.0, float(binary["false_positive_rate"]) - max_fpr)
    )


def train_head(
    *,
    head: str,
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    train_embeddings: np.ndarray,
    validation_embeddings: np.ndarray,
    test_embeddings: np.ndarray,
    output_dir: Path,
    seed: int,
    max_fpr: float,
    min_recall: float,
    candidates: Iterable[Candidate],
) -> dict[str, Any]:
    train_labels = np.asarray([str(row["label"]) for row in train_rows])
    validation_labels = np.asarray(
        [str(row["label"]) for row in validation_rows]
    )
    test_labels = np.asarray([str(row["label"]) for row in test_rows])

    scaler = StandardScaler().fit(train_embeddings)
    x_train = scaler.transform(train_embeddings)
    x_validation = scaler.transform(validation_embeddings)
    x_test = scaler.transform(test_embeddings)
    candidate_results = []
    best: tuple[float, Any, float, float, dict[str, Any]] | None = None
    for candidate in candidates:
        classifier = LogisticRegression(
            C=candidate.c,
            class_weight=candidate.class_weight,
            max_iter=2000,
            solver="lbfgs",
            random_state=seed,
        ).fit(x_train, train_labels)
        raw_validation_probabilities = classifier.predict_proba(x_validation)
        temperature = fit_temperature(
            raw_validation_probabilities,
            np.asarray(
                [
                    int(np.flatnonzero(classifier.classes_ == value)[0])
                    for value in validation_labels
                ]
            ),
        )
        validation_probabilities = apply_temperature(
            raw_validation_probabilities, temperature
        )
        scores = unsafe_scores(validation_probabilities, classifier.classes_)
        threshold, binary = select_threshold(
            labels=validation_labels,
            scores=scores,
            max_fpr=max_fpr,
            min_recall=min_recall,
        )
        multi = multiclass_metrics(
            validation_labels, validation_probabilities, classifier.classes_
        )
        score = candidate_score(
            multiclass_macro_f1=multi["macro_f1"],
            binary=binary,
            max_fpr=max_fpr,
        )
        record = {
            "candidate": candidate.name,
            "temperature": temperature,
            "unsafe_threshold": threshold,
            "selection_score": score,
            "validation_binary": binary,
            "validation_macro_f1": multi["macro_f1"],
        }
        candidate_results.append(record)
        if best is None or score > best[0]:
            best = (score, classifier, temperature, threshold, record)
    if best is None:
        raise RuntimeError(f"no candidate trained for {head}")

    _, classifier, temperature, threshold, selected_record = best
    validation_probabilities = apply_temperature(
        classifier.predict_proba(x_validation), temperature
    )
    test_probabilities = apply_temperature(
        classifier.predict_proba(x_test), temperature
    )
    validation_scores = unsafe_scores(
        validation_probabilities, classifier.classes_
    )
    test_scores = unsafe_scores(test_probabilities, classifier.classes_)
    test_binary = binary_stats(test_labels, test_scores, threshold)
    test_multi = multiclass_metrics(
        test_labels, test_probabilities, classifier.classes_
    )

    model_payload = {
        "schema_version": 1,
        "head": head,
        "classes": classifier.classes_.tolist(),
        "scaler_mean": scaler.mean_.astype(np.float32),
        "scaler_scale": scaler.scale_.astype(np.float32),
        "coefficients": classifier.coef_.astype(np.float32),
        "intercepts": classifier.intercept_.astype(np.float32),
        "temperature": float(temperature),
        "unsafe_threshold": float(threshold),
    }
    joblib.dump(model_payload, output_dir / f"{head}_head.joblib", compress=3)

    return {
        "head": head,
        "counts": {
            "train": len(train_rows),
            "validation": len(validation_rows),
            "test": len(test_rows),
            "train_by_label": dict(Counter(train_labels)),
            "validation_by_label": dict(Counter(validation_labels)),
            "test_by_label": dict(Counter(test_labels)),
        },
        "selection": selected_record,
        "candidate_results": candidate_results,
        "validation": {
            "binary": binary_stats(
                validation_labels, validation_scores, threshold
            ),
            "by_source_type": stage_metrics(
                validation_rows,
                validation_labels,
                validation_scores,
                threshold,
            ),
            **multiclass_metrics(
                validation_labels,
                validation_probabilities,
                classifier.classes_,
            ),
        },
        "test": {
            "binary": test_binary,
            "by_source_type": stage_metrics(
                test_rows, test_labels, test_scores, threshold
            ),
            **test_multi,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--max-fpr", type=float, default=0.01)
    parser.add_argument("--min-recall", type=float, default=0.85)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.time()

    datasets = {
        split: read_jsonl(args.dataset_root / f"{split}.jsonl")
        for split in ("train", "validation", "test")
    }
    model, device = load_encoder(args.base_model, args.device)
    heads: dict[str, Any] = {}
    candidates = [
        Candidate(c=c_value, class_weight=class_weight)
        for c_value in (0.03, 0.1, 0.3, 1.0, 3.0)
        for class_weight in (None, "balanced")
    ]

    for head in ("input", "output", "content"):
        split_rows = {
            split: head_rows(rows, head)
            for split, rows in datasets.items()
        }
        embeddings = {
            split: encode_rows(model, rows, args.batch_size)
            for split, rows in split_rows.items()
        }
        heads[head] = train_head(
            head=head,
            train_rows=split_rows["train"],
            validation_rows=split_rows["validation"],
            test_rows=split_rows["test"],
            train_embeddings=embeddings["train"],
            validation_embeddings=embeddings["validation"],
            test_embeddings=embeddings["test"],
            output_dir=args.output_dir,
            seed=args.seed,
            max_fpr=args.max_fpr,
            min_recall=args.min_recall,
            candidates=candidates,
        )
        print(json.dumps(heads[head]["test"], ensure_ascii=False, indent=2))

    metadata = {
        "schema_version": 3,
        "model_type": "stage_aware_bge_logistic_heads",
        "base_model": args.base_model,
        "device": device,
        "production_ready": False,
        "seed": args.seed,
        "selection_constraints": {
            "max_false_positive_rate": args.max_fpr,
            "min_recall": args.min_recall,
        },
        "dataset_hashes": {
            split: sha256(args.dataset_root / f"{split}.jsonl")
            for split in ("train", "validation", "test")
        },
        "heads": heads,
        "training_seconds": round(time.time() - started_at, 3),
    }
    (args.output_dir / "training_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
