# session_store.py — 会话白名单（JSON 文件持久化 + 内存缓存）
import json
import os
import time
from pathlib import Path

SESSION_DIR = Path(__file__).parent / "data" / "sessions"


class SessionStore:
    """统一会话存储接口：读写 JSON 文件，内存缓存加速 validate"""

    def __init__(self):
        self._cache: dict[str, dict] = {}
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    def _session_path(self, session_id: str) -> Path:
        return SESSION_DIR / f"{session_id}.json"

    def _load_from_disk(self) -> None:
        """启动时从磁盘恢复未过期会话到内存缓存"""
        now = time.time()
        loaded = 0
        for f in SESSION_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("expires_at", 0) > now:
                    self._cache[data["session_id"]] = data
                    loaded += 1
                else:
                    f.unlink(missing_ok=True)  # 删除过期文件
            except Exception:
                f.unlink(missing_ok=True)
        if loaded:
            print(f"[Session] Loaded {loaded} sessions from disk")

    async def create_session(self, session_id: str, user_id: str,
                             access_jti: str, ip: str, ttl: int = 900) -> None:
        data = {
            "session_id": session_id,
            "user_id": user_id,
            "access_jti": access_jti,
            "created_at": int(time.time() * 1000),
            "expires_at": time.time() + ttl,
            "ip": ip,
        }
        self._cache[session_id] = data
        try:
            self._session_path(session_id).write_text(json.dumps(data))
        except Exception:
            pass  # 磁盘写入失败不影响会话创建

    async def validate_session(self, session_id: str) -> bool:
        data = self._cache.get(session_id)
        if not data:
            # 尝试从磁盘加载（可能重启后内存丢失）
            try:
                path = self._session_path(session_id)
                if path.exists():
                    data = json.loads(path.read_text())
                    if data.get("expires_at", 0) > time.time():
                        self._cache[session_id] = data
                        return True
                    else:
                        path.unlink(missing_ok=True)
            except Exception:
                pass
            return False
        if time.time() > data.get("expires_at", 0):
            # 过期：清理内存和磁盘
            del self._cache[session_id]
            self._session_path(session_id).unlink(missing_ok=True)
            return False
        return True

    async def destroy_session(self, session_id: str) -> None:
        self._cache.pop(session_id, None)
        self._session_path(session_id).unlink(missing_ok=True)

    async def list_sessions(self) -> list[dict]:
        result = []
        now = time.time()
        for sid, data in list(self._cache.items()):
            if data.get("expires_at", 0) > now:
                result.append({"session_id": sid, "data": data})
            else:
                self._cache.pop(sid, None)
                self._session_path(sid).unlink(missing_ok=True)
        return result


session_store = SessionStore()
