from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


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


def stats(actual: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
    tp = int(np.sum(actual & predicted))
    fp = int(np.sum(~actual & predicted))
    fn = int(np.sum(actual & ~predicted))
    tn = int(np.sum(~actual & ~predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
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


def choose_threshold(
    labels: np.ndarray,
    scores: np.ndarray,
    *,
    max_fpr: float,
    min_recall: float,
) -> tuple[float, dict[str, Any]]:
    candidates = np.unique(
        np.concatenate([np.linspace(0.01, 0.99, 197), scores])
    )
    values = []
    for threshold in candidates:
        item = stats(labels, scores >= threshold)
        item["threshold"] = float(threshold)
        values.append(item)
    feasible = [
        item
        for item in values
        if item["false_positive_rate"] <= max_fpr and item["recall"] >= min_recall
    ]
    return max(
        feasible or values,
        key=lambda item: (
            item["f1"]
            - 10 * max(0.0, item["false_positive_rate"] - max_fpr)
            - 2 * max(0.0, min_recall - item["recall"]),
            item["recall"],
        ),
    )["threshold"], max(
        feasible or values,
        key=lambda item: (
            item["f1"]
            - 10 * max(0.0, item["false_positive_rate"] - max_fpr)
            - 2 * max(0.0, min_recall - item["recall"]),
            item["recall"],
        ),
    )


def by_source(
    rows: list[dict[str, Any]], labels: np.ndarray, scores: np.ndarray, threshold: float
) -> dict[str, Any]:
    result = {}
    for source_type in sorted({str(row["source_type"]) for row in rows}):
        mask = np.asarray([row["source_type"] == source_type for row in rows])
        result[source_type] = stats(labels[mask], scores[mask] >= threshold)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--max-fpr", type=float, default=0.01)
    parser.add_argument("--min-recall", type=float, default=0.85)
    parser.add_argument(
        "--production-ready",
        action="store_true",
        help=(
            "Mark the reviewed artifact as production ready. Use only after "
            "the selected runtime thresholds and combined rule/model guard "
            "have passed integration evaluation."
        ),
    )
    parser.add_argument(
        "--production-threshold",
        action="append",
        default=[],
        metavar="HEAD=VALUE",
        help=(
            "Optional reviewed runtime threshold, for example output=0.30. "
            "The selected validation threshold remains recorded separately."
        ),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    datasets = {
        split: read_jsonl(args.dataset_root / f"{split}.jsonl")
        for split in ("train", "validation", "test")
    }
    production_thresholds: dict[str, float] = {}
    for value in args.production_threshold:
        head, separator, raw_threshold = value.partition("=")
        if not separator or head not in {"input", "output", "content"}:
            raise ValueError(f"invalid production threshold: {value}")
        threshold = float(raw_threshold)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"invalid production threshold: {value}")
        production_thresholds[head] = threshold
    results = {}
    for head in ("input", "output", "content"):
        rows = {
            split: [
                row
                for row in split_rows
                if STAGE_TO_HEAD[str(row["source_type"])] == head
            ]
            for split, split_rows in datasets.items()
        }
        texts = {split: [model_text(row) for row in values] for split, values in rows.items()}
        labels = {
            split: np.asarray([row["label"] != "normal" for row in values], dtype=bool)
            for split, values in rows.items()
        }
        candidates = []
        best = None
        for ngram_range, max_features in (((2, 5), 50000), ((2, 6), 80000)):
            vectorizer = TfidfVectorizer(
                analyzer="char",
                ngram_range=ngram_range,
                min_df=2,
                max_df=0.998,
                max_features=max_features,
                sublinear_tf=True,
                norm="l2",
            )
            x_train = vectorizer.fit_transform(texts["train"])
            x_validation = vectorizer.transform(texts["validation"])
            x_test = vectorizer.transform(texts["test"])
            for c_value in (0.3, 1.0, 3.0, 10.0):
                for class_weight in (None, "balanced"):
                    classifier = LogisticRegression(
                        C=c_value,
                        class_weight=class_weight,
                        solver="liblinear",
                        max_iter=2000,
                        random_state=args.seed,
                    ).fit(x_train, labels["train"].astype(int))
                    validation_scores = classifier.predict_proba(x_validation)[:, 1]
                    threshold, validation_metrics = choose_threshold(
                        labels["validation"],
                        validation_scores,
                        max_fpr=args.max_fpr,
                        min_recall=args.min_recall,
                    )
                    score = (
                        validation_metrics["f1"]
                        - 10
                        * max(
                            0.0,
                            validation_metrics["false_positive_rate"] - args.max_fpr,
                        )
                        - 2
                        * max(0.0, args.min_recall - validation_metrics["recall"])
                    )
                    record = {
                        "ngram_range": list(ngram_range),
                        "max_features": max_features,
                        "c": c_value,
                        "class_weight": class_weight,
                        "unsafe_threshold": threshold,
                        "selection_score": score,
                        "validation": validation_metrics,
                    }
                    candidates.append(record)
                    if best is None or score > best[0]:
                        best = (
                            score,
                            vectorizer,
                            classifier,
                            threshold,
                            record,
                            x_validation,
                            x_test,
                        )
        if best is None:
            raise RuntimeError(f"no candidate for {head}")
        _, vectorizer, classifier, threshold, selected, x_validation, x_test = best
        # Rebuild matrices because the retained vectorizer may no longer match
        # the final loop iteration's local variables.
        x_validation = vectorizer.transform(texts["validation"])
        x_test = vectorizer.transform(texts["test"])
        validation_scores = classifier.predict_proba(x_validation)[:, 1]
        test_scores = classifier.predict_proba(x_test)[:, 1]
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
        production_threshold = production_thresholds.get(head, threshold)
        payload = {
            "schema_version": 1,
            "head": head,
            "model_type": "char_tfidf_binary",
            "unsafe_threshold": float(production_threshold),
            "vectorizer": vectorizer,
            "classifier": classifier,
        }
        joblib.dump(payload, args.output_dir / f"{head}_char.joblib", compress=3)
        results[head] = {
            "selection": selected,
            "candidates": candidates,
            "counts": {
                split: dict(Counter("unsafe" if value else "normal" for value in labels[split]))
                for split in labels
            },
            "validation": {
                **stats(labels["validation"], validation_scores >= threshold),
                "by_source_type": by_source(
                    rows["validation"], labels["validation"], validation_scores, threshold
                ),
            },
            "test": {
                **stats(labels["test"], test_scores >= threshold),
                "by_source_type": by_source(
                    rows["test"], labels["test"], test_scores, threshold
                ),
            },
            "production": {
                "unsafe_threshold": float(production_threshold),
                "test": {
                    **stats(
                        labels["test"],
                        test_scores >= production_threshold,
                    ),
                    "by_source_type": by_source(
                        rows["test"],
                        labels["test"],
                        test_scores,
                        production_threshold,
                    ),
                },
            },
            "errors": errors,
            "artifact_bytes": (args.output_dir / f"{head}_char.joblib").stat().st_size,
        }
        print(head, json.dumps(results[head]["test"], ensure_ascii=False))

    metadata = {
        "schema_version": 3,
        "model_type": "stage_aware_char_tfidf_binary_heads",
        "production_ready": args.production_ready,
        "readiness_basis": (
            "reviewed runtime thresholds plus deterministic IO Guard rules"
            if args.production_ready
            else "training artifact; runtime review is still required"
        ),
        "seed": args.seed,
        "selection_constraints": {
            "max_false_positive_rate": args.max_fpr,
            "min_recall": args.min_recall,
        },
        "dataset_hashes": {
            split: sha256(args.dataset_root / f"{split}.jsonl")
            for split in ("train", "validation", "test")
        },
        "artifact_hashes": {
            head: sha256(args.output_dir / f"{head}_char.joblib")
            for head in ("input", "output", "content")
        },
        "heads": results,
        "training_seconds": round(time.time() - started, 3),
    }
    (args.output_dir / "training_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
