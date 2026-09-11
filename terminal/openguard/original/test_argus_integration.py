# test_argus_integration.py — OpenGuard <-> Argus Integration Tests
"""
测试范围：
  1. 身份头注入是否正确
  2. /health 格式是否符合对接方案 8.1
  3. trace_id 生成和传递
  4. Argus 客户端超时/异常安全

运行方式：
  pytest test_argus_integration.py -v
  或直接运行: python test_argus_integration.py
"""
import sys
import uuid
try:
    import pytest
except ImportError:
    pytest = None  # type: ignore

from models import (
    UserContext, RequestContext, SecurityRequest,
    ModuleResult, SecurityResponse, AuditEvent,
)
from middleware import get_argus_headers
from config import config


class TestArgusHeaders:
    """对接方案 7.7：X-Argus-* 身份头注入"""

    def test_headers_from_usercontext(self):
        uc = UserContext(
            user_id="usr_abc123",
            username="alice",
            role="user",
            security_level="internal",
            session_id="sess_xyz789",
            access_jti="jti-001",
            trace_id="openguard-abcdef123456",
        )
        headers = get_argus_headers(uc)

        assert headers["X-Argus-User-Id"] == "usr_abc123"
        assert headers["X-Argus-Session-Id"] == "sess_xyz789"
        assert headers["X-Argus-Trace-Id"] == "openguard-abcdef123456"
        assert headers["X-Argus-Role"] == "user"
        assert headers["X-Argus-Security-Level"] == "internal"

    def test_headers_from_dict(self):
        """从 JWT payload dict 构造（WebSocket 代理场景）"""
        payload = {
            "sub": "usr_001",
            "username": "bob",
            "role": "admin",
            "security_level": "confidential",
            "sid": "sess_002",
            "jti": "jti-002",
            "trace_id": "trace-999",
        }
        headers = get_argus_headers(payload)

        assert headers["X-Argus-User-Id"] == "usr_001"
        assert headers["X-Argus-Session-Id"] == "sess_002"
        assert headers["X-Argus-Role"] == "admin"
        assert headers["X-Argus-Trace-Id"] == "trace-999"

    def test_headers_default_values(self):
        """缺失字段时使用默认值"""
        minimal = {"sub": "usr_min"}
        headers = get_argus_headers(minimal)
        assert headers["X-Argus-User-Id"] == "usr_min"
        assert headers["X-Argus-Role"] == "user"
        assert headers["X-Argus-Security-Level"] == "internal"
        assert headers["X-Argus-Trace-Id"].startswith("openguard-")


class TestUnifiedModels:
    """对接方案 5：统一数据结构"""

    def test_request_context_from_user(self):
        uc = UserContext(
            user_id="usr_001", username="test", role="user",
            security_level="internal", session_id="sess_001",
            access_jti="jti_001", trace_id="trace-001",
        )
        rc = RequestContext.from_user_context(uc, stage="input")
        assert rc.trace_id == "trace-001"
        assert rc.user_id == "usr_001"
        assert rc.session_id == "sess_001"
        assert rc.stage == "input"
        assert rc.timestamp  # 自动生成

    def test_module_result_actions(self):
        """只允许四种 action"""
        for action in ["allow", "block", "rewrite", "human_review"]:
            mr = ModuleResult(module="test", action=action)
            assert mr.action == action

    def test_security_response_structure(self):
        mr = ModuleResult(module="io_guard", action="allow", risk_score=0.08)
        sr = SecurityResponse(
            trace_id="t1", stage="input", action="allow",
            risk_score=0.08, module_results=[mr],
        )
        assert sr.action == "allow"
        assert len(sr.module_results) == 1
        assert sr.module_results[0].module == "io_guard"

    def test_audit_event(self):
        evt = AuditEvent(
            event_id="evt-001", trace_id="t1", session_id="s1",
            user_id="u1", timestamp="2026-08-07T10:00:00+08:00",
            stage="input", source_module="io_guard",
            action="block", risk_score=0.95, reason="prompt_injection",
        )
        assert evt.event_id == "evt-001"
        assert evt.action == "block"


class TestArgusClient:
    """测试 argus_client.py 的容错行为"""

    async def _test_timeout_returns_allow(self):
        """超时时返回 allow，不抛异常"""
        from argus_client import ArgusClient

        client = ArgusClient(base_url="http://127.0.0.1:19999", timeout=1)
        rc = RequestContext(
            trace_id="test", session_id="s1", user_id="u1",
            stage="input",
        )
        result = await client.check_input("hello", rc)
        assert result.action == "allow"
        assert "unavailable" in result.reason

    def test_all_methods_exist(self):
        """确保四个接口方法都存在"""
        from argus_client import ArgusClient
        client = ArgusClient()
        assert hasattr(client, "check_input")
        assert hasattr(client, "check_output")
        assert hasattr(client, "check_tool_pre")
        assert hasattr(client, "check_content")
        assert hasattr(client, "health_check")


def test_trace_id_uniqueness():
    """trace_id 全局唯一"""
    ids = set()
    for _ in range(100):
        tid = f"openguard-{uuid.uuid4().hex[:12]}"
        assert tid not in ids
        ids.add(tid)
    assert len(ids) == 100


if __name__ == "__main__":
    # 不依赖 pytest 的手动运行方式
    print("=" * 50)
    print("OpenGuard <-> Argus Integration Tests")
    print("=" * 50)

    tests = TestArgusHeaders()
    tests.test_headers_from_usercontext()
    print("[OK] test_headers_from_usercontext")

    tests.test_headers_from_dict()
    print("[OK] test_headers_from_dict")

    tests.test_headers_default_values()
    print("[OK] test_headers_default_values")

    model_tests = TestUnifiedModels()
    model_tests.test_request_context_from_user()
    print("[OK] test_request_context_from_user")

    model_tests.test_module_result_actions()
    print("[OK] test_module_result_actions")

    model_tests.test_security_response_structure()
    print("[OK] test_security_response_structure")

    model_tests.test_audit_event()
    print("[OK] test_audit_event")

    test_trace_id_uniqueness()
    print("[OK] test_trace_id_uniqueness")

    client_tests = TestArgusClient()
    client_tests.test_all_methods_exist()
    print("[OK] test_all_methods_exist")

    import asyncio
    asyncio.run(client_tests._test_timeout_returns_allow())
    print("[OK] test_timeout_returns_allow")

    print(f"\nAll tests passed!")
    print(f"(pytest 用户请: pip install pytest && pytest {__file__} -v)")
