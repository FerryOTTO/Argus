"""Step 6: 本地技能文件接口（替代已下线的 Bridge :18080 文件端点）。

在本机直接写文件到 OpenClaw 工作区，不走网络：
  main            -> <state>/.openclaw/workspace/
  <agentId>       -> <state>/.openclaw/workspace-<agentId>/
与 bridge.js getAgentWorkspacePath/sanitizePath 语义一致，另加归属校验。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1/local/skills", tags=["local-skills"])

_AGENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_FILE_BYTES = 1 * 1024 * 1024  # 与 Bridge 的 1MB 上限对齐


def _state_dir() -> Path:
    for cand in (
        os.getenv("OPENCLAW_STATE_DIR"),
        os.getenv("OPENCLAW_HOME"),
    ):
        if cand and os.path.isdir(cand):
            return Path(cand)
    # 回落：随包的 openclaw-data（与 daemon.js openClawStateDir 一致）
    root = Path(__file__).resolve().parent.parent.parent
    bundled = root.parent / "openclaw-data"
    if bundled.is_dir():
        return bundled
    return Path(os.path.expanduser("~")) / ".openclaw"


def _workspace_root(agent_id: str) -> Path:
    state = _state_dir()
    if not agent_id or agent_id == "main":
        return state / ".openclaw" / "workspace"
    return state / ".openclaw" / f"workspace-{agent_id}"


def _sanitize(rel_path: str, root: Path) -> Optional[Path]:
    """防路径穿越：rel 必须严格落在 root 之内（与 bridge.js 一致）。"""
    try:
        root_res = root.resolve()
        abs_p = (root_res / (rel_path or "")).resolve()
        if abs_p == root_res:
            return None
        if not str(abs_p).startswith(str(root_res) + os.sep):
            return None
        return abs_p
    except Exception:
        return None


def _check_owner(agent_id: str, user_id: str) -> tuple[bool, str]:
    """归属校验：A 用户不能写 B 的 workspace。

    规则（与 users.txt agent 命名习惯对齐）：
    - agent_id == main：仅允许运维身份（desktop-local 或 top_secret 明示）写入；
    - agent_<x> / usr_<x>-agent / <uid>-agent：允许 user_id == <x> 或特例 '*' 写入；
    - 其余：仅允许 user_id == agent_id 写入。
    调用方需先用 access_control 查出 caller 的等级与特例，本函数只做字符串归属比对。
    """
    agent_id = (agent_id or "").strip()
    user_id = (user_id or "").strip()
    if not agent_id or not _AGENT_RE.match(agent_id):
        return False, "invalid agent_id"
    if not user_id:
        return False, "user_id required"
    if user_id == agent_id:
        return True, ""
    # 约定后缀：xxx-agent 归属 xxx
    if agent_id.endswith("-agent") and agent_id[: -len("-agent")] == user_id:
        return True, ""
    if agent_id.startswith("agent_") and agent_id[len("agent_"):] == user_id:
        return True, ""
    return False, f"user {user_id} is not the owner of workspace {agent_id}"


class SkillWriteBody(BaseModel):
    agent_id: str = "main"
    path: str = ""
    content: str = ""
    user_id: str = ""
    # caller 特例（'*' 可写 main workspace）；由服务端从 users 表填入，不信任客户端自报等级
    caller_specials: list[str] = []


@router.put("/files")
def skill_write(body: SkillWriteBody):
    agent_id = (body.agent_id or "main").strip()
    if not _AGENT_RE.match(agent_id):
        return {"ok": False, "detail": "invalid agent_id"}
    rel = (body.path or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        return {"ok": False, "detail": "path required"}
    if len((body.content or "").encode("utf-8")) > MAX_FILE_BYTES:
        return {"ok": False, "detail": "file too large (max 1MB)"}
    user_id = (body.user_id or "").strip()
    # main workspace 写保护：仅 caller 特例含 '*'（运维）可写
    if agent_id == "main":
        specials = [str(s).strip() for s in (body.caller_specials or [])]
        if "*" not in specials:
            return {"ok": False, "detail": "main workspace is protected: operator only"}
    else:
        ok, detail = _check_owner(agent_id, user_id)
        if not ok:
            return {"ok": False, "detail": detail}
    root = _workspace_root(agent_id)
    abs_p = _sanitize(rel, root)
    if abs_p is None:
        return {"ok": False, "detail": "invalid path"}
    try:
        abs_p.parent.mkdir(parents=True, exist_ok=True)
        abs_p.write_text(body.content or "", encoding="utf-8")
    except Exception as e:
        return {"ok": False, "detail": str(e)}
    return {"ok": True, "agent_id": agent_id, "path": rel}


class SkillDeleteBody(BaseModel):
    agent_id: str = "main"
    path: str = ""
    user_id: str = ""
    caller_specials: list[str] = []


@router.delete("/files")
def skill_delete(body: SkillDeleteBody):
    import shutil

    agent_id = (body.agent_id or "main").strip()
    if not _AGENT_RE.match(agent_id):
        return {"ok": False, "detail": "invalid agent_id"}
    rel = (body.path or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        return {"ok": False, "detail": "path required"}
    user_id = (body.user_id or "").strip()
    if agent_id == "main":
        specials = [str(s).strip() for s in (body.caller_specials or [])]
        if "*" not in specials:
            return {"ok": False, "detail": "main workspace is protected: operator only"}
    else:
        ok, detail = _check_owner(agent_id, user_id)
        if not ok:
            return {"ok": False, "detail": detail}
    root = _workspace_root(agent_id)
    abs_p = _sanitize(rel, root)
    if abs_p is None:
        return {"ok": False, "detail": "invalid path"}
    try:
        if not abs_p.exists() and not abs_p.is_symlink():
            return {"ok": False, "detail": "not found"}
        if abs_p.is_dir() and not abs_p.is_symlink():
            shutil.rmtree(abs_p)
        else:
            abs_p.unlink()
    except Exception as e:
        return {"ok": False, "detail": str(e)}
    return {"ok": True, "agent_id": agent_id, "path": rel}


@router.get("/workspace")
def skill_workspace(agent_id: str = "main"):
    """只返回解析后的目录（不列文件内容），供前端展示落点。"""
    agent_id = (agent_id or "main").strip()
    if not _AGENT_RE.match(agent_id):
        return {"ok": False, "detail": "invalid agent_id"}
    return {"ok": True, "agent_id": agent_id, "root": str(_workspace_root(agent_id))}
