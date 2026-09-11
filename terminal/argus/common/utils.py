"""不依赖具体安全模块的公共小工具。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def utc_now_iso() -> str:
    """返回带时区的 UTC ISO 8601 时间。"""

    return datetime.now(timezone.utc).isoformat()


def generate_trace_id() -> str:
    """生成一次完整请求使用的链路 ID。"""

    return f"trace-{uuid4().hex}"


def generate_event_id() -> str:
    """生成审计事件 ID。"""

    return f"event-{uuid4().hex}"
