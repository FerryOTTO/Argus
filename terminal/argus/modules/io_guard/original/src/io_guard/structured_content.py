from __future__ import annotations

import ast
import json
from typing import Any


def extract_string_leaves(value: object) -> list[str]:
    """Return natural-language leaves from structured tool content.

    OpenClaw tool results are commonly JSON objects, Python-style dictionary
    strings, or a JSON string containing one of those values. Security meaning
    lives in string values such as a review, email body or page snippet; keys
    and punctuation are transport structure and must not become model features.
    """

    current = _parse_structured_value(value)
    leaves: list[str] = []

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple, set)):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            text = " ".join(item.split())
            if len(text) >= 8:
                leaves.append(text)

    visit(current)
    if leaves:
        return _deduplicate(leaves)
    text = " ".join(str(value).split())
    return [text] if text else []


def _parse_structured_value(value: object) -> object:
    current = value
    for _ in range(3):
        if not isinstance(current, str):
            break
        stripped = current.strip()
        if not stripped:
            break
        parsed: Any
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError, json.JSONDecodeError):
            try:
                parsed = ast.literal_eval(stripped)
            except (ValueError, SyntaxError):
                break
        if parsed == current:
            break
        current = parsed
    return current


def _deduplicate(values: list[str]) -> list[str]:
    selected = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        selected.append(value)
    return selected
