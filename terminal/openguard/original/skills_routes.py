# skills_routes.py — 技能系统：定义目录（公有/私有）+ 安装关系（指针）
#
# 数据模型（对齐需求）：
#   skills        技能定义，内容只存一次；visibility 区分 public/private，
#                 owner_user_id 私有必填、公有 NULL
#   agent_skills  安装关系，skill_id 指向定义（安装不复制内容）
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from config import config
from middleware import auth_middleware, admin_required
from database import (
    upsert_agent_skill, list_user_skills, list_all_skills,
    find_agent_skill, remove_agent_skill, delete_skill_by_id,
    verify_agent_owned_by_user, find_agent_by_user,
    create_skill_definition, find_skill_by_id, find_skill_by_owner_name,
    find_public_skill_by_name, list_skill_catalog, update_skill_definition,
    delete_skill_definition, count_installs_by_skill, list_all_skill_definitions,
    list_agents_by_skill,
)

router = APIRouter()

import uuid as _uuid
import time as _time
import hashlib as _hashlib

_now_ms = lambda: int(_time.time() * 1000)
_skill_id = lambda: "sk_" + _uuid.uuid4().hex[:20]
_skill_hash = lambda content: _hashlib.sha256((content or "").encode("utf-8")).hexdigest()

# 技能名必须可安全作为目录名（防路径穿越）
SKILL_NAME_RE = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"


def _skill_markdown(name: str, description: str | None, content: str | None) -> str:
    """生成/规范化 SKILL.md 内容：有内容用内容，无内容生成最小可用 SKILL.md。"""
    c = (content or "").strip()
    if c:
        return c + "\n"
    desc = (description or name).strip()
    return f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n\n{desc}\n"


def _bridge_http() -> str:
    return config.bridge_url.replace("ws://", "http://").replace("wss://", "https://").rstrip("/")


async def _bridge_write_skill(agent_id: str, skill_name: str, content: str) -> None:
    """通过 Bridge 把 SKILL.md 写入 agent 工作区 skills/<name>/SKILL.md。"""
    rel_path = f"skills/{quote(skill_name, safe='')}/SKILL.md"
    url = f"{_bridge_http()}/api/agents/{quote(agent_id, safe='')}/files/{rel_path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.put(url, headers={"X-Bridge-Token": config.bridge_token},
                                json={"content": content})
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Bridge 写入失败: {resp.text[:200]}")


async def _bridge_delete_skill(agent_id: str, skill_name: str) -> None:
    """通过 Bridge 删除 agent 工作区 skills/<name>/ 目录。"""
    rel_path = f"skills/{quote(skill_name, safe='')}"
    url = f"{_bridge_http()}/api/agents/{quote(agent_id, safe='')}/files/{rel_path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.delete(url, headers={"X-Bridge-Token": config.bridge_token})
        if resp.status_code not in (200, 404):
            raise HTTPException(status_code=502, detail=f"Bridge 删除失败: {resp.text[:200]}")


async def _delete_skill_files_best_effort(agent_ids: list[str], skill_name: str) -> None:
    """尽力清理多个 agent 工作区里的技能目录，失败仅告警不阻断。"""
    for aid in agent_ids:
        try:
            await _bridge_delete_skill(aid, skill_name)
        except Exception as e:
            print(f"[Skills] 清理 {aid}/{skill_name} 文件失败: {e}")


class SkillCreate(BaseModel):
    skill_name: str = Field(pattern=SKILL_NAME_RE)
    description: Optional[str] = None
    source: str = "custom"
    version: Optional[str] = None
    content: Optional[str] = None


class SkillUpdate(BaseModel):
    description: Optional[str] = None
    version: Optional[str] = None


class SkillDefinitionUpdate(BaseModel):
    description: Optional[str] = None
    version: Optional[str] = None
    content: Optional[str] = None


# ======================================================================
# 用户侧 — 技能定义目录（公有 + 我的私有）
# ======================================================================

@router.get("/api/skills/catalog")
async def api_skill_catalog(request: Request):
    """浏览目录：所有公有技能 + 我的私有技能，标注是否已安装到默认 agent 及安装热度。"""
    user = await auth_middleware(request)
    skills = await list_skill_catalog(user.user_id)
    agent = await find_agent_by_user(user.user_id)
    counts = await count_installs_by_skill()
    out = []
    for s in skills:
        installed = False
        if agent:
            installed = bool(await find_agent_skill(agent["agent_id"], s["name"]))
        out.append({
            "skill_id": s["id"],
            "name": s["name"],
            "description": s.get("description"),
            "version": s.get("version"),
            "visibility": s.get("visibility", "private"),
            "owner_user_id": s.get("owner_user_id"),
            "installed": installed,
            "install_count": counts.get(s["id"], 0),
            "created_at": s["created_at"],
            "updated_at": s.get("updated_at"),
        })
    return out


@router.get("/api/skills/catalog/{skill_id}")
async def api_get_skill_definition(skill_id: str, request: Request):
    """查看单个技能定义（含内容）。公有任意用户可见，私有仅 owner 可见。"""
    user = await auth_middleware(request)
    skill = await find_skill_by_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.get("visibility") == "private" and skill.get("owner_user_id") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your private skill")
    return {
        "skill_id": skill["id"],
        "name": skill["name"],
        "description": skill.get("description"),
        "version": skill.get("version"),
        "content": skill.get("content"),
        "visibility": skill.get("visibility", "private"),
        "owner_user_id": skill.get("owner_user_id"),
        "created_at": skill["created_at"],
        "updated_at": skill.get("updated_at"),
    }


@router.put("/api/skills/catalog/{skill_id}")
async def api_update_skill_definition(skill_id: str, body: SkillDefinitionUpdate, request: Request):
    """编辑我的私有技能定义（description/version/content；name 为稳定键不可改）。"""
    user = await auth_middleware(request)
    skill = await find_skill_by_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.get("visibility") != "private" or skill.get("owner_user_id") != user.user_id:
        raise HTTPException(status_code=403, detail="只能编辑自己的私有技能")
    await update_skill_definition(
        skill_id, description=body.description, version=body.version, content=body.content)
    return {"ok": True, "skill_id": skill_id}


@router.get("/api/skills")
async def api_list_my_skills(request: Request):
    """返回当前用户所有已安装技能（安装记录）。"""
    user = await auth_middleware(request)
    return await list_user_skills(user.user_id)


@router.post("/api/skills")
async def api_add_skill(body: SkillCreate, request: Request):
    """新增一个私有技能：写入定义目录（同 owner+name 只存一份）并安装到默认 agent。"""
    user = await auth_middleware(request)
    agent = await find_agent_by_user(user.user_id)
    if not agent:
        raise HTTPException(status_code=400, detail="No default agent found")

    # 内容落盘到 agent 工作区（先写文件，失败则本次安装不生效）
    md = _skill_markdown(body.skill_name, body.description, body.content)
    await _bridge_write_skill(agent["agent_id"], body.skill_name, md)

    now = _now_ms()
    # 定义层：同 owner 同名只存一份（内容更新即覆盖）
    existing = await find_skill_by_owner_name(user.user_id, body.skill_name)
    if existing:
        skill_id = existing["id"]
        await update_skill_definition(
            skill_id, description=body.description,
            version=body.version, content=body.content)
    else:
        skill_id = _skill_id()
        await create_skill_definition({
            "id": skill_id,
            "name": body.skill_name,
            "description": body.description,
            "version": body.version,
            "content": body.content,
            "content_hash": _skill_hash(body.content),
            "visibility": "private",
            "owner_user_id": user.user_id,
            "created_at": now,
            "updated_at": now,
        })

    # 安装关系（指针）
    await upsert_agent_skill(
        user.user_id, agent["agent_id"], body.skill_name,
        source=body.source, version=body.version,
        content_hash=_skill_hash(body.content), skill_id=skill_id)

    return {"ok": True, "skill_id": skill_id, "skill_name": body.skill_name,
            "agent_id": agent["agent_id"]}


@router.post("/api/skills/catalog/{skill_id}/install")
async def api_install_skill(skill_id: str, request: Request):
    """安装目录中的技能到默认 agent（公有任意用户可装，私有仅 owner 可装）。"""
    user = await auth_middleware(request)
    skill = await find_skill_by_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.get("visibility") == "private" and skill.get("owner_user_id") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your private skill")
    agent = await find_agent_by_user(user.user_id)
    if not agent:
        raise HTTPException(status_code=400, detail="No default agent found")

    # 内容落盘到 agent 工作区
    md = _skill_markdown(skill["name"], skill.get("description"), skill.get("content"))
    await _bridge_write_skill(agent["agent_id"], skill["name"], md)

    await upsert_agent_skill(
        user.user_id, agent["agent_id"], skill["name"],
        source="catalog", version=skill.get("version"),
        content_hash=skill.get("content_hash"), skill_id=skill["id"])
    return {"ok": True, "skill_id": skill_id, "agent_id": agent["agent_id"]}


@router.delete("/api/skills/catalog/{skill_id}")
async def api_delete_skill_definition(skill_id: str, request: Request):
    """删除我的私有技能定义（公有技能由管理员管理）。"""
    user = await auth_middleware(request)
    skill = await find_skill_by_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.get("visibility") != "private" or skill.get("owner_user_id") != user.user_id:
        raise HTTPException(status_code=403, detail="只能删除自己的私有技能")
    # 清理已安装到各 agent 工作区的文件，再级联删除定义与安装记录
    agent_ids = await list_agents_by_skill(skill_id)
    await _delete_skill_files_best_effort(agent_ids, skill["name"])
    await delete_skill_definition(skill_id)
    return {"ok": True}


@router.put("/api/skills/{skill_name}")
async def api_update_skill(skill_name: str, body: SkillUpdate, request: Request):
    """更新技能（安装记录版本/描述）。"""
    user = await auth_middleware(request)
    agent = await find_agent_by_user(user.user_id)
    if not agent:
        raise HTTPException(status_code=400, detail="No default agent found")
    existing = await find_agent_skill(agent["agent_id"], skill_name)
    if not existing:
        raise HTTPException(status_code=404, detail="Skill not found")
    await upsert_agent_skill(
        user.user_id, agent["agent_id"], skill_name,
        source=existing.get("skill_source", "custom"),
        version=body.version or existing.get("installed_version"),
        skill_id=existing.get("skill_id"))
    return {"ok": True, "skill_name": skill_name}


@router.delete("/api/skills/{skill_name}")
async def api_delete_skill(skill_name: str, request: Request):
    """删除一条技能安装记录（并从 agent 工作区删除文件）。"""
    user = await auth_middleware(request)
    agent = await find_agent_by_user(user.user_id)
    if not agent:
        raise HTTPException(status_code=400, detail="No default agent found")
    if not await verify_agent_owned_by_user(agent["agent_id"], user.user_id):
        raise HTTPException(status_code=403, detail="Not your agent")
    # 尽力删除工作区文件，失败不阻断 DB 记录删除
    try:
        await _bridge_delete_skill(agent["agent_id"], skill_name)
    except Exception as e:
        print(f"[Skills] 删除 {skill_name} 文件失败（忽略）: {e}")
    ok = await remove_agent_skill(agent["agent_id"], skill_name)
    if not ok:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"ok": True}


# ======================================================================
# 管理员侧 — 公有技能定义 + 全局安装记录管理
# ======================================================================

admin_router = APIRouter(prefix="/api/admin/skills")


class PublicSkillCreate(BaseModel):
    skill_name: str = Field(pattern=SKILL_NAME_RE)
    description: Optional[str] = None
    version: Optional[str] = None
    content: Optional[str] = None


@admin_router.post("")
async def admin_create_public_skill(body: PublicSkillCreate, request: Request):
    """创建/更新一个公有技能定义（内容只存一次）。"""
    await admin_required(request)
    now = _now_ms()
    existing = await find_public_skill_by_name(body.skill_name)
    if existing:
        await update_skill_definition(
            existing["id"], description=body.description,
            version=body.version, content=body.content)
        return {"ok": True, "skill_id": existing["id"], "name": body.skill_name}
    skill_id = _skill_id()
    await create_skill_definition({
        "id": skill_id, "name": body.skill_name,
        "description": body.description, "version": body.version,
        "content": body.content, "content_hash": _skill_hash(body.content),
        "visibility": "public", "owner_user_id": None,
        "created_at": now, "updated_at": now,
    })
    return {"ok": True, "skill_id": skill_id, "name": body.skill_name}


@admin_router.get("/catalog")
async def admin_list_definitions(request: Request):
    """列出所有技能定义（公有 + 全部私有），带安装次数。"""
    await admin_required(request)
    defs = await list_all_skill_definitions()
    counts = await count_installs_by_skill()
    out = []
    for s in defs:
        out.append({
            "skill_id": s["id"],
            "name": s["name"],
            "description": s.get("description"),
            "version": s.get("version"),
            "visibility": s.get("visibility", "private"),
            "owner_user_id": s.get("owner_user_id"),
            "install_count": counts.get(s["id"], 0),
            "created_at": s["created_at"],
            "updated_at": s.get("updated_at"),
        })
    return out


@admin_router.delete("/catalog/{skill_id}")
async def admin_delete_definition(skill_id: str, request: Request):
    """删除任意技能定义（公有或私有），级联删除安装记录。"""
    await admin_required(request)
    skill = await find_skill_by_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    # 清理各 agent 工作区的文件，再级联删除
    agent_ids = await list_agents_by_skill(skill_id)
    await _delete_skill_files_best_effort(agent_ids, skill["name"])
    await delete_skill_definition(skill_id)
    return {"ok": True, "skill_id": skill_id}


@admin_router.get("")
async def admin_list_all_skills(request: Request, user_id: Optional[str] = None):
    """列出所有用户的技能安装记录（可按 user_id 过滤）。"""
    await admin_required(request)
    if user_id:
        return await list_user_skills(user_id)
    return await list_all_skills()


@admin_router.delete("/{skill_id}")
async def admin_delete_skill(skill_id: str, request: Request):
    """按 ID 删除任意技能安装记录。"""
    await admin_required(request)
    ok = await delete_skill_by_id(skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Skill record not found")
    return {"ok": True}
