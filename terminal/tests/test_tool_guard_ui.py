"""Argus — Tool Guard 管理界面与运行期查询接口测试

覆盖:
- 页面可访问性:``/tool-guard`` 返回 200、无外部资源、全中文、无圆角
- 页面功能元素:配置管理(脱敏/恢复默认/仅内存生效提示)、会话历史(搜索/清理)、
  调试预检、自动刷新
- 会话查询 API:列表、关键字搜索、详情、404、过期清理
- 配置更新链路:PUT 保存 → GET 脱敏回显 → 恢复内置默认
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argus.api.main import app
from argus.api.tool_guard_routes import router as tool_guard_router
from argus.modules.tool_guard import session_store
from argus.modules.tool_guard.llm_config import ToolGuardLLMConfig


CLIENT = TestClient(app)


@pytest.fixture
def isolated_store():
    """用独立的会话存储替换全局单例,测试结束后恢复。"""
    original = session_store.store
    store = session_store.ToolSessionStore(ttl_seconds=3600)
    session_store.set_store(store)
    yield store
    session_store.set_store(original)


@pytest.fixture
def preserved_config():
    """保存运行期配置的原始值,测试结束后恢复,避免污染其他用例。

    同时预置一个模拟 API key,用于验证脱敏展示与写入链路。
    """
    config = ToolGuardLLMConfig.instance()
    original = {key: config.get(key) for key in ToolGuardLLMConfig.defaults()}
    config.update({"api_key": "test-secret-key-123"})
    yield config
    config.update(original)


# ---------------------------------------------------------------------------
# 页面可访问性
# ---------------------------------------------------------------------------


def test_tool_guard_page_returns_200_without_external_resources():
    response = CLIENT.get("/tool-guard")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert not re.search(r"(?:src|href)=[\"']https?://", response.text, re.I)
    assert "cdn" not in response.text.lower()


def test_page_uses_no_rounded_corners():
    html = CLIENT.get("/tool-guard").text
    # 无圆角:只允许 border-radius 显式为零,不允许任何非零圆角/胶囊/拱形
    assert not re.search(r"border-radius\s*:\s*(?!0(?:px|\s|;|$))[^;]*", html)
    assert "border-radius:99px" not in html


def test_page_contains_three_tabs_in_chinese():
    html = CLIENT.get("/tool-guard").text
    assert "配置管理" in html
    assert "会话历史" in html
    assert "调试预检" in html


def test_page_contains_config_management_features():
    html = CLIENT.get("/tool-guard").text
    assert "LLM 意图裁判运行期配置" in html
    assert "Base URL" in html
    assert "模型名称" in html
    assert "阻断阈值" in html
    assert "复核阈值" in html
    assert "超时秒数" in html
    assert "审计回写地址" in html
    assert "保存配置" in html
    assert "恢复默认配置" in html
    assert "仅内存生效" in html
    assert "重启服务后回退到环境变量 / 配置文件中的值" in html
    assert "脱敏" in html
    assert "***" in html


def test_page_contains_session_history_features():
    html = CLIENT.get("/tool-guard").text
    assert "按会话 ID 或用户意图搜索" in html
    assert "每5秒自动刷新" in html
    assert "清理过期会话" in html
    assert "工具调用时间线" in html
    assert "会话详情" in html
    assert "判定反馈" in html
    assert "意图匹配分" in html
    assert "偏离点" in html
    assert "审计事件关联" in html
    assert "setInterval" in html
    assert "5000" in html


def test_page_contains_debug_precheck_features():
    html = CLIENT.get("/tool-guard").text
    assert "模拟一次工具执行前检查" in html
    assert "工具参数（JSON）" in html
    assert "执行预检" in html
    assert "权限检查（access_control）" in html
    assert "意图匹配裁判（tool_guard）" in html
    assert "最终动作" in html


def test_page_contains_loading_empty_error_and_state_preservation():
    html = CLIENT.get("/tool-guard").text
    assert "正在加载会话" in html
    assert "暂无会话" in html
    assert 'role="alert"' in html
    assert "刷新失败，保留上次数据" in html
    assert "selectedSessionId" in html
    assert "expandedKeys" in html


# ---------------------------------------------------------------------------
# 会话查询 API
# ---------------------------------------------------------------------------


def _seed_sessions(store: session_store.ToolSessionStore) -> None:
    store.set_prompt("session-a", "帮我查一下明天的北京天气")
    store.record_call("session-a", "web_search", {"query": "北京明天天气", "limit": 5})
    store.record_call("session-a", "web_fetch", {"url": "https://weather.example.com"})
    store.record_verdict("session-a", "web_search", {"query": "北京明天天气"},
                         score=0.95, reason="直接服务于查询天气意图",
                         deviation="", action="allow")
    store.set_prompt("session-b", "整理本地项目资料并输出报告")
    store.record_call("session-b", "read_file", {"path": "/tmp/a.txt"})


def test_list_sessions_returns_summaries(isolated_store):
    _seed_sessions(isolated_store)
    response = CLIENT.get("/v1/tool/session")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    items = {item["session_id"]: item for item in body["items"]}
    assert items["session-a"]["original_prompt"] == "帮我查一下明天的北京天气"
    assert items["session-a"]["tool_call_count"] == 2
    assert items["session-a"]["verdict_count"] == 1
    assert items["session-a"]["updated_at"] > 0
    # 列表项不携带完整工具链,保持轻量
    assert "tool_chain" not in items["session-a"]
    assert "verdicts" not in items["session-a"]


def test_list_sessions_supports_keyword_search(isolated_store):
    _seed_sessions(isolated_store)
    by_session = CLIENT.get("/v1/tool/session", params={"keyword": "session-b"}).json()
    assert by_session["total"] == 1
    assert by_session["items"][0]["session_id"] == "session-b"
    by_prompt = CLIENT.get("/v1/tool/session", params={"keyword": "天气"}).json()
    assert by_prompt["total"] == 1
    assert by_prompt["items"][0]["session_id"] == "session-a"
    none = CLIENT.get("/v1/tool/session", params={"keyword": "不存在的会话"}).json()
    assert none["total"] == 0
    assert none["items"] == []


def test_list_sessions_supports_pagination(isolated_store):
    _seed_sessions(isolated_store)
    first = CLIENT.get("/v1/tool/session", params={"limit": 1, "offset": 0}).json()
    assert len(first["items"]) == 1
    second = CLIENT.get("/v1/tool/session", params={"limit": 1, "offset": 1}).json()
    assert len(second["items"]) == 1
    assert first["items"][0]["session_id"] != second["items"][0]["session_id"]
    assert CLIENT.get("/v1/tool/session", params={"limit": 500}).status_code == 422


def test_get_session_detail_returns_full_payload(isolated_store):
    _seed_sessions(isolated_store)
    response = CLIENT.get("/v1/tool/session/session-a")
    assert response.status_code == 200
    session = response.json()["session"]
    assert session["original_prompt"] == "帮我查一下明天的北京天气"
    assert len(session["tool_chain"]) == 2
    assert session["tool_chain"][0]["tool_name"] == "web_search"
    assert session["tool_chain"][0]["arguments"]["query"] == "北京明天天气"
    assert len(session["verdicts"]) == 1
    verdict = session["verdicts"][0]
    assert verdict["tool_name"] == "web_search"
    assert verdict["score"] == 0.95
    assert verdict["action"] == "allow"
    assert verdict["reason"] == "直接服务于查询天气意图"
    assert verdict["deviation"] == ""
    assert "updated_at" in session


def test_get_session_detail_returns_404_for_missing(isolated_store):
    _seed_sessions(isolated_store)
    response = CLIENT.get("/v1/tool/session/unknown-session")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "tool_session_not_found"


def test_cleanup_expired_removes_only_stale_sessions():
    store = session_store.ToolSessionStore(ttl_seconds=0.1)
    store.set_prompt("stale", "过期会话")
    store.set_prompt("fresh", "活跃会话")
    time.sleep(0.2)
    store.set_prompt("fresh", "活跃会话更新")  # 重新计时
    session_store.set_store(store)
    try:
        response = CLIENT.post("/v1/tool/session/cleanup_expired")
        assert response.status_code == 200
        assert response.json()["cleaned"] >= 1
        remaining = CLIENT.get("/v1/tool/session").json()
        ids = [item["session_id"] for item in remaining["items"]]
        assert "stale" not in ids
        assert "fresh" in ids
    finally:
        session_store.set_store(session_store.ToolSessionStore())


# ---------------------------------------------------------------------------
# 配置管理链路
# ---------------------------------------------------------------------------


def test_config_get_masks_api_key(preserved_config):
    response = CLIENT.get("/v1/tool_guard/config")
    assert response.status_code == 200
    config = response.json()["config"]
    assert "api_key" in config
    assert config["api_key"] == "***"
    assert config["api_key"] != "test-secret-key-123"  # 禁止明文回显
    for key in ("base_url", "model", "block_threshold", "review_threshold",
                "timeout_seconds"):
        assert key in config


def test_config_update_flow_and_masked_echo(preserved_config):
    response = CLIENT.put("/v1/tool_guard/config", json={
        "model": "updated-model",
        "block_threshold": 0.3,
        "review_threshold": 0.8,
        "unknown_key": "ignored",
    })
    assert response.status_code == 200
    snapshot = response.json()["config"]
    assert snapshot["model"] == "updated-model"
    assert snapshot["block_threshold"] == 0.3
    assert snapshot["review_threshold"] == 0.8
    assert "unknown_key" not in snapshot
    assert snapshot["api_key"] == "***"
    # GET 回显同样脱敏,禁止明文
    reread = CLIENT.get("/v1/tool_guard/config").json()["config"]
    assert reread["model"] == "updated-model"
    assert reread["api_key"] == "***"


def test_config_update_keeps_api_key_when_omitted(preserved_config):
    before = ToolGuardLLMConfig.instance().get("api_key")
    CLIENT.put("/v1/tool_guard/config", json={"model": "another-model"})
    assert ToolGuardLLMConfig.instance().get("api_key") == before


def test_config_reset_restores_builtin_defaults(preserved_config):
    CLIENT.put("/v1/tool_guard/config", json={
        "model": "tampered-model", "block_threshold": 0.1,
    })
    response = CLIENT.post("/v1/tool_guard/config/reset")
    assert response.status_code == 200
    snapshot = response.json()["config"]
    defaults = ToolGuardLLMConfig.defaults()
    assert snapshot["model"] == defaults["model"]
    assert snapshot["block_threshold"] == defaults["block_threshold"]
    assert snapshot["review_threshold"] == defaults["review_threshold"]
    # 重置后 key 回退到内置默认(空),不再脱敏显示
    assert snapshot["api_key"] == ""


def test_tool_guard_routes_are_query_management_mix():
    """管理路由包含查询与变更接口,与审计只读路由形成对照。"""
    methods = set()
    for route in tool_guard_router.routes:
        methods.update(route.methods or set())
    assert "GET" in methods
    assert "POST" in methods
    assert methods <= {"GET", "POST"}


def test_ui_html_file_located_next_to_router():
    html = CLIENT.get("/tool-guard").text
    assert "<html lang=\"zh-CN\">" in html
    assert "Tool Guard 管理界面" in html
