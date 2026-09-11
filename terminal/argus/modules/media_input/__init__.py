"""Media attachment extraction for input-stage checking."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from .config import load_media_config
from .download import fetch_remote
from .extractors import extract_from_file
from .mime import is_supported, normalize_type, sniff_mime

IMAGE_TYPES = {"png", "jpeg", "gif", "bmp", "webp"}


@dataclass
class ExtractedAttachment:
    """Result of extracting one attachment; errors are isolated per file."""

    name: str
    path: str | None = None
    url: str | None = None
    mime_type: str | None = None
    text: str = ""
    error: str | None = None


def _media_type(raw: dict[str, Any], name: str) -> str | None:
    declared = normalize_type(raw.get("mime_type"), name)
    return declared if is_supported(declared) else None


def _local_path(raw: dict[str, Any], cfg: dict[str, Any], name: str) -> str:
    path = raw.get("path")
    if path:
        return str(path)
    url = raw.get("url")
    if not url:
        raise ValueError("attachment has neither path nor url")
    remote = cfg.get("remote", {})
    return fetch_remote(
        str(url),
        int(remote.get("max_bytes", 5_000_000)),
        int(remote.get("timeout_ms", 8000)),
        name,
    )


def extract_attachments(
    attachments: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> list[ExtractedAttachment]:
    """Extract text from each attachment, isolating failures per file."""
    results: list[ExtractedAttachment] = []
    image_count = 0
    ocr_enabled = bool(cfg.get("ocr", {}).get("enabled", True))
    max_images = int(cfg.get("ocr", {}).get("max_images", 4))

    for raw in list(attachments)[: int(cfg["max_attachments"])]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "attachment")
        entry = ExtractedAttachment(
            name=name,
            path=str(raw["path"]) if raw.get("path") else None,
            url=str(raw["url"]) if raw.get("url") else None,
        )
        temporary_path: str | None = None
        try:
            local_path = _local_path(raw, cfg, name)
            if not raw.get("path") and raw.get("url"):
                temporary_path = local_path

            media_type = _media_type(raw, name) or sniff_mime(local_path)
            if media_type is None:
                raise ValueError("unsupported attachment type")
            entry.mime_type = media_type

            if media_type in IMAGE_TYPES:
                if not ocr_enabled:
                    raise ValueError("ocr disabled by policy")
                image_count += 1
                if image_count > max_images:
                    raise ValueError(
                        f"ocr.max_images exceeded ({max_images})"
                    )

            entry.text = extract_from_file(local_path, media_type, cfg)
        except Exception as exc:
            entry.error = str(exc)
            entry.text = ""
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
        results.append(entry)
    return results
