"""Configuration for media attachment extraction."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "io_guard"
    / "original"
    / "configs"
    / "default_policy.json"
)

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "max_file_bytes": 15 * 1024 * 1024,
    "max_text_chars": 50000,
    "max_attachments": 5,
    "remote": {"max_bytes": 5 * 1024 * 1024, "timeout_ms": 8000},
    "ocr": {"enabled": True, "lang": "ch", "device": "cpu", "max_images": 4},
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_media_config(
    policy_path: Path | str | None = None,
) -> dict[str, Any]:
    """Load the media_extraction block, preferring the policy file copy.

    Falls back to built-in defaults when the policy file is missing or does
    not carry a media_extraction block.  ``IO_GUARD_MEDIA_POLICY`` overrides
    the policy path.
    """
    configured = os.getenv("IO_GUARD_MEDIA_POLICY")
    path = (
        Path(configured)
        if configured
        else (Path(policy_path) if policy_path is not None else DEFAULT_POLICY_PATH)
    )
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if not path.exists():
        return cfg
    try:
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return cfg
    block = data.get("media_extraction")
    if isinstance(block, dict):
        cfg = _merge(cfg, block)
    return cfg
