"""Remote attachment download with a hard byte cap."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx


def _safe_suffix(url: str, name: str) -> str:
    candidate = Path(name).suffix.lower() if name else ""
    if not candidate:
        candidate = Path(urlparse(url).path).suffix.lower()
    if len(candidate) <= 8 and candidate.replace(".", "").isalnum():
        return candidate
    return ".bin"


def fetch_remote(
    url: str,
    max_bytes: int,
    timeout_ms: int,
    name: str = "",
) -> str:
    """Stream-download ``url`` to a temp file, rejecting oversized bodies.

    Returns the local temp path on success and always cleans it up on error.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("remote attachment URL must use http or https")

    fd, tmp_path = tempfile.mkstemp(
        prefix="argus_media_", suffix=_safe_suffix(url, name)
    )
    os.close(fd)
    total = 0
    try:
        with httpx.stream(
            "GET",
            url,
            timeout=timeout_ms / 1000,
            follow_redirects=True,
        ) as response:
            response.raise_for_status()
            with open(tmp_path, "wb") as stream:
                for chunk in response.iter_bytes(chunk_size=65536):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(
                            f"remote attachment exceeds {max_bytes} bytes"
                        )
                    stream.write(chunk)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path
