"""Tool Guard 会话状态存储:按 session_id 维护用户原始意图与已执行工具链。

数据流:
- OpenClaw 在收到用户输入时调用 ``POST /v1/tool/session/prompt`` 写入原始 prompt;
- OpenClaw 在工具执行完成后调用 ``POST /v1/tool/session/call`` 追加一条工具调用;
- ``/v1/tool/pre_check`` 时 ToolGuardAdapter 读取本存储,把 prompt + 工具链交给
  意图匹配裁判打分,无需请求方重复传递。

设计说明:
- 线程安全(单进程 FastAPI 内使用 RLock);
- 工具链长度有上限,超出后丢弃最旧记录并标记截断;
- 会话有 TTL,长时间无访问自动清理,防止内存泄漏;
- 只记录工具名与参数摘要(长文本截断),不保存工具返回内容——
  工具返回内容属于输出端(MELON)检测范围,不进入裁判输入。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

MAX_CHAIN_LEN = 128
MAX_ARG_VALUE_LEN = 120
SESSION_TTL_SECONDS = 30 * 60


def summarize_arguments(arguments: Any) -> dict[str, str]:
    """把工具参数压缩成适合送入裁判的摘要:只保留键名与截断后的标量值。"""
    if not isinstance(arguments, dict):
        return {}
    summary: dict[str, str] = {}
    for key, value in arguments.items():
        if isinstance(value, str):
            text = value if len(value) <= MAX_ARG_VALUE_LEN else value[:MAX_ARG_VALUE_LEN] + "..."
        elif isinstance(value, (int, float, bool)) or value is None:
            text = str(value)
        else:
            text = type(value).__name__
        summary[str(key)] = text
    return summary


@dataclass
class ToolSession:
    """一个会话的意图锚点与工具链。"""

    session_id: str
    original_prompt: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    verdicts: list[dict[str, Any]] = field(default_factory=list)
    chain_truncated: bool = False
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def set_prompt(self, prompt: str) -> None:
        self.original_prompt = prompt
        self.touch()

    def record_call(self, tool_name: str, arguments: Any, max_chain_len: int = MAX_CHAIN_LEN) -> None:
        entry = {
            "tool_name": tool_name,
            "arguments": summarize_arguments(arguments),
            "timestamp": time.time(),
        }
        if len(self.tool_calls) >= max_chain_len:
            self.tool_calls.pop(0)
            self.chain_truncated = True
        self.tool_calls.append(entry)
        self.touch()

    def record_verdict(
        self,
        tool_name: str,
        arguments: Any,
        score: float,
        reason: str,
        deviation: str,
        action: str,
    ) -> None:
        """记录一次意图匹配判定反馈,供复盘工具链意图漂移与劫持过程。"""
        self.verdicts.append(
            {
                "tool_name": tool_name,
                "arguments": summarize_arguments(arguments),
                "score": round(float(score), 4),
                "reason": reason,
                "deviation": deviation,
                "action": action,
                "timestamp": time.time(),
            }
        )
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "original_prompt": self.original_prompt,
            "tool_chain": list(self.tool_calls),
            "verdicts": list(self.verdicts),
            "chain_truncated": self.chain_truncated,
            "updated_at": self.updated_at,
        }


class ToolSessionStore:
    """线程安全的会话存储,带 TTL 惰性清理。"""

    def __init__(
        self,
        ttl_seconds: float = SESSION_TTL_SECONDS,
        max_chain_len: int = MAX_CHAIN_LEN,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_chain = max_chain_len
        self._sessions: dict[str, ToolSession] = {}
        self._lock = threading.RLock()

    def set_prompt(self, session_id: str, prompt: str) -> ToolSession:
        session = self._get_or_create(session_id)
        session.set_prompt(prompt)
        return session

    def record_call(self, session_id: str, tool_name: str, arguments: Any) -> ToolSession:
        session = self._get_or_create(session_id)
        session.record_call(tool_name, arguments, self._max_chain)
        return session

    def record_verdict(
        self,
        session_id: str,
        tool_name: str,
        arguments: Any,
        score: float,
        reason: str,
        deviation: str,
        action: str,
    ) -> ToolSession | None:
        """把一次意图判定反馈写回会话;会话不存在时返回 None。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or self._expired(session):
                return None
            session.record_verdict(tool_name, arguments, score, reason, deviation, action)
            return session

    def list_sessions(self) -> list[ToolSession]:
        """返回全部未过期会话(按最近活跃时间倒序)。"""
        with self._lock:
            expired = [sid for sid, session in self._sessions.items() if self._expired(session)]
            for sid in expired:
                self._sessions.pop(sid, None)
            sessions = sorted(
                self._sessions.values(), key=lambda s: s.updated_at, reverse=True
            )
            return list(sessions)

    def get(self, session_id: str) -> ToolSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._expired(session):
                self._sessions.pop(session_id, None)
                return None
            return session

    def get_or_create(self, session_id: str) -> ToolSession:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or self._expired(session):
                session = ToolSession(session_id=session_id)
                self._sessions[session_id] = session
            return session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def cleanup_expired(self) -> int:
        """清理全部过期会话,返回清理数量。"""
        with self._lock:
            expired = [sid for sid, session in self._sessions.items() if self._expired(session)]
            for sid in expired:
                self._sessions.pop(sid, None)
            return len(expired)

    def _get_or_create(self, session_id: str) -> ToolSession:
        with self._lock:
            return self.get_or_create(session_id)

    def _expired(self, session: ToolSession) -> bool:
        return time.time() - session.updated_at > self._ttl


# 全局单例:启动期可替换注入,便于测试
store = ToolSessionStore()


def set_store(new_store: ToolSessionStore) -> None:
    """测试或定制化时替换全局存储。"""
    global store
    store = new_store
