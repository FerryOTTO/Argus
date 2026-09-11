"""Persistent operator risk-review overrides derived beside the Audit JSONL."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import resolve_audit_path


REVIEW_SCHEMA_VERSION = 1
_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.RLock] = {}


class AuditRiskReviewError(ValueError):
    """Raised when the operator-review sidecar cannot be trusted."""


def _path_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.RLock())


def resolve_risk_review_path(
    path: str | Path | None = None,
    *,
    audit_path: str | Path | None = None,
) -> Path:
    """Resolve a sidecar path without modifying the raw AuditEvent JSONL."""

    configured = path or os.getenv("ARGUS_AUDIT_RISK_REVIEW_PATH")
    if configured:
        destination = Path(configured).expanduser()
        if not destination.is_absolute():
            destination = resolve_audit_path(audit_path).parent / destination
        return destination
    source = resolve_audit_path(audit_path)
    return source.with_name(f"{source.stem}.risk-reviews.json")


class AuditRiskReviewStore:
    """Atomically store effective-risk overrides keyed by real event_id."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        audit_path: str | Path | None = None,
    ) -> None:
        self.path = resolve_risk_review_path(path, audit_path=audit_path)
        self._lock = _path_lock(self.path)

    def load(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return self._load_unlocked()

    def dismissed_event_ids(self, trace_id: str | None = None) -> set[str]:
        return {
            event_id
            for event_id, review in self.load().items()
            if review.get("dismissed") is True
            and (trace_id is None or review.get("trace_id") == trace_id)
        }

    def set_dismissed(
        self,
        *,
        event_id: str,
        trace_id: str,
        dismissed: bool,
    ) -> dict[str, Any]:
        event_id = event_id.strip()
        trace_id = trace_id.strip()
        if not event_id or not trace_id:
            raise ValueError("event_id and trace_id must be non-empty")
        with self._lock:
            reviews = self._load_unlocked()
            if dismissed:
                reviews[event_id] = {
                    "event_id": event_id,
                    "trace_id": trace_id,
                    "dismissed": True,
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                reviews.pop(event_id, None)
            self._write_unlocked(reviews)
            return reviews.get(
                event_id,
                {
                    "event_id": event_id,
                    "trace_id": trace_id,
                    "dismissed": False,
                    "reviewed_at": None,
                },
            )

    def _load_unlocked(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuditRiskReviewError("audit risk review data is invalid") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != REVIEW_SCHEMA_VERSION:
            raise AuditRiskReviewError("audit risk review schema is invalid")
        raw_reviews = payload.get("reviews")
        if not isinstance(raw_reviews, dict):
            raise AuditRiskReviewError("audit risk review records are invalid")
        reviews: dict[str, dict[str, Any]] = {}
        for event_id, review in raw_reviews.items():
            if not isinstance(event_id, str) or not event_id or not isinstance(review, dict):
                raise AuditRiskReviewError("audit risk review record is invalid")
            if review.get("event_id") != event_id:
                raise AuditRiskReviewError("audit risk review event_id mismatch")
            trace_id = review.get("trace_id")
            if not isinstance(trace_id, str) or not trace_id:
                raise AuditRiskReviewError("audit risk review trace_id is invalid")
            if review.get("dismissed") is not True:
                raise AuditRiskReviewError("audit risk review state is invalid")
            reviewed_at = review.get("reviewed_at")
            if not isinstance(reviewed_at, str) or not reviewed_at:
                raise AuditRiskReviewError("audit risk review timestamp is invalid")
            reviews[event_id] = dict(review)
        return reviews

    def _write_unlocked(self, reviews: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        document = {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "reviews": {event_id: reviews[event_id] for event_id in sorted(reviews)},
        }
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
                json.dump(document, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
