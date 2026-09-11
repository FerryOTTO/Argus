from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.preprocessing import StandardScaler


STAGE_TO_HEAD = {
    "user_prompt": "input",
    "model_output": "output",
    "retrieval_chunk": "content",
    "tool_result": "content",
}


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


def model_text(row: dict[str, Any]) -> str:
    marker = {
        "user_prompt": "[输入]",
        "model_output": "[输出]",
        "retrieval_chunk": "[检索内容]",
        "tool_result": "[工具结果]",
    }[str(row["source_type"])]
    return f"{marker} {row['text']}"


def temperature_scale(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    logits = np.log(np.clip(probabilities, 1e-7, 1.0)) / temperature
    logits -= logits.max(axis=1, keepdims=True)
    exp = np.exp(logits)
    return exp / exp.sum(axis=1, keepdims=True)


def fit_temperature(probabilities: np.ndarray, labels: np.ndarray) -> float:
    best = (math.inf, 1.0)
    for temperature in np.linspace(0.55, 3.0, 100):
        values = temperature_scale(probabilities, float(temperature))
        nll = -float(
            np.log(np.clip(values[np.arange(len(labels)), labels], 1e-9, 1.0)).mean()
        )
        if nll < best[0]:
            best = (nll, float(temperature))
    return best[1]


def binary_stats(actual: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
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
    labels: np.ndarray,
    scores: np.ndarray,
    max_fpr: float,
    min_recall: float,
) -> tuple[float, dict[str, Any]]:
    candidates = np.unique(
        np.concatenate([np.linspace(0.01, 0.99, 197), scores])
    )
    records = []
    for threshold in candidates:
        metrics = binary_stats(labels, scores >= threshold)
        metrics["threshold"] = float(threshold)
        records.append(metrics)
    feasible = [
        item
        for item in records
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
            records,
            key=lambda item: (
                item["f1"]
                - 8.0 * max(0.0, item["false_positive_rate"] - max_fpr)
                - 1.5 * max(0.0, min_recall - item["recall"]),
                item["recall"],
            ),
        )
    return float(best["threshold"]), best


def by_source_type(
    rows: list[dict[str, Any]],
    labels: np.ndarray,
    scores: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    result = {}
    for source_type in sorted({str(row["source_type"]) for row in rows}):
        mask = np.asarray([row["source_type"] == source_type for row in rows])
        result[source_type] = binary_stats(
            labels[mask], scores[mask] >= threshold
        )
    return result


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
    started = time.time()

    import torch
    from sentence_transformers import SentenceTransformer

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    encoder = SentenceTransformer(
        args.base_model, device=device, local_files_only=True
    )
    all_rows = {
        split: read_jsonl(args.dataset_root / f"{split}.jsonl")
        for split in ("train", "validation", "test")
    }
    head_results = {}
    for head in ("input", "output", "content"):
        rows = {
            split: [
                row
                for row in split_rows
                if STAGE_TO_HEAD[str(row["source_type"])] == head
            ]
            for split, split_rows in all_rows.items()
        }
        embeddings = {
            split: encoder.encode(
                [model_text(row) for row in split_rows],
                batch_size=args.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=True,
            ).astype(np.float32)
            for split, split_rows in rows.items()
        }
        labels = {
            split: np.asarray(
                [row["label"] != "normal" for row in split_rows], dtype=bool
            )
            for split, split_rows in rows.items()
        }
        scaler = StandardScaler().fit(embeddings["train"])
        features = {
            split: scaler.transform(values)
            for split, values in embeddings.items()
        }
        candidate_results = []
        best = None
        for c_value in (0.003, 0.01, 0.03, 0.1, 0.3, 1.0):
            for class_weight in (None, "balanced"):
                classifier = LogisticRegression(
                    C=c_value,
                    class_weight=class_weight,
                    max_iter=2000,
                    random_state=args.seed,
                ).fit(features["train"], labels["train"].astype(int))
                raw = classifier.predict_proba(features["validation"])
                temperature = fit_temperature(
                    raw, labels["validation"].astype(int)
                )
                validation_scores = temperature_scale(raw, temperature)[:, 1]
                threshold, validation_metrics = select_threshold(
                    labels["validation"],
                    validation_scores,
                    args.max_fpr,
                    args.min_recall,
                )
                selection_score = (
                    validation_metrics["f1"]
                    - 8.0
                    * max(
                        0.0,
                        validation_metrics["false_positive_rate"]
                        - args.max_fpr,
                    )
                    - 1.5
                    * max(
                        0.0,
                        args.min_recall - validation_metrics["recall"],
                    )
                )
                record = {
                    "c": c_value,
                    "class_weight": class_weight,
                    "temperature": temperature,
                    "unsafe_threshold": threshold,
                    "selection_score": selection_score,
                    "validation": validation_metrics,
                }
                candidate_results.append(record)
                if best is None or selection_score > best[0]:
                    best = (
                        selection_score,
                        classifier,
                        temperature,
                        threshold,
                        record,
                    )
        if best is None:
            raise RuntimeError(f"no candidate for {head}")
        _, classifier, temperature, threshold, selected = best
        test_scores = temperature_scale(
            classifier.predict_proba(features["test"]), temperature
        )[:, 1]
        validation_scores = temperature_scale(
            classifier.predict_proba(features["validation"]), temperature
        )[:, 1]
        test_metrics = binary_stats(
            labels["test"], test_scores >= threshold
        )
        errors = []
        for index, (actual, predicted) in enumerate(
            zip(labels["test"], test_scores >= threshold, strict=True)
        ):
            if actual == predicted:
                continue
            row = rows["test"][index]
            errors.append(
                {
                    "id": row["id"],
                    "source": row["source"],
                    "source_type": row["source_type"],
                    "label": row["label"],
                    "score": float(test_scores[index]),
                    "error": "false_positive" if predicted else "false_negative",
                    "text": row["text"],
                }
            )
        model_payload = {
            "schema_version": 1,
            "head": head,
            "classes": ["normal", "unsafe"],
            "scaler_mean": scaler.mean_.astype(np.float32),
            "scaler_scale": scaler.scale_.astype(np.float32),
            "coefficients": classifier.coef_.astype(np.float32),
            "intercepts": classifier.intercept_.astype(np.float32),
            "temperature": float(temperature),
            "unsafe_threshold": float(threshold),
        }
        joblib.dump(
            model_payload, args.output_dir / f"{head}_binary.joblib", compress=3
        )
        head_results[head] = {
            "counts": {
                split: {
                    "total": len(split_rows),
                    "normal": int(np.sum(~labels[split])),
                    "unsafe": int(np.sum(labels[split])),
                    "by_label": dict(Counter(row["label"] for row in split_rows)),
                }
                for split, split_rows in rows.items()
            },
            "selection": selected,
            "candidates": candidate_results,
            "validation": {
                **binary_stats(
                    labels["validation"], validation_scores >= threshold
                ),
                "by_source_type": by_source_type(
                    rows["validation"],
                    labels["validation"],
                    validation_scores,
                    threshold,
                ),
            },
            "test": {
                **test_metrics,
                "by_source_type": by_source_type(
                    rows["test"], labels["test"], test_scores, threshold
                ),
            },
            "errors": errors,
        }
        print(head, json.dumps(head_results[head]["test"], ensure_ascii=False))

    metadata = {
        "schema_version": 3,
        "model_type": "stage_aware_bge_binary_heads",
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
        "heads": head_results,
        "training_seconds": round(time.time() - started, 3),
    }
    (args.output_dir / "training_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
