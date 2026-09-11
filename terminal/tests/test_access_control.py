"""Clawguard — 访问控制全量测试套件（基础 RBAC/MAC + 审计风险联动与防线升级）

覆盖范围：
  Part A: 核心 RBAC/MAC 判定与特例规则（13 tests）
  Part B: v4 适配器基础转换与容错（8 tests）
  Part C: 端到端集成与数据契约（6 tests）
  Part D: 性能与异常边界测试（5 tests）
  Part E: 审计风险监听器 AuditRiskMonitor（6 tests）
  Part F: 动态防线策略 DynamicLinePolicy（6 tests）
  Part G: 访问控制 × 审计联动全链路集成（7 tests）
总计：51 tests
"""

from __future__ import annotations

import os
import sys
import tempfile
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows 控制台 GBK 编码无法输出中文/emoji，统一切到 UTF-8
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        sys.stdout = __import__('io').TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawguard.modules.access_control.original import auth_gateway
from clawguard.modules.access_control.original.auth_gateway import (
    check, check_reason, check_v4, _normalize_level, SecurityLabel,
    add_user_rule, remove_user_rule, get_user_rule, list_user_rules,
    add_resource_rule, remove_resource_rule, list_resource_rules,
    set_mac_label, get_mac_label, sync_external_user,
    _match_pattern, _resource_required_level_tree, _resource_match_tree,
    _check_special, _check_rbac, _check_mac,
    RuleStore, _TextBackend, _SQLiteBackend,
    ACCESS_CONTROL_MODE, DEFAULT_RESOURCE_LEVEL,
)

from clawguard.adapters.access_control_adapter import AccessControlAdapter
from clawguard.modules.audit.original import AuditStore
from clawguard.modules.access_control.risk_link import (
    AuditRiskMonitor,
    DynamicLinePolicy,
)


# ============================================================
# 辅助函数
# ============================================================

def _setup_test_env():
    """设置临时测试环境，返回 (tmpdir, users_file, resources_file)"""
    tmpdir = tempfile.mkdtemp()
    # 隔离 quarantine - 每个测试用独立文件，保留5min窗口，叠加永久标记需管理员解除
    try:
        from clawguard.modules.access_control.quarantine_store import QuarantineStore
        QuarantineStore().clear_all()
    except Exception:
        pass
    os.environ['CLAWGUARD_QUARANTINE_PATH'] = str(Path(tmpdir) / 'q.json')
    os.environ['CLAWGUARD_QUARANTINE_PATH'] = str(Path(tmpdir) / 'q.json')
    users_file = Path(tmpdir) / "users.txt"
    resources_file = Path(tmpdir) / "resources.txt"

    users_file.write_text("""\
# 测试用户
admin_test      | top_secret | *
user_internal   | internal   |
user_secret     | secret     |
user_public     | public     |
user_special    | internal   | !tool:write_file, C:\\Users\\Public\\*
user_tool       | public     | tool:query_weather
""", encoding="utf-8")

    resources_file.write_text("""\
# 测试资源
tool:write_file         | 3 | flat
tool:read_file          | 2 | flat
tool:execute_bash       | 4 | flat
tool:query_weather     | 1 | flat
C:\\Users\\admin\\secrets | 4 | override
C:\\Users\\admin         | 2 | flat
C:\\Users\\Public        | 1 | flat
db:secret_db            | 3 | flat
db:public_db            | 1 | flat
""", encoding="utf-8")

    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}

    old_store = auth_gateway._store
    auth_gateway._store = store
    old_q = os.environ.get('CLAWGUARD_QUARANTINE_PATH')
    qfile = Path(tmpdir) / 'q.json'
    os.environ['CLAWGUARD_QUARANTINE_PATH'] = str(qfile)

    return tmpdir, store, (old_store, old_q)


def _teardown_test_env(tmpdir, old_store):
    """清理测试环境"""
    if isinstance(old_store, tuple):
        store_obj, old_q = old_store
        auth_gateway._store = store_obj
        if old_q is not None:
            os.environ['CLAWGUARD_QUARANTINE_PATH'] = old_q
        else:
            os.environ.pop('CLAWGUARD_QUARANTINE_PATH', None)
    else:
        auth_gateway._store = old_store
    shutil.rmtree(tmpdir)


def _now_iso(**delta):
    """生成带时区的当前时间 ISO 字符串，可选偏移（seconds/minutes/hours，负=过去）。"""
    base = datetime.now(timezone.utc)
    if delta:
        base = base + timedelta(**delta)
    return base.isoformat()


def _audit_event(event_id, user_id="user_risk", action="block", risk_score=0.9,
                 session_id="session-risk", **delta):
    """构造一条审计事件（默认 30 秒前，可用 delta 覆盖偏移）。"""
    offset = dict(delta)
    offset.setdefault("seconds", -30)
    return {
        "event_id": event_id,
        "trace_id": f"trace-{event_id}",
        "session_id": session_id,
        "user_id": user_id,
        "timestamp": _now_iso(**offset),
        "stage": "tool_pre",
        "source_module": "access_control",
        "action": action,
        "risk_score": risk_score,
        "reason": f"synthetic {action}",
        "content": {"tool_name": "read_file"},
        "metadata": {"sequence": 1},
    }


def _seed_store(store: AuditStore, events: list[dict]) -> AuditStore:
    for event in events:
        store.append(event)
    return store


def _adapter_request(user_id="user_internal", session_id="session-risk",
                     tool_name="read_file", path=""):
    return {
        "context": {
            "trace_id": "trace-test",
            "session_id": session_id,
            "user_id": user_id,
            "stage": "tool_pre",
            "timestamp": _now_iso(),
        },
        "payload": {
            "tool_name": tool_name,
            "tool_call_id": "call-test",
            "arguments": {"path": path},
            "database": "",
        }
    }


def _tmpdir():
    """创建一个临时目录，返回 Path。调用方负责清理。"""
    return Path(tempfile.mkdtemp())


# ============================================================
# Part A: 核心 RBAC/MAC 测试（13 tests）
# ============================================================

class TestCoreRBAC:
    @staticmethod
    def test_level_normalization():
        assert _normalize_level("1") == 1
        assert _normalize_level("2") == 2
        assert _normalize_level("3") == 3
        assert _normalize_level("4") == 4
        assert _normalize_level("public") == 1
        assert _normalize_level("internal") == 2
        assert _normalize_level("secret") == 3
        assert _normalize_level("top_secret") == 4
        assert _normalize_level("a") == 1
        assert _normalize_level("d") == 4
        assert _normalize_level("unknown") == 1
        print("  ✓ 1.1 等级归一化")

    @staticmethod
    def test_security_label_dominance():
        l1 = SecurityLabel(level=1)
        l2 = SecurityLabel(level=2)
        l4 = SecurityLabel(level=4)
        assert l2.dominates(l1)
        assert not l1.dominates(l2)
        assert l4.dominates(l1)
        assert l4.dominates(l4)

        l_hr = SecurityLabel(level=2, categories=frozenset({"HR"}))
        l_hr_fin = SecurityLabel(level=2, categories=frozenset({"HR", "FIN"}))
        assert l_hr_fin.dominates(l_hr)
        assert not l_hr.dominates(l_hr_fin)
        print("  ✓ 1.2 MAC 标签支配关系")

    @staticmethod
    def test_pattern_matching():
        assert _match_pattern("C:\\Users\\Public\\*", "C:\\Users\\Public\\doc.txt")
        assert not _match_pattern("C:\\Users\\Public\\*", "C:\\Users\\admin\\doc.txt")
        assert _match_pattern("tool:read_file", "tool:read_file")
        assert not _match_pattern("tool:read_file", "tool:write_file")
        assert _match_pattern("tool:*", "tool:read_file")
        assert _match_pattern("tool:*", "tool:execute_bash")
        assert _match_pattern("db:public_db", "db:public_db")
        print("  ✓ 1.3 资源路径/工具模式匹配")

    @staticmethod
    def test_admin_full_access():
        tmpdir, store, old = _setup_test_env()
        try:
            assert check("admin_test", path="C:\\Users\\admin\\secrets\\passwords.txt")
            assert check("admin_test", tool="tool:execute_bash")
            assert check("admin_test", tool="tool:write_file")
            assert check("admin_test", database="db:secret_db")
            print("  ✓ 1.4 管理员通配符权限")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_user_level_hierarchy():
        tmpdir, store, old = _setup_test_env()
        try:
            # 内部用户(2)访问内部资源(2) -> 放行
            assert check("user_internal", path="C:\\Users\\admin\\file.txt")
            assert check("user_internal", tool="tool:read_file")

            # 内部用户(2)访问绝密资源(4) -> 拦截
            assert not check("user_internal", path="C:\\Users\\admin\\secrets\\key.pem")
            assert not check("user_internal", tool="tool:execute_bash")

            # 秘密用户(3)访问秘密工具(3) -> 放行
            assert check("user_secret", tool="tool:write_file")
            # 秘密用户(3)访问绝密工具(4) -> 拦截
            assert not check("user_secret", tool="tool:execute_bash")

            # 公开用户(1)访问内部工具(2) -> 拦截
            assert not check("user_public", tool="tool:read_file")
            print("  ✓ 1.5 用户等级分级鉴权")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_special_rules_allow_and_block():
        tmpdir, store, old = _setup_test_env()
        try:
            # 特例放行：公开用户有天气工具特例
            assert check("user_tool", tool="tool:query_weather")
            # 特例拒绝：内部用户显式被禁止写文件
            assert not check("user_special", tool="tool:write_file")
            # 特例放行：内部用户可访问公开目录
            assert check("user_special", path="C:\\Users\\Public\\readme.txt")
            print("  ✓ 1.6 特例放行与特例拦截")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_override_inheritance():
        tmpdir, store, old = _setup_test_env()
        try:
            # C:\Users\admin 是 2 级，但 C:\Users\admin\secrets 是 4 级 override
            assert check("user_internal", path="C:\\Users\\admin\\normal.txt")
            assert not check("user_internal", path="C:\\Users\\admin\\secrets\\vault.key")
            print("  ✓ 1.7 路径继承与 override 机制")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_check_reason_output():
        tmpdir, store, old = _setup_test_env()
        try:
            ok, reason = check_reason("user_internal", tool="tool:read_file")
            assert ok
            assert "用户等级 2" in reason

            ok, reason = check_reason("user_internal", tool="tool:execute_bash")
            assert not ok
            assert "用户等级 2 < 资源所需 4" in reason
            print("  ✓ 1.8 判定原因返回（check_reason）")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_check_v4_interface():
        tmpdir, store, old = _setup_test_env()
        try:
            res = check_v4(user_id="user_internal", tool="tool:read_file")
            assert isinstance(res, dict)
            assert res["allowed"] is True
            assert res["user_id"] == "user_internal"
            assert "tool:read_file" in res["tool"]

            res = check_v4(user_id="user_internal", tool="tool:execute_bash")
            assert res["allowed"] is False
            print("  ✓ 1.9 check_v4 接口格式")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_dynamic_rule_crud():
        tmpdir, store, old = _setup_test_env()
        try:
            add_user_rule("dynamic_user", "secret", ["tool:execute_bash"])
            assert check("dynamic_user", tool="tool:execute_bash")
            u = get_user_rule("dynamic_user")
            assert u["level"] == 3

            remove_user_rule("dynamic_user")
            assert get_user_rule("dynamic_user") is None

            add_resource_rule("tool:custom_tool", "top_secret")
            assert not check("user_internal", tool="tool:custom_tool")
            remove_resource_rule("tool:custom_tool")
            print("  ✓ 1.10 动态规则增删改查")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_mac_mode():
        tmpdir, store, old = _setup_test_env()
        try:
            auth_gateway.ACCESS_CONTROL_MODE = "mac"
            set_mac_label("user_internal", level=2, categories={"HR"})

            # 同级别、同范畴 -> 放行
            store.resource_labels["tool:read_file"] = SecurityLabel(level=2, categories=frozenset({"HR"}))
            assert check("user_internal", tool="tool:read_file")

            # 范畴缺失 -> 拦截
            store.resource_labels["tool:write_file"] = SecurityLabel(level=2, categories=frozenset({"HR", "FIN"}))
            assert not check("user_internal", tool="tool:write_file")
            print("  ✓ 1.11 MAC 模式安全标签鉴权")
        finally:
            auth_gateway.ACCESS_CONTROL_MODE = "rbac"
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_hybrid_mode():
        tmpdir, store, old = _setup_test_env()
        try:
            auth_gateway.ACCESS_CONTROL_MODE = "hybrid"
            set_mac_label("user_internal", level=2, categories=set())

            # RBAC 允许(2>=2)且 MAC 允许 -> 放行
            assert check("user_internal", tool="tool:read_file")

            # RBAC 拦截(2<4) -> 拦截
            assert not check("user_internal", tool="tool:execute_bash")
            print("  ✓ 1.12 Hybrid 模式双重校验")
        finally:
            auth_gateway.ACCESS_CONTROL_MODE = "rbac"
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_sync_external_user():
        tmpdir, store, old = _setup_test_env()
        try:
            sync_external_user("jwt_user_99", "secret")
            assert store.get_user_level("jwt_user_99") == 3
            assert check("jwt_user_99", tool="tool:write_file")
            print("  ✓ 1.13 外部身份动态同步")
        finally:
            _teardown_test_env(tmpdir, old)


# ============================================================
# Part B: v4 适配器基础测试（8 tests）
# ============================================================

class TestV4Adapter:
    @staticmethod
    def test_adapter_allow_format():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            req = {
                "context": {"user_id": "user_internal", "stage": "tool_pre", "trace_id": "t-1"},
                "payload": {"tool_name": "read_file", "arguments": {}}
            }
            res = adapter.run_sync(req)
            assert res["module"] == "access_control"
            assert res["success"] is True
            assert res["action"] == "allow"
            assert res["risk_score"] == 0.0
            assert "latency_ms" in res
            print("  ✓ 2.1 适配器放行输出契约")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_adapter_block_format():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            req = {
                "context": {"user_id": "user_internal", "stage": "tool_pre", "trace_id": "t-2"},
                "payload": {"tool_name": "execute_bash", "arguments": {}}
            }
            res = adapter.run_sync(req)
            assert res["success"] is True
            assert res["action"] == "block"
            assert res["risk_score"] == 1.0
            assert "用户等级 2 < 资源所需 4" in res["reason"]
            print("  ✓ 2.2 适配器拦截输出契约")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_adapter_with_path_in_arguments():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            req = {
                "context": {"user_id": "user_internal", "stage": "tool_pre"},
                "payload": {
                    "tool_name": "read_file",
                    "arguments": {"path": "C:\\Users\\admin\\secrets\\vault.key"}
                }
            }
            res = adapter.run_sync(req)
            # secrets 是 4 级 override，内部用户(2)应该被拦截
            assert res["action"] == "block"
            print("  ✓ 2.3 从 arguments.path 提取路径鉴权")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_adapter_tool_prefix_normalization():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            # 传 "read_file" 而不是 "tool:read_file"，适配器自动补齐前缀
            req = {
                "context": {"user_id": "user_internal", "stage": "tool_pre"},
                "payload": {"tool_name": "read_file"}
            }
            res = adapter.run_sync(req)
            assert res["action"] == "allow"
            assert res["details"]["tool"] == "tool:read_file"
            print("  ✓ 2.4 tool 名称自动补齐 tool: 前缀")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_adapter_database_access():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            # public_db 需 1 级，user_internal(2) -> 放行
            req = {
                "context": {"user_id": "user_internal", "stage": "tool_pre"},
                "payload": {"database": "db:public_db"}
            }
            assert adapter.run_sync(req)["action"] == "allow"

            # secret_db 需 3 级，user_internal(2) -> 拦截
            req["payload"]["database"] = "db:secret_db"
            assert adapter.run_sync(req)["action"] == "block"
            print("  ✓ 2.5 数据库资源鉴权")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_adapter_unknown_user_default_level():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            # 未知用户默认 1 级
            req = {
                "context": {"user_id": "anonymous_user", "stage": "tool_pre"},
                "payload": {"tool_name": "query_weather"}
            }
            assert adapter.run_sync(req)["action"] == "allow"

            req["payload"]["tool_name"] = "read_file"
            assert adapter.run_sync(req)["action"] == "block"
            print("  ✓ 2.6 未知用户默认等级处理")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_adapter_pydantic_model_input():
        tmpdir, store, old = _setup_test_env()
        try:
            from clawguard.common.models import SecurityRequest, RequestContext
            adapter = AccessControlAdapter(risk_link_enabled=False)

            req = SecurityRequest(
                context=RequestContext(user_id="user_internal", stage="tool_pre"),
                payload={"tool_name": "read_file"}
            )
            res = adapter.run_sync(req)
            assert res.action == "allow"
            assert res.success is True
            print("  ✓ 2.7 支持 Pydantic SecurityRequest 模型入参")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_adapter_exception_safety():
        adapter = AccessControlAdapter(risk_link_enabled=False)
        # 传入非法数据类型，不应抛出未捕获异常导致网关崩溃
        res = adapter.run_sync(None)
        is_success = res.success if hasattr(res, "success") else res["success"]
        is_action = res.action if hasattr(res, "action") else res["action"]
        assert is_success is False
        assert is_action == "block"
        print("  ✓ 2.8 异常安全隔离（Fail-Secure）")


# ============================================================
# Part C: 端到端集成测试（6 tests）
# ============================================================

class TestE2E:
    @staticmethod
    def test_e2e_full_request_allow():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            req = {
                "context": {
                    "trace_id": "trace-e2e-001",
                    "session_id": "session-e2e-001",
                    "user_id": "user_secret",
                    "stage": "tool_pre",
                    "timestamp": "2026-08-03T10:00:00Z"
                },
                "payload": {
                    "tool_name": "write_file",
                    "tool_call_id": "call-001",
                    "arguments": {"path": "C:\\Users\\Public\\report.txt"},
                    "database": ""
                }
            }
            res = adapter.run_sync(req)
            assert res["success"] is True
            assert res["action"] == "allow"
            assert res["risk_score"] == 0.0
            print("  ✓ 3.1 端到端完整放行请求")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_e2e_full_request_block():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            req = {
                "context": {
                    "trace_id": "trace-e2e-002",
                    "session_id": "session-e2e-002",
                    "user_id": "user_public",
                    "stage": "tool_pre",
                    "timestamp": "2026-08-03T10:00:00Z"
                },
                "payload": {
                    "tool_name": "execute_bash",
                    "tool_call_id": "call-002",
                    "arguments": {"command": "rm -rf /"},
                    "database": ""
                }
            }
            res = adapter.run_sync(req)
            assert res["success"] is True
            assert res["action"] == "block"
            assert res["risk_score"] == 1.0
            assert "用户等级 1 < 资源所需 4" in res["reason"]
            print("  ✓ 3.2 端到端越权拦截请求")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_e2e_unknown_user():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            req = {
                "context": {"user_id": "unregistered_hacker", "stage": "tool_pre"},
                "payload": {"tool_name": "execute_bash"}
            }
            res = adapter.run_sync(req)
            assert res["action"] == "block"
            print("  ✓ 3.3 未注册用户越权拦截")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_e2e_database_access():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            # 绝密库只允许 admin
            req = {
                "context": {"user_id": "admin_test", "stage": "tool_pre"},
                "payload": {"database": "db:secret_db"}
            }
            assert adapter.run_sync(req)["action"] == "allow"

            req["context"]["user_id"] = "user_public"
            assert adapter.run_sync(req)["action"] == "block"
            print("  ✓ 3.4 数据库端到端访问控制")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_e2e_special_rule_allow():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            # user_tool 是 1 级，但有 query_weather 特例
            req = {
                "context": {"user_id": "user_tool", "stage": "tool_pre"},
                "payload": {"tool_name": "query_weather"}
            }
            res = adapter.run_sync(req)
            assert res["action"] == "allow"
            print("  ✓ 3.5 特例放行端到端验证")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_e2e_special_rule_block():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            # user_special 是 2 级，但特例中显式 !tool:write_file
            req = {
                "context": {"user_id": "user_special", "stage": "tool_pre"},
                "payload": {"tool_name": "write_file"}
            }
            res = adapter.run_sync(req)
            assert res["action"] == "block"
            print("  ✓ 3.6 特例拒绝端到端验证")
        finally:
            _teardown_test_env(tmpdir, old)


# ============================================================
# Part D: 性能与边界测试（5 tests）
# ============================================================

class TestPerformance:
    @staticmethod
    def test_latency_under_threshold():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            req = {
                "context": {"user_id": "user_internal", "stage": "tool_pre"},
                "payload": {"tool_name": "read_file"}
            }
            # 预热
            adapter.run_sync(req)

            import time
            runs = 100
            t0 = time.perf_counter()
            for _ in range(runs):
                res = adapter.run_sync(req)
                assert res["action"] == "allow"
            elapsed_avg = (time.perf_counter() - t0) / runs * 1000

            # 单次判定必须低于 2ms
            assert elapsed_avg < 2.0, f"判定延迟超标: {elapsed_avg:.3f}ms"
            print(f"  ✓ 4.1 性能基准测试通过 (平均延迟: {elapsed_avg:.3f}ms < 2.0ms)")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_empty_payload():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            req = {"context": {"user_id": "user_internal", "stage": "tool_pre"}, "payload": {}}
            res = adapter.run_sync(req)
            assert res["action"] == "block"
            print("  ✓ 4.2 空 Payload 安全拦截")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_missing_context():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            req = {"payload": {"tool_name": "query_weather"}}
            res = adapter.run_sync(req)
            # 缺 context 时默认 default_user(1级) 访问天气(1级) -> 放行
            assert res["action"] == "allow"
            print("  ✓ 4.3 缺省 Context 默认降级处理")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_long_path():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            long_path = "C:\\Users\\admin\\" + "sub\\" * 50 + "file.txt"
            req = {
                "context": {"user_id": "user_internal", "stage": "tool_pre"},
                "payload": {"tool_name": "read_file", "arguments": {"path": long_path}}
            }
            res = adapter.run_sync(req)
            assert res["action"] == "allow"
            print("  ✓ 4.4 超长深度路径规范化鉴权")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_special_chars_in_path():
        tmpdir, store, old = _setup_test_env()
        try:
            adapter = AccessControlAdapter(risk_link_enabled=False)
            req = {
                "context": {"user_id": "user_internal", "stage": "tool_pre"},
                "payload": {"tool_name": "read_file", "arguments": {"path": "C:\\Users\\admin\\..\\admin\\doc.txt"}}
            }
            res = adapter.run_sync(req)
            assert res["action"] == "allow"
            print("  ✓ 4.5 包含相对路径符 .. 自动归一化")
        finally:
            _teardown_test_env(tmpdir, old)


# ============================================================
# Part E: AuditRiskMonitor 单元测试（6 tests）
# ============================================================

class TestAuditRiskMonitor:
    """实时风险评分计算与频发试探识别"""

    @staticmethod
    def test_no_events_means_zero_risk():
        tmp = _tmpdir()
        try:
            store = AuditStore(tmp / "a.jsonl")
            monitor = AuditRiskMonitor(store=store, window_seconds=300,
                                       probe_block_count=3)
            assessment = monitor.assess("user_risk", "session-risk")
            assert assessment["risk_score"] == 0.0
            assert assessment["block_count"] == 0
            assert assessment["probe_likely"] is False
            assert assessment["event_count"] == 0
            print("  ✓ 5.1 无事件时零风险")
        finally:
            shutil.rmtree(tmp)

    @staticmethod
    def test_frequent_blocks_detects_probe():
        tmp = _tmpdir()
        try:
            store = _seed_store(AuditStore(tmp / "a.jsonl"), [
                _audit_event("e1", risk_score=0.9),
                _audit_event("e2", risk_score=0.9),
                _audit_event("e3", risk_score=0.9),
            ])
            monitor = AuditRiskMonitor(store=store, window_seconds=300,
                                       probe_block_count=3)
            assessment = monitor.assess("user_risk", "session-risk")
            assert assessment["block_count"] == 3
            assert assessment["probe_likely"] is True
            assert assessment["risk_score"] >= 0.5
            print(f"  ✓ 5.2 频发拦截识别试探 (risk={assessment['risk_score']})")
        finally:
            shutil.rmtree(tmp)

    @staticmethod
    def test_other_users_are_ignored():
        tmp = _tmpdir()
        try:
            store = _seed_store(AuditStore(tmp / "a.jsonl"), [
                _audit_event("e1", user_id="user_risk", risk_score=0.9),
                _audit_event("e2", user_id="other_user", risk_score=0.95),
                _audit_event("e3", user_id="user_risk", risk_score=0.9),
            ])
            monitor = AuditRiskMonitor(store=store, window_seconds=300,
                                       probe_block_count=3)
            assessment = monitor.assess("user_risk", "session-risk")
            assert assessment["event_count"] == 2
            assert assessment["block_count"] == 2
            assert assessment["probe_likely"] is False
            print("  ✓ 5.3 只统计目标用户")
        finally:
            shutil.rmtree(tmp)

    @staticmethod
    def test_session_filter():
        tmp = _tmpdir()
        try:
            store = _seed_store(AuditStore(tmp / "a.jsonl"), [
                _audit_event("e1", session_id="session-a", risk_score=0.9),
                _audit_event("e2", session_id="session-b", risk_score=0.95),
                _audit_event("e3", session_id="session-a", risk_score=0.9),
            ])
            monitor = AuditRiskMonitor(store=store, window_seconds=300,
                                       probe_block_count=3)
            a = monitor.assess("user_risk", "session-a")
            assert a["event_count"] == 2
            b = monitor.assess("user_risk", "session-b")
            assert b["event_count"] == 1
            print("  ✓ 5.4 会话过滤")
        finally:
            shutil.rmtree(tmp)

    @staticmethod
    def test_expired_events_outside_window_ignored():
        tmp = _tmpdir()
        try:
            store = _seed_store(AuditStore(tmp / "a.jsonl"), [
                _audit_event("old", risk_score=0.9, minutes=-10),
                _audit_event("new", risk_score=0.9, seconds=-30),
            ])
            monitor = AuditRiskMonitor(store=store, window_seconds=300,
                                       probe_block_count=2)
            assessment = monitor.assess("user_risk", "session-risk")
            assert assessment["event_count"] == 1
            assert assessment["block_count"] == 1
            print("  ✓ 5.5 时间窗外事件忽略")
        finally:
            shutil.rmtree(tmp)

    @staticmethod
    def test_low_risk_events_give_lower_score():
        tmp = _tmpdir()
        try:
            store = _seed_store(AuditStore(tmp / "a.jsonl"), [
                _audit_event("e1", risk_score=0.1, action="allow"),
                _audit_event("e2", risk_score=0.2, action="allow"),
            ])
            monitor = AuditRiskMonitor(store=store, window_seconds=300,
                                       probe_block_count=3)
            assessment = monitor.assess("user_risk", "session-risk")
            assert assessment["risk_score"] < 0.5
            assert assessment["probe_likely"] is False
            print(f"  ✓ 5.6 低风险事件低评分 (risk={assessment['risk_score']})")
        finally:
            shutil.rmtree(tmp)


# ============================================================
# Part F: DynamicLinePolicy 单元测试（6 tests）
# ============================================================

class TestDynamicLinePolicy:
    """防线升级与二次审批决策"""

    @staticmethod
    def test_penalty_zero_below_threshold():
        policy = DynamicLinePolicy(escalation_threshold=0.5, max_penalty=2)
        assert policy.penalty_for({"risk_score": 0.3}) == 0
        assert policy.penalty_for({"risk_score": 0.49}) == 0
        print("  ✓ 6.1 低于阈值不升级")

    @staticmethod
    def test_penalty_scales_with_risk():
        policy = DynamicLinePolicy(escalation_threshold=0.5, max_penalty=2)
        assert policy.penalty_for({"risk_score": 0.5}) == 1
        assert policy.penalty_for({"risk_score": 0.75}) == 1
        assert policy.penalty_for({"risk_score": 0.95}) == 2
        assert policy.penalty_for({"risk_score": 1.0}) == 2
        print("  ✓ 6.2 penalty 随风险递增")

    @staticmethod
    def test_no_escalation_keeps_original():
        policy = DynamicLinePolicy(escalation_threshold=0.5)
        decision = policy.decide(
            allowed=True, escalated_allowed=True, reason="allow: ok",
            assessment={"risk_score": 0.2, "block_count": 0},
        )
        assert decision["action"] == "allow"
        assert decision["escalated"] is False
        assert decision["penalty"] == 0

        decision = policy.decide(
            allowed=False, escalated_allowed=False, reason="block: denied",
            assessment={"risk_score": 0.2, "block_count": 0},
        )
        assert decision["action"] == "block"
        print("  ✓ 6.3 无风险维持原判定")

    @staticmethod
    def test_original_block_stays_block():
        policy = DynamicLinePolicy(escalation_threshold=0.5)
        decision = policy.decide(
            allowed=False, escalated_allowed=False, reason="block: denied",
            assessment={"risk_score": 0.9, "block_count": 3},
        )
        assert decision["action"] == "block"
        assert decision["escalated"] is True
        assert "risk_escalated" in decision["reason"]
        print("  ✓ 6.4 原始拦截保持 block")

    @staticmethod
    def test_escalated_allow_stays_allow():
        policy = DynamicLinePolicy(escalation_threshold=0.5)
        decision = policy.decide(
            allowed=True, escalated_allowed=True, reason="allow: ok",
            assessment={"risk_score": 0.9, "block_count": 3},
        )
        assert decision["action"] == "allow"
        assert decision["escalated"] is True
        assert decision["penalty"] >= 1
        print("  ✓ 6.5 升级后仍放行保持 allow")

    @staticmethod
    def test_escalated_block_triggers_human_review():
        policy = DynamicLinePolicy(escalation_threshold=0.5)
        decision = policy.decide(
            allowed=True, escalated_allowed=False, reason="allow: ok",
            assessment={"risk_score": 0.9, "block_count": 3},
        )
        assert decision["action"] == "human_review"
        assert decision["escalated"] is True
        assert decision["penalty"] >= 1
        assert "human_review" in decision["reason"] or "人工审批" in decision["reason"]
        print("  ✓ 6.6 升级后拦截转人工审批")


# ============================================================
# Part G: 访问控制 × 审计联动集成测试（7 tests）
# ============================================================

class TestRiskLinkIntegration:
    """adapter 原始判定 → 风险升级 → 二次审批 全链路"""

    @staticmethod
    def test_no_audit_events_keeps_original_decision():
        tmp = _tmpdir()
        tmpdir, store, old = _setup_test_env()
        try:
            audit_store = AuditStore(tmp / "empty.jsonl")
            monitor = AuditRiskMonitor(store=audit_store, probe_block_count=3)
            adapter = AccessControlAdapter(risk_monitor=monitor)

            # user_internal(2) 访问 read_file(需2) → allow
            result = adapter.run_sync(_adapter_request(tool_name="read_file"))
            assert result["action"] == "allow"
            assert result["details"]["escalated"] is False
            assert result["details"]["penalty"] == 0
            print("  ✓ 7.1 无审计事件维持原判定")
        finally:
            _teardown_test_env(tmpdir, old)
            shutil.rmtree(tmp)

    @staticmethod
    def test_probe_escalates_to_human_review():
        tmp = _tmpdir()
        tmpdir, store, old = _setup_test_env()
        try:
            audit_store = _seed_store(AuditStore(tmp / "probe.jsonl"), [
                _audit_event("p1", user_id="user_internal", risk_score=0.9),
                _audit_event("p2", user_id="user_internal", risk_score=0.9),
                _audit_event("p3", user_id="user_internal", risk_score=0.9),
            ])
            monitor = AuditRiskMonitor(store=audit_store, probe_block_count=3)
            policy = DynamicLinePolicy(escalation_threshold=0.5)
            adapter = AccessControlAdapter(risk_monitor=monitor, risk_policy=policy)

            # user_internal(2) 访问 read_file(需2)：原始 allow，
            # 防线升级后 read_file 需 2+penalty(≥1)=3 > 2 → 转 human_review
            result = adapter.run_sync(_adapter_request(tool_name="read_file"))
            assert result["action"] == "human_review", f"实际: {result['action']} | {result['reason']}"
            assert result["details"]["escalated"] is True
            assert result["details"]["penalty"] >= 1
            assert result["details"]["risk"]["probe_likely"] is True
            assert result["details"]["risk"]["block_count"] == 3
            print(f"  ✓ 7.2 频发试探升级防线并二次审批 (penalty={result['details']['penalty']})")
        finally:
            _teardown_test_env(tmpdir, old)
            shutil.rmtree(tmp)

    @staticmethod
    def test_sufficient_level_survives_escalation():
        tmp = _tmpdir()
        tmpdir, store, old = _setup_test_env()
        try:
            audit_store = _seed_store(AuditStore(tmp / "probe.jsonl"), [
                _audit_event("p1", user_id="user_secret", risk_score=0.7),
                _audit_event("p2", user_id="user_secret", risk_score=0.7),
            ])
            monitor = AuditRiskMonitor(store=audit_store, probe_block_count=3)
            policy = DynamicLinePolicy(escalation_threshold=0.5)
            adapter = AccessControlAdapter(risk_monitor=monitor, risk_policy=policy)

            # user_secret(3) 访问 read_file(需2)：原始 allow，升级后需 2+penalty(1)=3 ≤ 3 → 仍 allow
            result = adapter.run_sync(_adapter_request(
                user_id="user_secret", tool_name="read_file"))
            assert result["action"] == "allow", f"实际: {result['action']}"
            assert result["details"]["escalated"] is True
            assert result["details"]["penalty"] >= 1
            print(f"  ✓ 7.3 等级足够升级后仍放行 (penalty={result['details']['penalty']})")
        finally:
            _teardown_test_env(tmpdir, old)
            shutil.rmtree(tmp)

    @staticmethod
    def test_original_block_remains_block():
        tmp = _tmpdir()
        tmpdir, store, old = _setup_test_env()
        try:
            audit_store = _seed_store(AuditStore(tmp / "probe.jsonl"), [
                _audit_event("p1", user_id="user_internal", risk_score=0.9),
                _audit_event("p2", user_id="user_internal", risk_score=0.9),
                _audit_event("p3", user_id="user_internal", risk_score=0.9),
            ])
            monitor = AuditRiskMonitor(store=audit_store, probe_block_count=3)
            adapter = AccessControlAdapter(risk_monitor=monitor)

            # user_internal(2) 访问 execute_bash(需4)：原始 block → 保持 block
            result = adapter.run_sync(_adapter_request(tool_name="execute_bash"))
            assert result["action"] == "block", f"实际: {result['action']}"
            assert result["details"]["escalated"] is True
            print("  ✓ 7.4 原始拦截保持 block")
        finally:
            _teardown_test_env(tmpdir, old)
            shutil.rmtree(tmp)

    @staticmethod
    def test_admin_bypass_escalation():
        tmp = _tmpdir()
        tmpdir, store, old = _setup_test_env()
        try:
            audit_store = _seed_store(AuditStore(tmp / "probe.jsonl"), [
                _audit_event("p1", user_id="admin_test", risk_score=0.95),
                _audit_event("p2", user_id="admin_test", risk_score=0.95),
                _audit_event("p3", user_id="admin_test", risk_score=0.95),
            ])
            monitor = AuditRiskMonitor(store=audit_store, probe_block_count=3)
            policy = DynamicLinePolicy(escalation_threshold=0.5)
            adapter = AccessControlAdapter(risk_monitor=monitor, risk_policy=policy)

            result = adapter.run_sync(_adapter_request(
                user_id="admin_test", tool_name="execute_bash"))
            assert result["action"] == "allow", f"实际: {result['action']}"
            print("  ✓ 7.5 admin 特例放行不受防线升级影响")
        finally:
            _teardown_test_env(tmpdir, old)
            shutil.rmtree(tmp)

    @staticmethod
    def test_audit_failure_fails_open():
        tmpdir, store, old = _setup_test_env()
        try:
            class FailingMonitor:
                def assess(self, user_id, session_id=""):
                    raise RuntimeError("audit unavailable")

            adapter = AccessControlAdapter(risk_monitor=FailingMonitor())

            # 审计读取失败 → fail-open 按原始判定返回
            result = adapter.run_sync(_adapter_request(tool_name="read_file"))
            assert result["success"] is True
            assert result["action"] == "allow", f"实际: {result['action']}"
            assert result["error"] is None
            print("  ✓ 7.6 审计不可用 fail-open")
        finally:
            _teardown_test_env(tmpdir, old)

    @staticmethod
    def test_risk_link_can_be_disabled():
        tmp = _tmpdir()
        tmpdir, store, old = _setup_test_env()
        try:
            audit_store = _seed_store(AuditStore(tmp / "probe.jsonl"), [
                _audit_event("p1", user_id="user_internal", risk_score=0.9),
                _audit_event("p2", user_id="user_internal", risk_score=0.9),
                _audit_event("p3", user_id="user_internal", risk_score=0.9),
            ])
            monitor = AuditRiskMonitor(store=audit_store, probe_block_count=3)
            adapter = AccessControlAdapter(
                risk_monitor=monitor, risk_link_enabled=False)

            # 关闭联动：即使有高风险事件也维持原始判定
            result = adapter.run_sync(_adapter_request(tool_name="read_file"))
            assert result["action"] == "allow", f"实际: {result['action']}"
            assert result["details"]["escalated"] is False
            assert result["details"]["penalty"] == 0
            print("  ✓ 7.7 可关闭联动")
        finally:
            _teardown_test_env(tmpdir, old)
            shutil.rmtree(tmp)


# ============================================================
# 测试运行器
# ============================================================

def run_all_tests():
    print("=" * 70)
    print("Clawguard 访问控制全量测试套件 (51 项测试)")
    print("=" * 70)

    test_groups = [
        ("Part A: 核心 RBAC/MAC", [
            TestCoreRBAC.test_level_normalization,
            TestCoreRBAC.test_security_label_dominance,
            TestCoreRBAC.test_pattern_matching,
            TestCoreRBAC.test_admin_full_access,
            TestCoreRBAC.test_user_level_hierarchy,
            TestCoreRBAC.test_special_rules_allow_and_block,
            TestCoreRBAC.test_override_inheritance,
            TestCoreRBAC.test_check_reason_output,
            TestCoreRBAC.test_check_v4_interface,
            TestCoreRBAC.test_dynamic_rule_crud,
            TestCoreRBAC.test_mac_mode,
            TestCoreRBAC.test_hybrid_mode,
            TestCoreRBAC.test_sync_external_user,
        ]),
        ("Part B: 适配器基础转换", [
            TestV4Adapter.test_adapter_allow_format,
            TestV4Adapter.test_adapter_block_format,
            TestV4Adapter.test_adapter_with_path_in_arguments,
            TestV4Adapter.test_adapter_tool_prefix_normalization,
            TestV4Adapter.test_adapter_database_access,
            TestV4Adapter.test_adapter_unknown_user_default_level,
            TestV4Adapter.test_adapter_pydantic_model_input,
            TestV4Adapter.test_adapter_exception_safety,
        ]),
        ("Part C: 端到端集成", [
            TestE2E.test_e2e_full_request_allow,
            TestE2E.test_e2e_full_request_block,
            TestE2E.test_e2e_unknown_user,
            TestE2E.test_e2e_database_access,
            TestE2E.test_e2e_special_rule_allow,
            TestE2E.test_e2e_special_rule_block,
        ]),
        ("Part D: 性能与边界", [
            TestPerformance.test_latency_under_threshold,
            TestPerformance.test_empty_payload,
            TestPerformance.test_missing_context,
            TestPerformance.test_long_path,
            TestPerformance.test_special_chars_in_path,
        ]),
        ("Part E: 审计风险监听器", [
            TestAuditRiskMonitor.test_no_events_means_zero_risk,
            TestAuditRiskMonitor.test_frequent_blocks_detects_probe,
            TestAuditRiskMonitor.test_other_users_are_ignored,
            TestAuditRiskMonitor.test_session_filter,
            TestAuditRiskMonitor.test_expired_events_outside_window_ignored,
            TestAuditRiskMonitor.test_low_risk_events_give_lower_score,
        ]),
        ("Part F: 动态防线策略", [
            TestDynamicLinePolicy.test_penalty_zero_below_threshold,
            TestDynamicLinePolicy.test_penalty_scales_with_risk,
            TestDynamicLinePolicy.test_no_escalation_keeps_original,
            TestDynamicLinePolicy.test_original_block_stays_block,
            TestDynamicLinePolicy.test_escalated_allow_stays_allow,
            TestDynamicLinePolicy.test_escalated_block_triggers_human_review,
        ]),
        ("Part G: 集成联动与二次审批", [
            TestRiskLinkIntegration.test_no_audit_events_keeps_original_decision,
            TestRiskLinkIntegration.test_probe_escalates_to_human_review,
            TestRiskLinkIntegration.test_sufficient_level_survives_escalation,
            TestRiskLinkIntegration.test_original_block_remains_block,
            TestRiskLinkIntegration.test_admin_bypass_escalation,
            TestRiskLinkIntegration.test_audit_failure_fails_open,
            TestRiskLinkIntegration.test_risk_link_can_be_disabled,
        ]),
    ]

    total_passed = 0
    total_failed = 0
    group_results = []

    for group_name, tests in test_groups:
        print(f"\n{'─' * 70}")
        print(f"  {group_name}")
        print(f"{'─' * 70}")
        passed = 0
        failed = 0
        for test in tests:
            try:
                test()
                passed += 1
                total_passed += 1
            except Exception as e:
                failed += 1
                total_failed += 1
                print(f"  ✗ {test.__name__} FAILED: {e}")
                import traceback
                traceback.print_exc()
        group_results.append((group_name, passed, failed))

    # 汇总
    print()
    print("=" * 70)
    print("测试汇总")
    print("=" * 70)
    for group_name, passed, failed in group_results:
        status = "✓ 全部通过" if failed == 0 else f"✗ {failed} 个失败"
        print(f"  {group_name}: {passed}/{passed+failed} — {status}")
    print(f"{'─' * 70}")
    print(f"  总计: {total_passed} 通过, {total_failed} 失败")
    print("=" * 70)

    if total_failed == 0:
        print("\n  🎉 所有测试通过！")
    else:
        print(f"\n  ⚠️ 有 {total_failed} 个测试失败，请检查。")

    return total_failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
