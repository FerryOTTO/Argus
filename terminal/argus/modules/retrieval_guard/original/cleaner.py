"""把 OpenClaw 检索结果清洗为可送检且可回写的真实网页正文。"""

from __future__ import annotations

import json
import re
from typing import Any

MIN_LENGTH = 1
MAX_JSON_DEPTH = 3

EXTERNAL_BLOCK_RE = re.compile(
    r"<<<EXTERNAL_UNTRUSTED_CONTENT\b[^>]*>>>\s*"
    r"(?:Source:\s*Web (?:Search|Fetch)\s*)?(?:---\s*)?"
    r"([\s\S]*?)\s*"
    r"<<<END_EXTERNAL_UNTRUSTED_CONTENT\b[^>]*>>>",
    re.IGNORECASE,
)
LEGACY_WRAPPER_RE = re.compile(
    r"(?:^|\n)---\s*\n([\s\S]*?)"
    r"<<<END_EXTERNAL_UNTRUSTED_CONTENT\b[^>]*>>>",
    re.IGNORECASE,
)
ERROR_STATUSES = {"error", "failed", "failure"}
EXTERNAL_TOOLS = {"web_fetch", "web_search"}


def clean(text: str, *, tool_name: str = "") -> str | None:
    """Return the real retrieved text, excluding transport-only warnings.

    OpenClaw can nest or JSON-encode a failed ``web_fetch`` result multiple
    times.  The failure message contains a security notice that must not be
    classified as page content, while text inside the explicit external trust
    boundary must still be checked and preserved for a possible rewrite.
    """

    if not isinstance(text, str) or not text.strip():
        return None

    parsed = _parse_structured_value(text)
    blocks = _external_blocks(parsed)
    if blocks:
        check_text = "\n".join(_deduplicate(blocks)).strip()
    else:
        if _contains_transport_error(parsed, tool_name=tool_name):
            return None
        check_text = _preferred_text(parsed) or text
        check_text = _unwrap_external_content(check_text)

    check_text = check_text.strip()
    if len(check_text) < MIN_LENGTH:
        return None

    return check_text


def _parse_structured_value(value: Any) -> Any:
    current = value
    for _ in range(MAX_JSON_DEPTH):
        if not isinstance(current, str):
            break
        candidate = current.strip()
        if not candidate:
            break
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            break
        if parsed == current:
            break
        current = parsed
    return current


def _external_blocks(value: Any) -> list[str]:
    if isinstance(value, dict):
        blocks: list[str] = []
        for child in value.values():
            blocks.extend(_external_blocks(child))
        return blocks
    if isinstance(value, (list, tuple, set)):
        blocks = []
        for child in value:
            blocks.extend(_external_blocks(child))
        return blocks
    if not isinstance(value, str):
        return []

    decoded = _decode_transport_newlines(value)
    matches = [match.strip() for match in EXTERNAL_BLOCK_RE.findall(decoded)]
    if matches:
        return [match for match in matches if match]
    parsed = _parse_structured_value(value)
    return [] if parsed == value else _external_blocks(parsed)


def _decode_transport_newlines(value: str) -> str:
    if "EXTERNAL_UNTRUSTED_CONTENT" not in value:
        return value
    return (
        value.replace(r"\r\n", "\n")
        .replace(r"\n", "\n")
        .replace(r"\r", "\n")
        .replace(r"\t", "\t")
    )


def _contains_transport_error(value: Any, *, tool_name: str) -> bool:
    if isinstance(value, dict):
        status = str(value.get("status") or "").strip().casefold()
        embedded_tool = str(value.get("tool") or "").strip().casefold()
        effective_tool = embedded_tool or tool_name.strip().casefold()
        if status in ERROR_STATUSES and effective_tool in EXTERNAL_TOOLS:
            return True
        if (
            embedded_tool in EXTERNAL_TOOLS
            and value.get("error") not in (None, "", False)
        ):
            return True
        return any(
            _contains_transport_error(child, tool_name=effective_tool)
            for child in value.values()
        )
    if isinstance(value, (list, tuple, set)):
        return any(
            _contains_transport_error(child, tool_name=tool_name)
            for child in value
        )
    if isinstance(value, str):
        parsed = _parse_structured_value(value)
        return parsed != value and _contains_transport_error(
            parsed,
            tool_name=tool_name,
        )
    return False


def _preferred_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    for key in ("text", "content"):
        selected = _string_leaves(value.get(key))
        if selected:
            return "\n".join(_deduplicate(selected))
    return None


def _string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        selected: list[str] = []
        for child in value:
            selected.extend(_string_leaves(child))
        return selected
    if isinstance(value, dict):
        selected = []
        for child in value.values():
            selected.extend(_string_leaves(child))
        return selected
    return []


def _unwrap_external_content(value: str) -> str:
    decoded = _decode_transport_newlines(value)
    match = LEGACY_WRAPPER_RE.search(decoded)
    return match.group(1).strip() if match else decoded


def _deduplicate(values: list[str]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            selected.append(normalized)
            seen.add(normalized)
    return selected
