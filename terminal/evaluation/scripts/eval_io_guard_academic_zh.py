"""Evaluate IO Guard against locally downloaded academic Chinese datasets.

The script intentionally does not download or vendor third-party datasets.
Pass a directory containing the official SafetyBench Chinese test JSON and
AlignBench JSONL files. This keeps licensing and version choices explicit.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
IO_GUARD_ROOT = REPO_ROOT / "clawguard/modules/io_guard/original"
sys.path.insert(0, str(IO_GUARD_ROOT / "src"))

from io_guard import GuardRequest, IOGuard, SourceType  # noqa: E402


def _load_alignbench(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _evaluate(
    guard: IOGuard,
    rows: list[tuple[str, str]],
    *,
    stage: str,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for record_id, text in rows:
        request = GuardRequest(
            content=text,
            source_type=(
                SourceType.MODEL_OUTPUT
                if stage == "output"
                else SourceType.USER_PROMPT
            ),
        )
        result = (
            guard.post_check(request)
            if stage == "output"
            else guard.pre_check(request)
        )
        if result.decision.value != "allow":
            findings.append(
                {
                    "id": record_id,
                    "action": result.decision.value,
                    "risk_types": [risk.value for risk in result.risk_types],
                    "evidence": [item.message for item in result.evidence],
                }
            )
    return {
        "total": len(rows),
        "flagged": len(findings),
        "flag_rate": len(findings) / len(rows) if rows else 0.0,
        "evidence_counts": dict(
            Counter(
                evidence
                for finding in findings
                for evidence in finding["evidence"]
            )
        ),
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    align = _load_alignbench(args.data_dir / "alignbench.jsonl")
    safety = json.loads(
        (args.data_dir / "safetybench_test_zh.json").read_text(
            encoding="utf-8"
        )
    )
    guard = IOGuard()
    report = {
        "policy": "rules-only",
        "sources": {
            "alignbench": "THUDM/AlignBench",
            "safetybench": "thu-coai/SafetyBench",
        },
        "results": {
            "align_input": _evaluate(
                guard,
                [
                    (str(item["question_id"]), str(item["question"]))
                    for item in align
                ],
                stage="input",
            ),
            "align_output": _evaluate(
                guard,
                [
                    (str(item["question_id"]), str(item["reference"]))
                    for item in align
                ],
                stage="output",
            ),
            "safety_input": _evaluate(
                guard,
                [
                    (str(item["id"]), str(item["question"]))
                    for item in safety
                ],
                stage="input",
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["results"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
