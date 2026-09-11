from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score


STAGE_TO_HEAD = {
    "user_prompt": "input",
    "model_output": "output",
    "retrieval_chunk": "content",
    "tool_result": "content",
}


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def model_text(row: dict) -> str:
    marker = {
        "user_prompt": "[输入]",
        "model_output": "[输出]",
        "retrieval_chunk": "[检索内容]",
        "tool_result": "[工具结果]",
    }[row["source_type"]]
    return f"{marker} {row['text']}"


def apply_head(payload: dict, embeddings: np.ndarray) -> np.ndarray:
    values = (embeddings - payload["scaler_mean"]) / payload["scaler_scale"]
    logits = values @ payload["coefficients"].T + payload["intercepts"]
    if len(payload["classes"]) == 2 and logits.shape[1] == 1:
        # scikit-learn stores one logit for binary logistic regression. The
        # first class is the zero logit and the second class uses this value.
        logits = np.column_stack([np.zeros(len(logits)), logits[:, 0]])
    logits /= payload["temperature"]
    logits -= logits.max(axis=1, keepdims=True)
    exp = np.exp(logits)
    return exp / exp.sum(axis=1, keepdims=True)


def binary_stats(actual: np.ndarray, predicted: np.ndarray) -> dict:
    tp = int(np.sum(actual & predicted))
    fp = int(np.sum(~actual & predicted))
    fn = int(np.sum(actual & ~predicted))
    tn = int(np.sum(~actual & ~predicted))
    return {
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--base-model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from sentence_transformers import SentenceTransformer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    encoder = SentenceTransformer(
        args.base_model, device=device, local_files_only=True
    )
    result = {"device": device, "heads": {}}
    for head in ("input", "output", "content"):
        payload = joblib.load(args.model_dir / f"{head}_head.joblib")
        values = {"validation": [], "test": []}
        for split in values:
            rows = [
                row
                for row in read_jsonl(args.dataset_root / f"{split}.jsonl")
                if STAGE_TO_HEAD[row["source_type"]] == head
            ]
            embeddings = encoder.encode(
                [model_text(row) for row in rows],
                batch_size=args.batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=True,
            ).astype(np.float32)
            probabilities = apply_head(payload, embeddings)
            classes = np.asarray(payload["classes"])
            normal_index = int(np.flatnonzero(classes == "normal")[0])
            unsafe_probability = 1.0 - probabilities[:, normal_index]
            predicted_class = classes[probabilities.argmax(axis=1)]
            values[split] = {
                "rows": rows,
                "embeddings": embeddings,
                "probabilities": probabilities,
                "unsafe_probability": unsafe_probability,
                "predicted_class": predicted_class,
            }

        validation = values["validation"]
        validation_actual = np.asarray(
            [row["label"] != "normal" for row in validation["rows"]]
        )
        # The second-level decision head is a genuinely optimized binary model.
        # It learns which multiclass probability patterns are reliable for a
        # stage instead of assuming every non-normal argmax is equally risky.
        meta_features = np.column_stack(
            [validation["probabilities"], validation["embeddings"]]
        )
        meta = LogisticRegression(
            C=0.03,
            class_weight="balanced",
            max_iter=2000,
            random_state=20260813,
        ).fit(meta_features, validation_actual.astype(int))
        validation_scores = meta.predict_proba(meta_features)[:, 1]
        candidates = np.unique(
            np.concatenate([np.linspace(0.05, 0.99, 189), validation_scores])
        )
        scored = []
        for threshold in candidates:
            metrics = binary_stats(
                validation_actual, validation_scores >= threshold
            )
            metrics["threshold"] = float(threshold)
            scored.append(metrics)
        feasible = [
            item
            for item in scored
            if item["false_positive_rate"] <= 0.01 and item["recall"] >= 0.85
        ]
        best = max(
            feasible or scored,
            key=lambda item: (
                2
                * item["precision"]
                * item["recall"]
                / max(1e-12, item["precision"] + item["recall"])
                - 8 * max(0.0, item["false_positive_rate"] - 0.01)
            ),
        )

        test = values["test"]
        test_actual = np.asarray(
            [row["label"] != "normal" for row in test["rows"]]
        )
        test_features = np.column_stack(
            [test["probabilities"], test["embeddings"]]
        )
        test_scores = meta.predict_proba(test_features)[:, 1]
        test_predicted = test_scores >= best["threshold"]
        test_metrics = binary_stats(test_actual, test_predicted)
        errors = []
        for index, (actual, predicted) in enumerate(
            zip(test_actual, test_predicted, strict=True)
        ):
            if actual == predicted:
                continue
            row = test["rows"][index]
            errors.append(
                {
                    "id": row["id"],
                    "source": row["source"],
                    "source_type": row["source_type"],
                    "label": row["label"],
                    "predicted_class": str(test["predicted_class"][index]),
                    "unsafe_score": float(test_scores[index]),
                    "error": "false_positive" if predicted else "false_negative",
                    "text": row["text"],
                }
            )
        errors.sort(
            key=lambda item: (
                item["error"],
                -item["unsafe_score"]
                if item["error"] == "false_positive"
                else item["unsafe_score"],
            )
        )
        result["heads"][head] = {
            "validation": best,
            "test": test_metrics,
            "errors": errors,
            "meta_head": {
                "classes": meta.classes_.tolist(),
                "coefficients": meta.coef_.astype(np.float32).tolist(),
                "intercepts": meta.intercept_.astype(np.float32).tolist(),
                "unsafe_threshold": best["threshold"],
            },
        }
        print(head, json.dumps(test_metrics, ensure_ascii=False))

    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
