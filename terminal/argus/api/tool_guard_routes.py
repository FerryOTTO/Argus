"""Tool Guard 管理界面与运行期查询接口。

提供:
- 会话查询:``GET /v1/tool/session`` / ``GET /v1/tool/session/{session_id}``
  (会话数据保存在内存 ``ToolSessionStore``,重启后清空);
- 清理过期会话:``POST /v1/tool/session/cleanup_expired``;
- 配置重置:``POST /v1/tool_guard/config/reset``(恢复内置默认值,仅内存生效);
- 管理页面:``GET /tool-guard``(依赖零、本地可访问的静态 HTML)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from argus.modules.tool_guard import session_store
from argus.modules.tool_guard.llm_config import ToolGuardLLMConfig

router = APIRouter()
UI_PATH = (
    Path(__file__).resolve().parents[1] / "modules" / "tool_guard" / "ui" / "index.html"
)


def _session_summary(session: session_store.ToolSession) -> dict[str, Any]:
    """会话列表项:不携带完整工具链,便于列表轻量展示。"""
    return {
        "session_id": session.session_id,
        "original_prompt": session.original_prompt,
        "tool_call_count": len(session.tool_calls),
        "verdict_count": len(session.verdicts),
        "chain_truncated": session.chain_truncated,
        "updated_at": session.updated_at,
    }


@router.get("/v1/tool/session")
def list_tool_sessions(
    keyword: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> dict[str, Any]:
    """返回全部未过期会话(按最近活跃时间倒序),支持 session_id/意图关键字搜索。"""

    sessions = session_store.store.list_sessions()
    keyword_lower = keyword.strip().lower()
    if keyword_lower:
        sessions = [
            session
            for session in sessions
            if keyword_lower in session.session_id.lower()
            or keyword_lower in session.original_prompt.lower()
        ]
    items = [_session_summary(session) for session in sessions[offset : offset + limit]]
    return {
        "items": items,
        "total": len(sessions),
        "limit": limit,
        "offset": offset,
    }


@router.get("/v1/tool/session/{session_id}")
def get_tool_session(session_id: str) -> dict[str, Any]:
    """返回单个会话完整详情(意图锚点、工具链、判定反馈)。"""

    session = session_store.store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "tool_session_not_found",
                "message": "Tool Guard 会话不存在或已过期。",
            },
        )
    return {"session": session.to_dict()}


@router.post("/v1/tool/session/cleanup_expired")
def cleanup_expired_sessions() -> dict[str, Any]:
    """清理全部过期会话,返回清理数量。"""

    cleaned = session_store.store.cleanup_expired()
    return {"status": "ok", "cleaned": cleaned}


@router.post("/v1/tool_guard/config/reset")
def reset_tool_guard_config() -> dict[str, Any]:
    """恢复 Tool Guard LLM 裁判的内置默认配置(仅内存生效)。"""

    return {"config": ToolGuardLLMConfig.instance().reset()}


@router.get("/tool-guard", include_in_schema=False)
def tool_guard_console() -> FileResponse:
    """提供 Tool Guard 本地管理界面(依赖零、无圆角、全中文)。"""

    return FileResponse(UI_PATH, media_type="text/html")
