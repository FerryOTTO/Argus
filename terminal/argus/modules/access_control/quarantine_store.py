'''Persistent quarantine store for access-control.'''

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_QUARANTINE_DIR = Path('runtime') / 'quarantine'
DEFAULT_QUARANTINE_FILENAME = 'quarantine.json'

_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.RLock] = {}

def _path_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.RLock())

def resolve_quarantine_path(path: str | Path | None = None) -> Path:
    configured: str | Path
    if path is not None:
        configured = path
    elif os.getenv('ARGUS_QUARANTINE_PATH'):
        configured = os.environ['ARGUS_QUARANTINE_PATH']
    else:
        configured = os.getenv('ARGUS_QUARANTINE_DIR', str(DEFAULT_QUARANTINE_DIR))
    dest = Path(configured).expanduser()
    if not dest.is_absolute():
        dest = PROJECT_ROOT / dest
    if dest.suffix.lower() != '.json':
        dest = dest / DEFAULT_QUARANTINE_FILENAME
    return dest

class QuarantineStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = resolve_quarantine_path(path)
        self._lock = _path_lock(self.path)
    def _load_unlocked(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8') or '{}')
            if isinstance(data, dict):
                return data
            return {}
        except Exception:
            return {}
    def _save_unlocked(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent))
        try:
            with open(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
    def is_quarantined(self, user_id: str) -> bool:
        with self._lock:
            data = self._load_unlocked()
            rec = data.get(user_id)
            return bool(rec and rec.get('active'))
    def get(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._load_unlocked()
            return data.get(user_id)
    def list_active(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load_unlocked()
            return [v for v in data.values() if v.get('active')]
    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load_unlocked()
            return list(data.values())
    def quarantine(self, user_id: str, reason: str, assessment: dict[str, Any] | None = None, *, by: str = 'system') -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        with self._lock:
            data = self._load_unlocked()
            existing = data.get(user_id)
            if existing and existing.get('active'):
                return existing
            rec = {
                'user_id': user_id,
                'quarantined_at': now,
                'reason': reason,
                'block_count': (assessment or {}).get('block_count', 0),
                'risk_score': (assessment or {}).get('risk_score', 0.0),
                'assessment': assessment or {},
                'quarantined_by': by,
                'active': True,
                'cleared_at': None,
                'cleared_by': None,
            }
            data[user_id] = rec
            self._save_unlocked(data)
            return rec
    def clear(self, user_id: str, *, by: str = 'admin') -> bool:
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        with self._lock:
            data = self._load_unlocked()
            rec = data.get(user_id)
            if not rec or not rec.get('active'):
                return False
            rec['active'] = False
            rec['cleared_at'] = now
            rec['cleared_by'] = by
            self._save_unlocked(data)
            return True
    def clear_all(self) -> int:
        with self._lock:
            data = self._load_unlocked()
            cnt = sum(1 for v in data.values() if v.get('active'))
            for v in data.values():
                if v.get('active'):
                    v['active'] = False
                    v['cleared_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
                    v['cleared_by'] = 'admin'
            self._save_unlocked(data)
            return cnt
