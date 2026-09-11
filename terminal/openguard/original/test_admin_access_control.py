# test_admin_access_control.py — OpenGuard Admin 访问控制与规则修改接口测试
import pytest
import os
import sys
import time
import uuid
from pathlib import Path
from fastapi.testclient import TestClient

DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DIR.parents[1]
if str(DIR) not in sys.path:
    sys.path.insert(0, str(DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import app
from auth import sign_access_token
from session_store import session_store
from rate_limiter import limiter


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _create_auth_headers(user_id: str, username: str, role: str, security_level: str):
    sid = "sess_" + uuid.uuid4().hex[:16]
    jti = uuid.uuid4().hex
    token = sign_access_token(
        user_id,
        username,
        role,
        security_level,
        jti,
        sid,
    )
    session_store._cache[sid] = {
        "session_id": sid,
        "user_id": user_id,
        "access_jti": jti,
        "created_at": int(time.time() * 1000),
        "expires_at": time.time() + 3600,
        "ip": "test",
    }
    return {"Authorization": f"Bearer {token}"}


import auth


@pytest.fixture(autouse=True)
def mock_agent_create(monkeypatch):
    async def fake_create_agent(user_id, username):
        from database import insert_agent
        agent_record = {
            "id": f"ua_{uuid.uuid4().hex[:8]}",
            "user_id": user_id,
            "agent_id": f"{user_id}-agent",
            "name": f"{username}'s Agent",
            "is_default": 1,
            "status": "active",
            "created_at": int(time.time() * 1000),
        }
        await insert_agent(agent_record)
        return agent_record

    monkeypatch.setattr(auth, "_create_default_agent", fake_create_agent)


@pytest.fixture(autouse=True)
def clear_rate_limits():
    limiter._windows.clear()


def test_admin_update_user_security_level(client):
    admin_h = _create_auth_headers("usr_admin_01", "super_admin", "admin", "top_secret")
    user_h = _create_auth_headers("usr_norm_01", "normal_user", "user", "internal")

    # 1. 注册一个测试用户
    uname = f"sec_user_{uuid.uuid4().hex[:6]}"
    reg = client.post("/auth/register", json={"username": uname, "password": "password123"})
    assert reg.status_code == 200, reg.text
    target_id = reg.json()["id"]

    # 2. 成功修改安全等级为 secret
    res = client.put(
        f"/api/admin/users/{target_id}/security_level",
        json={"security_level": "secret"},
        headers=admin_h,
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["security_level"] == "secret"

    # 验证 GET /api/admin/users 列表中该用户的 security_level
    users_res = client.get("/api/admin/users", headers=admin_h)
    assert users_res.status_code == 200
    matched = [u for u in users_res.json() if u["id"] == target_id]
    assert len(matched) == 1
    assert matched[0]["security_level"] == "secret"

    # 3. 传入无效等级应当报错 422
    res_err = client.put(
        f"/api/admin/users/{target_id}/security_level",
        json={"security_level": "invalid_level"},
        headers=admin_h,
    )
    assert res_err.status_code == 422

    # 4. 普通用户尝试修改应当报 403
    res_forbidden = client.put(
        f"/api/admin/users/{target_id}/security_level",
        json={"security_level": "top_secret"},
        headers=user_h,
    )
    assert res_forbidden.status_code == 403


def test_admin_get_rules(client):
    admin_h = _create_auth_headers("usr_admin_01", "super_admin", "admin", "top_secret")
    res = client.get("/api/admin/rules", headers=admin_h)
    assert res.status_code == 200, res.text
    data = res.json()
    assert "users" in data
    assert "resources" in data
    assert "quarantine" in data
    assert isinstance(data["users"], list)
    assert isinstance(data["resources"], list)


def test_admin_user_rule_crud(client):
    admin_h = _create_auth_headers("usr_admin_01", "super_admin", "admin", "top_secret")

    # 1. 添加用户规则
    add_res = client.post(
        "/api/admin/rules/users",
        json={
            "user_id": "test_ac_user_99",
            "level": "secret",
            "specials": ["!tool:write_file", "tool:query_weather"],
        },
        headers=admin_h,
    )
    assert add_res.status_code == 200, add_res.text
    assert add_res.json()["success"] is True

    # 2. 获取规则列表中应该包含新增的用户规则
    rules_res = client.get("/api/admin/rules", headers=admin_h)
    users = rules_res.json()["users"]
    matched = [u for u in users if u["user_id"] == "test_ac_user_99"]
    assert len(matched) == 1
    assert matched[0]["level"] == 3  # secret normalized to 3
    assert "!tool:write_file" in matched[0]["specials"]

    # 3. 删除用户规则
    del_res = client.delete(
        "/api/admin/rules/users/test_ac_user_99",
        headers=admin_h,
    )
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True


def test_admin_resource_rule_crud(client):
    admin_h = _create_auth_headers("usr_admin_01", "super_admin", "admin", "top_secret")

    # 1. 添加资源规则
    add_res = client.post(
        "/api/admin/rules/resources",
        json={
            "pattern": "tool:unit_test_tool",
            "required_level": "top_secret",
            "inherit_mode": "flat",
        },
        headers=admin_h,
    )
    assert add_res.status_code == 200, add_res.text
    assert add_res.json()["success"] is True

    # 2. 检查资源规则列表
    rules_res = client.get("/api/admin/rules", headers=admin_h)
    resources = rules_res.json()["resources"]
    matched = [r for r in resources if r["pattern"] == "tool:unit_test_tool"]
    assert len(matched) == 1
    assert matched[0]["required_level"] == 4

    # 3. 删除资源规则
    del_res = client.delete(
        "/api/admin/rules/resources/tool:unit_test_tool",
        headers=admin_h,
    )
    assert del_res.status_code == 200


def test_admin_rules_reload(client):
    admin_h = _create_auth_headers("usr_admin_01", "super_admin", "admin", "top_secret")
    res = client.post("/api/admin/rules/reload", headers=admin_h)
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_missing_admin_api_returns_json_not_html(client):
    """确保不存在的 /api/admin/ 接口返回 404 JSON 而非回落到 OpenClaw SPA 返回 HTML"""
    admin_h = _create_auth_headers("usr_admin_01", "super_admin", "admin", "top_secret")
    res = client.get("/api/admin/non_existent_endpoint_xyz", headers=admin_h)
    assert res.status_code == 404
    assert res.headers.get("content-type", "").startswith("application/json")
    data = res.json()
    assert "detail" in data


def test_admin_quarantine_and_audit(client):
    admin_h = _create_auth_headers("usr_admin_01", "super_admin", "admin", "top_secret")

    # 清空隔离
    q_res = client.post("/api/admin/rules/quarantine/clear_all", headers=admin_h)
    assert q_res.status_code == 200
    assert q_res.json()["success"] is True

    # 清空审计
    audit_res = client.post("/api/admin/rules/clear_audit", headers=admin_h)
    assert audit_res.status_code == 200
    assert audit_res.json()["success"] is True


def test_user_registration_and_deletion_sync_to_ac(client):
    """测试用户注册自动同步到 AC 规则库，用户删除自动从 AC 规则库清理"""
    from argus.modules.access_control.original import auth_gateway
    admin_h = _create_auth_headers("usr_admin_01", "super_admin", "admin", "top_secret")

    # 1. 注册新用户
    uname = f"sync_u_{uuid.uuid4().hex[:6]}"
    reg = client.post("/auth/register", json={"username": uname, "password": "password123"})
    assert reg.status_code == 200, reg.text
    user_id = reg.json()["id"]

    # 验证规则库中自动包含该用户的 user_id 和 username
    store = auth_gateway._store
    assert store.get_user_level(user_id) == 2  # internal
    assert store.get_user_level(uname) == 2    # internal

    # 2. 删除用户
    del_res = client.delete(f"/api/admin/users/{user_id}", headers=admin_h)
    assert del_res.status_code == 200

    # 验证规则库已自动清理
    assert store.get_user_level(user_id) is None
    assert store.get_user_level(uname) is None
