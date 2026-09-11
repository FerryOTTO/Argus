"""MIME sniffing and support checks for media attachments."""

from __future__ import annotations

import zipfile
from pathlib import Path

IMAGE_TYPES = {"png", "jpeg", "gif", "bmp", "webp"}
TEXT_TYPES = {"txt", "csv", "md"}
SUPPORTED_TYPES = {"pdf", "docx", "xlsx", "csv", "txt", *IMAGE_TYPES}

_EXT_TO_TYPE = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
    ".bmp": "bmp",
    ".webp": "webp",
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".csv": "csv",
    ".txt": "txt",
    ".md": "txt",
}

_MIME_TO_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/webp": "webp",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/csv": "csv",
    "application/csv": "csv",
    "text/plain": "txt",
}

_MAGIC_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"%PDF-", "pdf"),
    (b"PK\x03\x04", "zip"),
)


def _sniff_magic(path: Path) -> str | None:
    with path.open("rb") as stream:
        head = stream.read(32)
    for signature, media_type in _MAGIC_SIGNATURES:
        if head.startswith(signature):
            return media_type
    return None


def _zip_type(path: Path) -> str:
    name = path.name.lower()
    try:
        with zipfile.ZipFile(path) as archive:
            content_types = archive.read(
                "[Content_Types].xml"
            ).decode("utf-8", "ignore")
            if "wordprocessingml" in content_types:
                return "docx"
            if "spreadsheetml" in content_types:
                return "xlsx"
            names = {entry.filename.lower() for entry in archive.infolist()}
            if any(n.startswith("word/") for n in names):
                return "docx"
            if any(n.startswith("xl/") for n in names):
                return "xlsx"
    except (OSError, KeyError, zipfile.BadZipFile):
        pass
    return "docx" if name.endswith(".docx") else "xlsx"


def sniff_mime(path: str | Path) -> str | None:
    """Return a canonical type for a local file, or None if unsupported."""
    target = Path(path)
    if not target.exists() or not target.is_file():
        return None
    detected = _sniff_magic(target)
    if detected == "zip":
        return _zip_type(target)
    if detected is not None:
        return detected
    return _EXT_TO_TYPE.get(target.suffix.lower())


def normalize_type(mime_type: str | None, name: str = "") -> str | None:
    """Map a declared MIME string to a canonical type, or None to sniff."""
    if not mime_type:
        return None
    normalized = str(mime_type).strip().lower()
    if normalized in _MIME_TO_TYPE:
        return _MIME_TO_TYPE[normalized]
    if name:
        return _EXT_TO_TYPE.get(Path(name).suffix.lower())
    return None


def is_supported(media_type: str | None) -> bool:
    return media_type in SUPPORTED_TYPES
