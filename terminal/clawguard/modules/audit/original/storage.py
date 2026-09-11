"""Validated, append-only JSONL storage for Clawguard AuditEvent records."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from clawguard.common.models import AuditEvent


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_AUDIT_DIR = Path("runtime") / "audit"
DEFAULT_AUDIT_FILENAME = "audit-events.jsonl"
DEFAULT_RISK_THRESHOLD = 0.5

_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.RLock] = {}


class AuditJsonlError(ValueError):
    """Line-aware JSONL or AuditEvent validation failure."""

    def __init__(self, path: Path, line_number: int, detail: str) -> None:
        self.path = path
        self.line_number = line_number
        self.detail = detail
        super().__init__(f"{path}: line {line_number}: {detail}")


def _path_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.RLock())


def resolve_audit_path(path: str | Path | None = None) -> Path:
    """Resolve a configured file or directory without hard-coded host paths."""

    configured: str | Path
    if path is not None:
        configured = path
    elif os.getenv("CLAWGUARD_AUDIT_PATH"):
        configured = os.environ["CLAWGUARD_AUDIT_PATH"]
    else:
        configured = os.getenv("CLAWGUARD_AUDIT_DIR", str(DEFAULT_AUDIT_DIR))

    destination = Path(configured).expanduser()
    if not destination.is_absolute():
        destination = PROJECT_ROOT / destination
    if destination.suffix.lower() != ".jsonl":
        destination /= DEFAULT_AUDIT_FILENAME
    return destination


def parse_timestamp(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def normalize_audit_event(event: Mapping[str, Any] | AuditEvent) -> dict[str, Any]:
    """Revalidate with the team model and return a JSON-compatible copy."""

    model = event if isinstance(event, AuditEvent) else AuditEvent.model_validate(event)
    normalized = model.model_dump(mode="json")
    for field in ("event_id", "trace_id", "stage", "source_module", "action"):
        value = normalized[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
    parse_timestamp(normalized["timestamp"])
    return normalized


def get_risk_threshold(value: float | str | None = None) -> float:
    raw: float | str = (
        value
        if value is not None
        else os.getenv(
            "CLAWGUARD_AUDIT_RISK_THRESHOLD", str(DEFAULT_RISK_THRESHOLD)
        )
    )
    try:
        threshold = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("audit risk threshold must be a number in [0, 1]") from exc
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("audit risk threshold must be in [0, 1]")
    return threshold


def is_direct_risk_source(
    event: Mapping[str, Any] | AuditEvent,
    threshold: float | str | None = None,
) -> bool:
    normalized = normalize_audit_event(event)
    return float(normalized["risk_score"]) >= get_risk_threshold(threshold)


class AuditStore:
    """Append canonical AuditEvent JSON without database or background watcher."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = resolve_audit_path(path)
        self._lock = _path_lock(self.path)

    def append(self, event: Mapping[str, Any] | AuditEvent) -> dict[str, Any]:
        normalized = normalize_audit_event(event)
        encoded = (
            json.dumps(
                normalized,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        with self._lock:
            for line_number, existing in enumerate(self._load_unlocked(), start=1):
                if existing["event_id"] != normalized["event_id"]:
                    continue
                if existing == normalized:
                    return existing
                raise AuditJsonlError(
                    self.path,
                    line_number,
                    f"conflicting duplicate event_id: {normalized['event_id']}",
                )

            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch(exist_ok=True)
            original_size = self.path.stat().st_size
            try:
                with self.path.open("r+b") as stream:
                    stream.seek(0, os.SEEK_END)
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                if self.path.exists() and self.path.stat().st_size != original_size:
                    with self.path.open("r+b") as stream:
                        stream.truncate(original_size)
                        stream.flush()
                        os.fsync(stream.fileno())
                raise
        return normalized

    def load(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._load_unlocked()

    def delete_traces(self, trace_ids: set[str]) -> dict[str, Any]:
        """Atomically remove all events belonging to the requested traces."""

        requested = {trace_id.strip() for trace_id in trace_ids if trace_id.strip()}
        if not requested:
            return {
                "deleted_trace_ids": [],
                "missing_trace_ids": [],
                "deleted_event_count": 0,
            }

        with self._lock:
            events = self._load_unlocked()
            existing = {event["trace_id"] for event in events}
            deleted_trace_ids = sorted(requested & existing)
            missing_trace_ids = sorted(requested - existing)
            deleted = [event for event in events if event["trace_id"] in requested]
            if not deleted:
                return {
                    "deleted_trace_ids": deleted_trace_ids,
                    "missing_trace_ids": missing_trace_ids,
                    "deleted_event_count": 0,
                }

            retained = [event for event in events if event["trace_id"] not in requested]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="\n",
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    dir=self.path.parent,
                    delete=False,
                ) as stream:
                    temporary_path = Path(stream.name)
                    for event in retained:
                        stream.write(
                            json.dumps(
                                event,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_path, self.path)
                temporary_path = None
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

        return {
            "deleted_trace_ids": deleted_trace_ids,
            "missing_trace_ids": missing_trace_ids,
            "deleted_event_count": len(deleted),
        }

    def _load_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8-sig") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                if not raw_line.strip():
                    continue
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise AuditJsonlError(
                        self.path,
                        line_number,
                        f"invalid JSON at column {exc.colno}: {exc.msg}",
                    ) from exc
                try:
                    events.append(normalize_audit_event(payload))
                except (TypeError, ValueError) as exc:
                    raise AuditJsonlError(
                        self.path, line_number, f"invalid AuditEvent: {exc}"
                    ) from exc
        return events


def record_audit_event(
    event: Mapping[str, Any] | AuditEvent,
    *,
    path: str | Path | None = None,
    threshold: float | str | None = None,
) -> dict[str, Any]:
    """Public direct-call entry used by AuditAdapter."""

    normalized = normalize_audit_event(event)
    configured_threshold = get_risk_threshold(threshold)
    stored = AuditStore(path).append(normalized)
    return {
        "event_id": stored["event_id"],
        "trace_id": stored["trace_id"],
        "stored": True,
        "direct_risk_source": (
            float(stored["risk_score"]) >= configured_threshold
        ),
        "risk_threshold": configured_threshold,
    }
