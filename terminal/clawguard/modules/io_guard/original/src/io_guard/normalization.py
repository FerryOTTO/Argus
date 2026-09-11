from __future__ import annotations

import re
import unicodedata


ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\ufeff]")


def normalize_text(text: str) -> str:
    """Normalize text before detection while preserving human-readable content."""
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = ZERO_WIDTH_RE.sub("", normalized)
    return normalized.strip()


def estimate_tokens(text: str) -> int:
    """Rough token estimate for budget checks without external tokenizers."""
    if not text:
        return 0
    ascii_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_chars = max(len(text) - cjk_chars, 0)
    return max(ascii_words + cjk_chars + other_chars // 4, 1)


def safe_snippet(text: str, start: int, end: int, limit: int = 120) -> str:
    snippet = text[start:end]
    if len(snippet) <= limit:
        return snippet
    return snippet[: limit - 3] + "..."
