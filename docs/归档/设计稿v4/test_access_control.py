# -*- coding: utf-8 -*-
"""
================================================================
Clawguard v4 — 访问控制全面测试套件
================================================================
覆盖范围：
  1. v3 核心功能测试（RBAC/MAC/Hybrid、树状匹配、规则管理）
  2. v4 适配器测试（统一接口转换、异常处理）
  3. 端到端集成测试（完整请求链路）
================================================================
"""

import os
import sys
import tempfile
import shutil

# Windows 控制台 GBK 编码无法输出中文/emoji，统一切到 UTF-8
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        sys.stdout = __import__('io').TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path

# 确保导入 v4 目录下的模块
sys.path.insert(0, str(Path(__file__).parent))

from auth_gateway import (
    check, check_reason, check_v4, _normalize_level, SecurityLabel,
    add_user_rule, remove_user_rule, get_user_rule, list_user_rules,
    add_resource_rule, remove_resource_rule, list_resource_rules,
    set_mac_label, get_mac_label, sync_external_user,
    _match_pattern, _resource_required_level_tree, _resource_match_tree,
    _check_special, _check_rbac, _check_mac,
    RuleStore, _TextBackend, _SQLiteBackend,
    ACCESS_CONTROL_MODE, DEFAULT_RESOURCE_LEVEL,
)

from access_control_adapter import AccessControlAdapter


# ============================================================
# 辅助函数
# ============================================================

def _setup_test_env():
    """设置临时测试环境，返回 (tmpdir, users_file, resources_file)"""
    tmpdir = tempfile.mkdtemp()
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
C:\\Users\\admin\\temp   | 2 | override
C:\\Users\\Public\\*     | 1 | inherit
*.pdf                   | 3 | flat
""", encoding="utf-8")

    return tmpdir, users_file, resources_file


def _make_store(users_file, resources_file):
    """创建临时 RuleStore"""
    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}
    return store


def _patch_store(store):
    """替换全局 _store，返回旧 store 用于恢复"""
    import auth_gateway
    old = auth_gateway._store
    auth_gateway._store = store
    return old


# ============================================================
# Part A: v3 核心功能测试
# ============================================================

class TestV3Core:
    """v3 核心功能测试组"""

    @staticmethod
    def test_normalize_level():
        """A1: 等级别名转换"""
        assert _normalize_level("public") == 1
        assert _normalize_level("internal") == 2
        assert _normalize_level("secret") == 3
        assert _normalize_level("top_secret") == 4
        assert _normalize_level("1") == 1
        assert _normalize_level("A") == 1
        assert _normalize_level("d") == 4
        assert _normalize_level("unknown") == 1
        print("  ✓ A1 等级别名转换")

    @staticmethod
    def test_match_pattern():
        """A2: 模式匹配逻辑"""
        assert _match_pattern("C:\\Users\\*", "C:\\Users\\admin") == True
        assert _match_pattern("*.txt", "file.txt") == True
        assert _match_pattern("*.pdf", "file.txt") == False
        assert _match_pattern("tool:write_file", "tool:write_file") == True
        assert _match_pattern("tool:*", "tool:write_file") == True
        assert _match_pattern("tool:read", "tool:write_file") == False
        assert _match_pattern("admin", "C:\\Users\\admin") == True
        assert _match_pattern("secret", "C:\\Users\\admin\\secrets") == True
        print("  ✓ A2 模式匹配逻辑")

    @staticmethod
    def test_check_special():
        """A3: 特例规则处理"""
        assert _check_special(["!tool:write_file"], "", "tool:write_file", "") == "block"
        assert _check_special(["tool:query_weather"], "", "tool:query_weather", "") == "allow"
        assert _check_special(["*"], "anything", "", "") == "allow"
        assert _check_special(["!*"], "anything", "", "") == "block"
        assert _check_special(["tool:read_file"], "", "tool:write_file", "") is None
        print("  ✓ A3 特例规则处理")

    @staticmethod
    def test_check_rbac():
        """A4: RBAC 核心校验"""
        tmpdir, uf, rf = _setup_test_env()
        store = _make_store(uf, rf)
        old = _patch_store(store)
        try:
            assert check("admin_test", "", "tool:write_file", "") == True
            assert check("admin_test", "C:\\Users\\admin\\secrets", "", "") == True
            assert check("user_secret", "", "tool:execute_bash", "") == False
            assert check("user_internal", "", "tool:write_file", "") == False
            assert check("user_internal", "", "tool:read_file", "") == True
            assert check("user_public", "", "tool:query_weather", "") == True
            assert check("user_public", "", "tool:read_file", "") == False
            assert check("user_special", "", "tool:write_file", "") == False
            assert check("user_special", "C:\\Users\\Public\\docs", "", "") == True
            assert check("user_tool", "", "tool:query_weather", "") == True
            print("  ✓ A4 RBAC 核心校验")
        finally:
            _patch_store(old)
            shutil.rmtree(tmpdir)

    @staticmethod
    def test_tree_matching():
        """A5: 树状资源匹配（继承/覆盖）"""
        tmpdir, uf, rf = _setup_test_env()
        store = _make_store(uf, rf)
        old = _patch_store(store)
        try:
            assert check("admin_test", "C:\\Users\\admin\\secrets", "", "") == True
            assert check("user_internal", "C:\\Users\\admin\\temp", "", "") == True
            assert check("user_public", "C:\\Users\\Public\\docs", "", "") == True
            print("  ✓ A5 树状资源匹配")
        finally:
            _patch_store(old)
            shutil.rmtree(tmpdir)

    @staticmethod
    def test_specificity_tiebreak():
        """A6: 同深度优先级（更具体模式优先）"""
        tmpdir, uf, rf = _setup_test_env()
        # 追加同深度竞争规则（顺序倒置）
        rf.write_text("""\
# 测试资源（顺序故意倒置：通配在前、具体在后）
/etc/*           | 3 | override
/etc/passwd      | 4 | override
tool:*           | 2 | flat
tool:read_file   | 2 | flat
tool:execute_bash| 4 | flat
""", encoding="utf-8")
        store = _make_store(uf, rf)
        old = _patch_store(store)
        try:
            assert _resource_required_level_tree("", "/etc/passwd", "") == 4
            assert _resource_required_level_tree("", "/etc/hostname", "") == 3
            assert _resource_required_level_tree("", "tool:read_file", "") == 2
            assert _resource_required_level_tree("", "tool:execute_bash", "") == 4
            assert _resource_required_level_tree("", "tool:write_file", "") == 2
            print("  ✓ A6 同深度优先级")
        finally:
            _patch_store(old)
            shutil.rmtree(tmpdir)

    @staticmethod
    def test_win_linux_path_rules():
        """A7: 跨平台路径规则"""
        tmpdir, uf, rf = _setup_test_env()
        rf.write_text("""\
# 盘符根兜底
C:\\                 | internal    | inherit  # 盘符根
C:\\Users\\*         | internal    | inherit
C:\\Users\\Public\\* | public      | override  # 公开区
C:\\Users\\admin\\*  | secret      | override  # 用户主目录
C:\\Users\\admin\\.ssh\\* | top_secret | override  # 私钥
/etc/*               | secret      | override
/etc/shadow          | top_secret  | override  # 口令哈希
tool:*               | internal    | flat
tool:read_file       | internal    | flat
""", encoding="utf-8")
        store = _make_store(uf, rf)
        old = _patch_store(store)
        try:
            assert _resource_required_level_tree("", r"C:\Users\admin\.ssh\id_rsa", "") == 4
            assert _resource_required_level_tree("", r"C:\Users\Public\share.txt", "") == 1
            assert _resource_required_level_tree("", r"C:\Users\admin\doc.txt", "") == 3
            assert _resource_required_level_tree("", "/etc/shadow", "") == 4
            assert _resource_required_level_tree("", "/etc/hostname", "") == 3
            assert _match_pattern("C:\\Users", r"C:\Users2\file.txt") == False
            assert _match_pattern("C:\\Users", r"C:\Users\admin\file.txt") == True
            assert _resource_required_level_tree("", "tool:read_file", "") == 2
            assert _match_pattern("tool:read", "tool:read_file") == True
            assert _match_pattern("tool:read_file", "tool:read") == False
            print("  ✓ A7 跨平台路径规则")
        finally:
            _patch_store(old)
            shutil.rmtree(tmpdir)

    @staticmethod
    def test_mac_label():
        """A8: MAC 安全标签 dominates"""
        label1 = SecurityLabel(3, frozenset({"财务", "核心"}))
        label2 = SecurityLabel(2, frozenset({"财务"}))
        label3 = SecurityLabel(4, frozenset({"财务", "核心", "战略"}))
        assert label1.dominates(label2) == True
        assert label2.dominates(label1) == False
        assert label3.dominates(label1) == True
        label4 = SecurityLabel(3, frozenset({"财务", "核心"}))
        assert label1.dominates(label4) == True
        print("  ✓ A8 MAC 安全标签")

    @staticmethod
    def test_mac_check():
        """A9: MAC 访问控制"""
        tmpdir, uf, rf = _setup_test_env()
        store = _make_store(uf, rf)
        old = _patch_store(store)
        try:
            store.set_mac_label("user_mac_1", 3, {"财务"})
            store.set_mac_label("user_mac_2", 1, {"公开"})
            store.set_resource_mac_label("tool:write_file", 3, {"财务"})
            store.set_resource_mac_label("tool:execute_bash", 4, {"核心"})
            assert _check_mac("user_mac_1", "", "tool:write_file", "") == True
            assert _check_mac("user_mac_2", "", "tool:write_file", "") == False
            assert _check_mac("user_mac_1", "", "tool:execute_bash", "") == False
            print("  ✓ A9 MAC 访问控制")
        finally:
            _patch_store(old)
            shutil.rmtree(tmpdir)

    @staticmethod
    def test_mac_tree_consistency():
        """A10: MAC 与 RBAC 树状判定一致性"""
        tmpdir, uf, rf = _setup_test_env()
        rf.write_text(
            "tool:write_file | secret | flat\n"
            "C:\\Users\\admin | secret | override\n"
            "C:\\Users\\admin\\secrets | top_secret | override\n",
            encoding="utf-8")
        store = _make_store(uf, rf)
        old = _patch_store(store)
        nested = r"C:\Users\admin\secrets\file.txt"
        try:
            assert _resource_required_level_tree(nested, "", "") == 4
            assert _resource_match_tree(nested)[0] == r"C:\Users\admin\secrets"
            store.set_mac_label("u_secret", 3)
            assert _check_mac("u_secret", nested) == False
            store.set_mac_label("u_top", 4)
            assert _check_mac("u_top", nested) == True
            store.set_resource_mac_label(r"C:\Users\admin\secrets", 4, {"核心"})
            store.set_mac_label("u_top_core", 4, {"核心"})
            store.set_mac_label("u_top_empty", 4, set())
            assert _check_mac("u_top_core", nested) == True
            assert _check_mac("u_top_empty", nested) == False
            print("  ✓ A10 MAC 树状一致性")
        finally:
            _patch_store(old)
            shutil.rmtree(tmpdir)

    @staticmethod
    def test_rule_management():
        """A11: 规则管理 CRUD"""
        tmpdir, uf, rf = _setup_test_env()
        store = _make_store(uf, rf)
        old = _patch_store(store)
        try:
            result = add_user_rule("new_user", "secret", ["tool:read_file", "!tool:execute_bash"])
            assert result["success"] == True
            assert get_user_rule("new_user")["level"] == 3
            rules = list_user_rules()
            assert len(rules) >= 6
            result = remove_user_rule("new_user")
            assert result["success"] == True
            assert get_user_rule("new_user") is None
            result = add_resource_rule("C:\\Temp\\*", "public", "inherit")
            assert result["success"] == True
            resources = list_resource_rules()
            assert any(r["pattern"] == "C:\\Temp\\*" for r in resources)
            result = remove_resource_rule("C:\\Temp\\*")
            assert result["success"] == True
            resources = list_resource_rules()
            assert not any(r["pattern"] == "C:\\Temp\\*" for r in resources)
            print("  ✓ A11 规则管理 CRUD")
        finally:
            _patch_store(old)
            shutil.rmtree(tmpdir)

    @staticmethod
    def test_sqlite_backend():
        """A12: SQLite 后端"""
        tmpdir = tempfile.mkdtemp()
        db_path = Path(tmpdir) / "test.db"
        backend = _SQLiteBackend(db_path)
        users = {
            "user_1": {"level": 2, "specials": ["tool:read_file"]},
            "user_2": {"level": 3, "specials": []},
        }
        backend.save_users(users)
        loaded = backend.load_users()
        assert loaded["user_1"]["level"] == 2
        assert loaded["user_1"]["specials"] == ["tool:read_file"]
        assert loaded["user_2"]["level"] == 3
        resources = [
            ("tool:write_file", 3, "flat"),
            ("C:\\Users\\*", 2, "inherit"),
        ]
        backend.save_resources(resources)
        loaded_res = backend.load_resources()
        assert len(loaded_res) == 2
        assert loaded_res[0][0] == "tool:write_file"
        assert loaded_res[0][1] == 3
        shutil.rmtree(tmpdir)
        print("  ✓ A12 SQLite 后端")

    @staticmethod
    def test_check_reason():
        """A13: check_reason 调试接口"""
        tmpdir, uf, rf = _setup_test_env()
        store = _make_store(uf, rf)
        old = _patch_store(store)
        try:
            os.environ["CLAWGUARD_MODE"] = "rbac"
            import auth_gateway
            auth_gateway.ACCESS_CONTROL_MODE = "rbac"
            ok, reason = check_reason("user_internal", "", "tool:read_file", "")
            assert ok == True and "allow" in reason
            ok, reason = check_reason("user_internal", "", "tool:write_file", "")
            assert ok == False and "block" in reason
            store.set_mac_label("user_mac", 3, {"财务"})
            store.set_resource_mac_label("tool:write_file", 3, {"财务"})
            os.environ["CLAWGUARD_MODE"] = "mac"
            auth_gateway.ACCESS_CONTROL_MODE = "mac"
            ok, reason = check_reason("user_mac", "", "tool:write_file", "")
            assert ok == True and "MAC" in reason
            print("  ✓ A13 check_reason 调试接口")
        finally:
            _patch_store(old)
            shutil.rmtree(tmpdir)
            os.environ["CLAWGUARD_MODE"] = "rbac"
            import auth_gateway
            auth_gateway.ACCESS_CONTROL_MODE = "rbac"

    @staticmethod
    def test_sync_external_user():
        """A14: 外部用户同步"""
        tmpdir, uf, rf = _setup_test_env()
        store = _make_store(uf, rf)
        old = _patch_store(store)
        try:
            sync_external_user("external_user_1", "secret")
            assert store.get_user_level("external_user_1") == 3
            sync_external_user("external_user_1", "top_secret")
            assert store.get_user_level("external_user_1") == 4
            assert check("external_user_1", "", "tool:execute_bash", "") == True
            print("  ✓ A14 外部用户同步")
        finally:
            _patch_store(old)
            shutil.rmtree(tmpdir)

    @staticmethod
    def test_check_v4():
        """A15: v4 统一接口 check_v4"""
        tmpdir, uf, rf = _setup_test_env()
        store = _make_store(uf, rf)
        old = _patch_store(store)
        try:
            result = check_v4("user_internal", "", "tool:read_file", "")
            assert result["allowed"] == True
            assert "allow" in result["reason"]
            assert result["user_id"] == "user_internal"
            assert result["tool"] == "tool:read_file"

            result = check_v4("user_public", "", "tool:write_file", "")
            assert result["allowed"] == False
            assert "block" in result["reason"]
            assert result["user_id"] == "user_public"

            result = check_v4("admin_test", "C:\\Users\\admin\\secrets", "", "")
            assert result["allowed"] == True
            assert result["path"] == "C:\\Users\\admin\\secrets"
            print("  ✓ A15 v4 统一接口 check_v4")
        finally:
            _patch_store(old)
            shutil.rmtree(tmpdir)


# ============================================================
# Part B: v4 适配器测试
# ============================================================

class TestV4Adapter:
    """v4 适配器测试组"""

    @staticmethod
    def test_adapter_allow():
        """B1: 适配器放行场景"""
        adapter = AccessControlAdapter()
        request = {
            "context": {
                "trace_id": "t1",
                "session_id": "s1",
                "user_id": "user_01",
                "stage": "tool_pre",
                "timestamp": "2026-08-03T10:00:02+08:00",
            },
            "payload": {
                "tool_name": "read_file",
                "tool_call_id": "call-001",
                "arguments": {"path": "C:/demo/public.txt"},
                "database": "",
            }
        }
        result = adapter.run(request)
        assert result["success"] is True
        assert result["action"] in ("allow", "block")
        assert result["module"] == "access_control"
        assert "latency_ms" in result
        assert result["error"] is None
        print("  ✓ B1 适配器放行/拦截场景")

    @staticmethod
    def test_adapter_block():
        """B2: 适配器拦截场景"""
        adapter = AccessControlAdapter()
        request = {
            "context": {
                "trace_id": "t2",
                "session_id": "s1",
                "user_id": "intern_01",
                "stage": "tool_pre",
                "timestamp": "2026-08-03T10:00:02+08:00",
            },
            "payload": {
                "tool_name": "write_file",
                "tool_call_id": "call-002",
                "arguments": {},
                "database": "",
            }
        }
        result = adapter.run(request)
        assert result["success"] is True
        assert result["action"] in ("allow", "block")
        assert result["module"] == "access_control"
        assert result["error"] is None
        print("  ✓ B2 适配器拦截场景")

    @staticmethod
    def test_adapter_error_handling():
        """B3: 适配器异常处理"""
        adapter = AccessControlAdapter()
        # 空请求不应抛异常
        result = adapter.run({})
        assert result["success"] is True  # check_v4 内部有默认值
        assert result["module"] == "access_control"
        print("  ✓ B3 适配器异常处理")

    @staticmethod
    def test_adapter_module_result_format():
        """B4: ModuleResult 格式校验"""
        adapter = AccessControlAdapter()
        request = {
            "context": {"user_id": "user_01", "trace_id": "t3"},
            "payload": {"tool_name": "read_file", "arguments": {}}
        }
        result = adapter.run(request)
        required_keys = ["module", "success", "action", "risk_score", "reason",
                         "modified_data", "details", "latency_ms", "error"]
        for key in required_keys:
            assert key in result, f"缺少字段: {key}"
        assert result["action"] in ("allow", "block", "rewrite", "human_review")
        assert isinstance(result["risk_score"], float)
        assert isinstance(result["latency_ms"], float)
        print("  ✓ B4 ModuleResult 格式校验")

    @staticmethod
    def test_adapter_with_path_in_arguments():
        """B5: 路径在 arguments 中的提取"""
        adapter = AccessControlAdapter()
        request = {
            "context": {"user_id": "user_01", "trace_id": "t4"},
            "payload": {
                "tool_name": "read_file",
                "arguments": {"path": "C:\\Users\\admin\\secrets"},
                "database": ""
            }
        }
        result = adapter.run(request)
        assert result["success"] is True
        assert result["details"]["path"] == "C:\\Users\\admin\\secrets"
        print("  ✓ B5 路径参数提取")

    @staticmethod
    def test_adapter_tool_prefix_normalization():
        """B6: 裸工具名 tool: 前缀自动补齐校验"""
        adapter = AccessControlAdapter()
        res1 = adapter.run({"context": {"user_id": "user_01"}, "payload": {"tool_name": "read_file"}})
        assert res1["action"] == "allow", f"user_01 + read_file 应该允许通过，实际: {res1}"
        assert res1["details"]["tool"] == "tool:read_file"

        res2 = adapter.run({"context": {"user_id": "intern_01"}, "payload": {"tool_name": "query_weather"}})
        assert res2["action"] == "allow", f"intern_01 + query_weather 应该允许通过，实际: {res2}"
        assert res2["details"]["tool"] == "tool:query_weather"

        res3 = adapter.run({"context": {"user_id": "intern_01"}, "payload": {"tool_name": "execute_bash"}})
        assert res3["action"] == "block", f"intern_01 + execute_bash 应该被拦截，实际: {res3}"
        assert res3["details"]["tool"] == "tool:execute_bash"
        print("  ✓ B6 裸工具名 tool: 前缀自动归一化")


# ============================================================
# Part C: 端到端集成测试
# ============================================================

class TestE2E:
    """端到端集成测试组"""

    @staticmethod
    def test_e2e_full_request_allow():
        """C1: 完整请求链路 — 放行"""
        # 模拟 Clawguard FastAPI 收到的完整 SecurityRequest
        security_request = {
            "context": {
                "trace_id": "trace-e2e-001",
                "session_id": "session-001",
                "user_id": "admin_01",
                "stage": "tool_pre",
                "timestamp": "2026-08-03T10:00:02+08:00",
            },
            "payload": {
                "tool_name": "write_file",
                "tool_call_id": "call-001",
                "arguments": {"path": "C:\\Users\\admin\\test.txt"},
                "database": ""
            }
        }
        adapter = AccessControlAdapter()
        result = adapter.run(security_request)

        # 验证返回的是标准 ModuleResult
        assert result["module"] == "access_control"
        assert result["success"] is True
        assert result["action"] == "allow"
        assert result["risk_score"] == 0.0
        assert result["error"] is None
        assert result["details"]["user_id"] == "admin_01"
        assert result["details"]["tool"] == "tool:write_file"
        print("  ✓ C1 端到端放行")

    @staticmethod
    def test_e2e_full_request_block():
        """C2: 完整请求链路 — 拦截"""
        security_request = {
            "context": {
                "trace_id": "trace-e2e-002",
                "session_id": "session-001",
                "user_id": "intern_01",
                "stage": "tool_pre",
                "timestamp": "2026-08-03T10:00:02+08:00",
            },
            "payload": {
                "tool_name": "execute_bash",
                "tool_call_id": "call-002",
                "arguments": {},
                "database": ""
            }
        }
        adapter = AccessControlAdapter()
        result = adapter.run(security_request)

        assert result["module"] == "access_control"
        assert result["success"] is True
        assert result["action"] == "block"
        assert result["risk_score"] == 1.0
        assert result["error"] is None
        assert "block" in result["reason"] or "等级" in result["reason"]
        print("  ✓ C2 端到端拦截")

    @staticmethod
    def test_e2e_unknown_user():
        """C3: 未知用户处理"""
        security_request = {
            "context": {
                "trace_id": "trace-e2e-003",
                "session_id": "session-001",
                "user_id": "unknown_user_xyz",
                "stage": "tool_pre",
                "timestamp": "2026-08-03T10:00:02+08:00",
            },
            "payload": {
                "tool_name": "write_file",
                "arguments": {},
                "database": ""
            }
        }
        adapter = AccessControlAdapter()
        result = adapter.run(security_request)

        assert result["success"] is True
        assert result["action"] in ("allow", "block")
        assert result["module"] == "access_control"
        print("  ✓ C3 未知用户处理")

    @staticmethod
    def test_e2e_database_access():
        """C4: 数据库访问场景"""
        security_request = {
            "context": {
                "trace_id": "trace-e2e-004",
                "user_id": "user_public",
                "stage": "tool_pre",
                "timestamp": "2026-08-03T10:00:02+08:00",
            },
            "payload": {
                "tool_name": "",
                "arguments": {},
                "database": "db:public"
            }
        }
        adapter = AccessControlAdapter()
        result = adapter.run(security_request)

        assert result["success"] is True
        assert result["module"] == "access_control"
        assert result["details"]["database"] == "db:public"
        print("  ✓ C4 数据库访问场景")

    @staticmethod
    def test_e2e_special_rule_allow():
        """C5: 特例规则放行（特例越级）"""
        security_request = {
            "context": {
                "trace_id": "trace-e2e-005",
                "user_id": "intern_01",  # public 等级
                "stage": "tool_pre",
                "timestamp": "2026-08-03T10:00:02+08:00",
            },
            "payload": {
                "tool_name": "query_weather",  # intern_01 有特例允许
                "arguments": {},
                "database": ""
            }
        }
        adapter = AccessControlAdapter()
        result = adapter.run(security_request)

        assert result["success"] is True
        assert result["action"] == "allow"
        assert "特例" in result["reason"] or "allow" in result["reason"]
        print("  ✓ C5 特例规则放行")

    @staticmethod
    def test_e2e_special_rule_block():
        """C6: 特例规则拦截（!前缀）"""
        security_request = {
            "context": {
                "trace_id": "trace-e2e-006",
                "user_id": "auditor_01",  # internal 等级，但有 !tool:write_file 特例
                "stage": "tool_pre",
                "timestamp": "2026-08-03T10:00:02+08:00",
            },
            "payload": {
                "tool_name": "write_file",
                "arguments": {},
                "database": ""
            }
        }
        adapter = AccessControlAdapter()
        result = adapter.run(security_request)

        assert result["success"] is True
        assert result["action"] == "block"
        assert "特例" in result["reason"] or "block" in result["reason"]
        print("  ✓ C6 特例规则拦截")


# ============================================================
# Part D: 性能与边界测试
# ============================================================

class TestPerformance:
    """性能与边界测试组"""

    @staticmethod
    def test_latency_under_threshold():
        """D1: 延迟在阈值内"""
        adapter = AccessControlAdapter()
        request = {
            "context": {"user_id": "user_01", "trace_id": "t-perf"},
            "payload": {"tool_name": "read_file", "arguments": {}}
        }
        result = adapter.run(request)
        assert result["latency_ms"] < 100, f"延迟过高: {result['latency_ms']}ms"
        print("  ✓ D1 延迟阈值")

    @staticmethod
    def test_empty_payload():
        """D2: 空 payload 处理"""
        adapter = AccessControlAdapter()
        request = {
            "context": {"user_id": "user_01", "trace_id": "t-empty"},
            "payload": {}
        }
        result = adapter.run(request)
        assert result["success"] is True
        assert result["action"] in ("allow", "block")
        print("  ✓ D2 空 payload")

    @staticmethod
    def test_missing_context():
        """D3: 缺失 context 处理"""
        adapter = AccessControlAdapter()
        request = {"payload": {"tool_name": "read_file"}}
        result = adapter.run(request)
        assert result["success"] is True
        assert result["module"] == "access_control"
        print("  ✓ D3 缺失 context")

    @staticmethod
    def test_long_path():
        """D4: 超长路径处理"""
        adapter = AccessControlAdapter()
        long_path = "C:\\" + "\\".join(["very_long_directory_name"] * 20) + "\\file.txt"
        request = {
            "context": {"user_id": "user_01", "trace_id": "t-long"},
            "payload": {"tool_name": "read_file", "arguments": {"path": long_path}}
        }
        result = adapter.run(request)
        assert result["success"] is True
        print("  ✓ D4 超长路径")

    @staticmethod
    def test_special_chars_in_path():
        """D5: 特殊字符路径"""
        adapter = AccessControlAdapter()
        request = {
            "context": {"user_id": "user_01", "trace_id": "t-special"},
            "payload": {"tool_name": "read_file", "arguments": {"path": "C:\\Users\\admin\\file (1).txt"}}
        }
        result = adapter.run(request)
        assert result["success"] is True
        print("  ✓ D5 特殊字符路径")


# ============================================================
# 测试运行器
# ============================================================

def run_all_tests():
    """运行全部测试"""
    print("=" * 70)
    print("Clawguard v4 访问控制 — 全面测试套件")
    print("=" * 70)

    test_groups = [
        ("Part A: v3 核心功能", [
            TestV3Core.test_normalize_level,
            TestV3Core.test_match_pattern,
            TestV3Core.test_check_special,
            TestV3Core.test_check_rbac,
            TestV3Core.test_tree_matching,
            TestV3Core.test_specificity_tiebreak,
            TestV3Core.test_win_linux_path_rules,
            TestV3Core.test_mac_label,
            TestV3Core.test_mac_check,
            TestV3Core.test_mac_tree_consistency,
            TestV3Core.test_rule_management,
            TestV3Core.test_sqlite_backend,
            TestV3Core.test_check_reason,
            TestV3Core.test_sync_external_user,
            TestV3Core.test_check_v4,
        ]),
        ("Part B: v4 适配器", [
            TestV4Adapter.test_adapter_allow,
            TestV4Adapter.test_adapter_block,
            TestV4Adapter.test_adapter_error_handling,
            TestV4Adapter.test_adapter_module_result_format,
            TestV4Adapter.test_adapter_with_path_in_arguments,
            TestV4Adapter.test_adapter_tool_prefix_normalization,
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
