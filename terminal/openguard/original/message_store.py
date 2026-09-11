# message_store.py — 聊天消息本地 JSONL 备份
import json
import time
from pathlib import Path

MESSAGE_DIR = Path(__file__).parent / "data" / "messages"


class MessageStore:
    """将聊天消息写入本地 JSONL 文件，按 user_id / session_key 组织"""

    def __init__(self):
        MESSAGE_DIR.mkdir(parents=True, exist_ok=True)

    def _ensure_user_dir(self, user_id: str) -> Path:
        user_dir = MESSAGE_DIR / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    async def save_message(self, user_id: str, session_key: str,
                           role: str, content: str) -> None:
        """写入一条消息到 JSONL 文件"""
        safe_key = session_key.replace(":", "_").replace("/", "_")
        path = self._ensure_user_dir(user_id) / f"{safe_key}.jsonl"
        record = {
            "role": role,
            "content": content,
            "timestamp": int(time.time() * 1000),
            "session_key": session_key,
        }
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 写入失败不影响主流程

    async def load_history(self, user_id: str, session_key: str,
                           limit: int = 200) -> list[dict]:
        """读取某个会话的历史消息"""
        safe_key = session_key.replace(":", "_").replace("/", "_")
        path = self._ensure_user_dir(user_id) / f"{safe_key}.jsonl"
        if not path.exists():
            return []
        messages = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        messages.append(json.loads(line))
                        if len(messages) >= limit:
                            break
        except Exception:
            pass
        return messages

    async def list_sessions(self, user_id: str) -> list[dict]:
        """列出某用户的所有本地会话"""
        user_dir = self._ensure_user_dir(user_id)
        sessions = []
        for f in sorted(user_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            # 从首条记录恢复真实 session_key（文件名里的 "_" 替换无法还原含下划线的原始 key）
            session_key = None
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    first = fh.readline().strip()
                    if first:
                        session_key = json.loads(first).get("session_key")
            except Exception:
                pass
            sessions.append({
                "session_key": session_key or f.stem,
                "file": f.name,
                "size": f.stat().st_size,
            })
        return sessions


message_store = MessageStore()
