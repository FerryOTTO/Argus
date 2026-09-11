"""Lazy OCR engine (RapidOCR on CPU) with graceful unavailability."""

from __future__ import annotations

import threading
from typing import Any

_ENGINE: Any = None
_INIT_ERROR: str | None = None
_LOCK = threading.Lock()


def get_ocr(lang: str = "ch") -> Any:
    """Return the shared OCR engine, raising if it cannot be initialised."""
    global _ENGINE, _INIT_ERROR
    if _ENGINE is not None:
        return _ENGINE
    with _LOCK:
        if _ENGINE is not None:
            return _ENGINE
        if _INIT_ERROR is not None:
            raise RuntimeError(_INIT_ERROR)
        try:
            from rapidocr_onnxruntime import RapidOCR

            _ENGINE = RapidOCR()
        except Exception as exc:
            _INIT_ERROR = f"OCR engine unavailable: {exc}"
            raise RuntimeError(_INIT_ERROR) from exc
    return _ENGINE


def ocr_image(path: str) -> str:
    """Run OCR over an image and return joined recognized text lines."""
    engine = get_ocr()
    result, _ = engine(str(path))
    if not result:
        return ""
    lines: list[str] = []
    for item in result:
        try:
            text = str(item[1])
        except (TypeError, IndexError, ValueError):
            continue
        if text.strip():
            lines.append(text.strip())
    return "\n".join(lines)
