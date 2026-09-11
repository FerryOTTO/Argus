# -*- coding: utf-8 -*-
"""
Clawguard v3 测试套件
test_auth_gateway.py
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

# 确保导入 v3 的 auth_gateway
sys.path.insert(0, str(Path(__file__).parent))
from auth_gateway import (
    check, check_reason, _normalize_level, SecurityLabel,
    add_user_rule, remove_user_rule, get_user_rule, list_user_rules,
    add_resource_rule, remove_resource_rule, list_resource_rules,
    set_mac_label, get_mac_label, sync_external_user,
    _match_pattern, _resource_required_level_tree, _resource_match_tree,
    _check_special, _check_rbac, _check_mac,
    RuleStore, _TextBackend, _SQLiteBackend,
    ACCESS_CONTROL_MODE, DEFAULT_RESOURCE_LEVEL,
)


# ============================================================
# 辅助函数
# ============================================================

def _setup_test_env():
    """设置临时测试环境"""
    tmpdir = tempfile.mkdtemp()
    users_file = Path(tmpdir) / "users.txt"
    resources_file = Path(tmpdir) / "resources.txt"

    # 写入测试用户规则
    users_file.write_text("""\
# 测试用户
admin_test      | top_secret | *
user_internal   | internal   |
user_secret     | secret     |
user_public     | public     |
user_special    | internal   | !tool:write_file, C:\\Users\\Public\\*
user_tool       | public     | tool:query_weather
""", encoding="utf-8")

    # 写入测试资源规则
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


# ============================================================
# 测试 1: 基础等级转换
# ============================================================

def test_normalize_level():
    """测试等级别名转换"""
    assert _normalize_level("public") == 1
    assert _normalize_level("internal") == 2
    assert _normalize_level("secret") == 3
    assert _normalize_level("top_secret") == 4
    assert _normalize_level("1") == 1
    assert _normalize_level("A") == 1
    assert _normalize_level("d") == 4
    assert _normalize_level("unknown") == 1  # 默认 fallback
    print("✓ test_normalize_level passed")


# ============================================================
# 测试 2: 模式匹配
# ============================================================

def test_match_pattern():
    """测试模式匹配逻辑"""
    # glob 匹配
    assert _match_pattern("C:\\Users\\*", "C:\\Users\\admin") == True
    assert _match_pattern("*.txt", "file.txt") == True
    assert _match_pattern("*.pdf", "file.txt") == False

    # 工具匹配
    assert _match_pattern("tool:write_file", "tool:write_file") == True
    assert _match_pattern("tool:*", "tool:write_file") == True
    assert _match_pattern("tool:read", "tool:write_file") == False

    # 子串匹配
    assert _match_pattern("admin", "C:\\Users\\admin") == True
    assert _match_pattern("secret", "C:\\Users\\admin\\secrets") == True

    print("✓ test_match_pattern passed")


# ============================================================
# 测试 3: 特例规则
# ============================================================

def test_check_special():
    """测试特例规则处理"""
    # !前缀 = 禁止
    assert _check_special(["!tool:write_file"], "", "tool:write_file", "") == "block"
    # 无 ! = 允许
    assert _check_special(["tool:query_weather"], "", "tool:query_weather", "") == "allow"
    # * = 允许所有
    assert _check_special(["*"], "anything", "", "") == "allow"
    # !* = 禁止所有
    assert _check_special(["!*"], "anything", "", "") == "block"
    # 无命中
    assert _check_special(["tool:read_file"], "", "tool:write_file", "") is None

    print("✓ test_check_special passed")


# ============================================================
# 测试 4: RBAC 核心校验
# ============================================================

def test_check_rbac():
    """测试 RBAC 访问控制（需要临时环境）"""
    tmpdir, users_file, resources_file = _setup_test_env()

    # 创建临时 RuleStore
    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}

    # 替换全局 store
    import auth_gateway
    old_store = auth_gateway._store
    auth_gateway._store = store

    try:
        # admin 全权限
        assert check("admin_test", "", "tool:write_file", "") == True
        assert check("admin_test", "C:\\Users\\admin\\secrets", "", "") == True

        # secret 用户不能执行 bash（需要 top_secret=4）
        assert check("user_secret", "", "tool:execute_bash", "") == False

        # internal 用户不能写文件（需要 secret=3）
        assert check("user_internal", "", "tool:write_file", "") == False

        # internal 用户可以读文件（需要 internal=2）
        assert check("user_internal", "", "tool:read_file", "") == True

        # public 用户只能查天气
        assert check("user_public", "", "tool:query_weather", "") == True
        assert check("user_public", "", "tool:read_file", "") == False

        # 特例：user_special 禁止写文件（尽管等级够）
        assert check("user_special", "", "tool:write_file", "") == False

        # 特例：user_special 允许访问 Public 目录
        assert check("user_special", "C:\\Users\\Public\\docs", "", "") == True

        # 特例：user_tool 允许查天气（等级 public=1 不够，但特例放行）
        assert check("user_tool", "", "tool:query_weather", "") == True

        print("✓ test_check_rbac passed")
    finally:
        auth_gateway._store = old_store
        shutil.rmtree(tmpdir)


# ============================================================
# 测试 5: 树状资源匹配
# ============================================================

def test_tree_matching():
    """测试树状资源匹配（继承/覆盖）"""
    tmpdir, users_file, resources_file = _setup_test_env()

    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}

    import auth_gateway
    old_store = auth_gateway._store
    auth_gateway._store = store

    try:
        # C:\Users\admin\secrets 需要 level=4（override 模式）
        # top_secret 用户 (level=4) 可以访问
        assert check("admin_test", "C:\\Users\\admin\\secrets", "", "") == True

        # C:\Users\admin\temp 需要 level=2（override 模式）
        # internal 用户 (level=2) 可以访问
        assert check("user_internal", "C:\\Users\\admin\\temp", "", "") == True

        # C:\Users\Public\* 需要 level=1（inherit 模式）
        # public 用户可以访问
        assert check("user_public", "C:\\Users\\Public\\docs", "", "") == True

        print("✓ test_tree_matching passed")
    finally:
        auth_gateway._store = old_store
        shutil.rmtree(tmpdir)


# ============================================================
# 测试 6: 同深度优先级（更具体模式优先）
# ============================================================

def test_specificity_tiebreak():
    """同深度竞争时，更具体的模式应优先（与文件顺序无关）"""
    tmpdir, users_file, resources_file = _setup_test_env()

    # 追加一组同深度竞争的规则：目录通配 + 具体文件 + 工具通配 + 具体工具
    resources_file.write_text("""\
# 测试资源（顺序故意倒置：通配在前、具体在后）
/etc/*           | 3 | override
/etc/passwd      | 4 | override
tool:*           | 2 | flat
tool:read_file   | 2 | flat
tool:execute_bash| 4 | flat
""", encoding="utf-8")

    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}

    import auth_gateway
    old_store = auth_gateway._store
    auth_gateway._store = store

    try:
        # 具体文件 /etc/passwd (4) 应盖过目录通配 /etc/* (3)，与文件顺序无关
        assert _resource_required_level_tree("", "/etc/passwd", "") == 4
        # 其他 /etc 下文件仍走目录规则
        assert _resource_required_level_tree("", "/etc/hostname", "") == 3
        # 具体工具 tool:read_file 应盖过 tool:* 通配
        assert _resource_required_level_tree("", "tool:read_file", "") == 2
        assert _resource_required_level_tree("", "tool:execute_bash", "") == 4
        assert _resource_required_level_tree("", "tool:write_file", "") == 2
        print("✓ test_specificity_tiebreak passed")
    finally:
        auth_gateway._store = old_store
        shutil.rmtree(tmpdir)


# ============================================================
# 测试 7: 跨平台路径规则（盘符深度/行内注释/路径边界）
# ============================================================

def test_win_linux_path_rules():
    """Windows 盘符深度、Linux 深度、行内注释、路径边界"""
    tmpdir, users_file, resources_file = _setup_test_env()

    # 带行内注释的第三列 + Windows/Linux 混合路径
    resources_file.write_text("""\
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

    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}

    import auth_gateway
    old_store = auth_gateway._store
    auth_gateway._store = store

    try:
        # 行内注释不再破坏 override，且 Windows 盘符按真实层级计深度
        assert _resource_required_level_tree("", r"C:\Users\admin\.ssh\id_rsa", "") == 4
        assert _resource_required_level_tree("", r"C:\Users\Public\share.txt", "") == 1
        assert _resource_required_level_tree("", r"C:\Users\admin\doc.txt", "") == 3
        # Linux 具体文件盖过目录通配
        assert _resource_required_level_tree("", "/etc/shadow", "") == 4
        assert _resource_required_level_tree("", "/etc/hostname", "") == 3
        # 路径边界：C:\Users 不误中 C:\Users2（分隔符边界而非子串）
        assert _match_pattern("C:\\Users", r"C:\Users2\file.txt") == False
        assert _match_pattern("C:\\Users", r"C:\Users\admin\file.txt") == True
        # 命名空间规则与路径规则互不干扰
        assert _resource_required_level_tree("", "tool:read_file", "") == 2
        assert _match_pattern("tool:read", "tool:read_file") == True
        assert _match_pattern("tool:read_file", "tool:read") == False
        print("✓ test_win_linux_path_rules passed")
    finally:
        auth_gateway._store = old_store
        shutil.rmtree(tmpdir)


# ============================================================
# 测试 8: MAC 安全标签
# ============================================================

def test_mac_label():
    """测试 MAC 安全标签"""
    label1 = SecurityLabel(3, frozenset({"财务", "核心"}))
    label2 = SecurityLabel(2, frozenset({"财务"}))
    label3 = SecurityLabel(4, frozenset({"财务", "核心", "战略"}))

    # label1 (3, {财务,核心}) dominates label2 (2, {财务})
    assert label1.dominates(label2) == True

    # label2 (2, {财务}) 不能 dominates label1 (3, {财务,核心})
    assert label2.dominates(label1) == False

    # label3 (4, {财务,核心,战略}) dominates label1
    assert label3.dominates(label1) == True

    # 相同等级和类别
    label4 = SecurityLabel(3, frozenset({"财务", "核心"}))
    assert label1.dominates(label4) == True

    print("✓ test_mac_label passed")


def test_mac_check():
    """测试 MAC 访问控制"""
    tmpdir, users_file, resources_file = _setup_test_env()

    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}

    import auth_gateway
    old_store = auth_gateway._store
    auth_gateway._store = store

    # 设置 MAC 标签
    store.set_mac_label("user_mac_1", 3, {"财务"})
    store.set_mac_label("user_mac_2", 1, {"公开"})
    store.set_resource_mac_label("tool:write_file", 3, {"财务"})
    store.set_resource_mac_label("tool:execute_bash", 4, {"核心"})

    try:
        # user_mac_1 (3, {财务}) 可以访问 tool:write_file (3, {财务})
        assert _check_mac("user_mac_1", "", "tool:write_file", "") == True

        # user_mac_2 (1, {公开}) 不能访问 tool:write_file (3, {财务})
        assert _check_mac("user_mac_2", "", "tool:write_file", "") == False

        # user_mac_1 (3, {财务}) 不能访问 tool:execute_bash (4, {核心}) — 等级不够
        assert _check_mac("user_mac_1", "", "tool:execute_bash", "") == False

        print("✓ test_mac_check passed")
    finally:
        auth_gateway._store = old_store
        shutil.rmtree(tmpdir)


# ============================================================
# 测试 7: MAC 与 RBAC 树状判定一致性
# ============================================================

def test_mac_tree_consistency():
    """MAC 分支须用树状匹配解析资源标签，与 RBAC 结果一致（修复平铺首匹配漏洞）"""
    tmpdir, users_file, resources_file = _setup_test_env()

    # 嵌套路径：通配/浅层规则在前，深层 override 在后（顺序倒置以暴露平铺匹配问题）
    resources_file.write_text(
        "tool:write_file | secret | flat\n"
        "C:\\Users\\admin | secret | override\n"
        "C:\\Users\\admin\\secrets | top_secret | override\n",
        encoding="utf-8")

    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}

    import auth_gateway
    old_store = auth_gateway._store
    auth_gateway._store = store

    nested = r"C:\Users\admin\secrets\file.txt"
    try:
        # 树状匹配应解析到更深一层 top_secret(4)，而非浅层 secret(3)
        assert _resource_required_level_tree(nested, "", "") == 4
        assert _resource_match_tree(nested)[0] == r"C:\Users\admin\secrets"

        # 修复前：平铺首匹配解析到 C:\Users\admin(3)，secret 用户被错误放行
        store.set_mac_label("u_secret", 3)
        assert _check_mac("u_secret", nested) == False
        store.set_mac_label("u_top", 4)
        assert _check_mac("u_top", nested) == True

        # 显式资源 MAC 标签挂在树状最优模式上，类别隔离仍生效
        store.set_resource_mac_label(r"C:\Users\admin\secrets", 4, {"核心"})
        store.set_mac_label("u_top_core", 4, {"核心"})
        store.set_mac_label("u_top_empty", 4, set())
        assert _check_mac("u_top_core", nested) == True
        assert _check_mac("u_top_empty", nested) == False   # 缺类别 → 拦截

        print("✓ test_mac_tree_consistency passed")
    finally:
        auth_gateway._store = old_store
        shutil.rmtree(tmpdir)


# ============================================================
# 测试 7: 规则管理接口
# ============================================================

def test_rule_management():
    """测试规则的增删改查"""
    tmpdir, users_file, resources_file = _setup_test_env()

    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}

    import auth_gateway
    old_store = auth_gateway._store
    auth_gateway._store = store

    try:
        # 添加用户规则
        result = add_user_rule("new_user", "secret", ["tool:read_file", "!tool:execute_bash"])
        assert result["success"] == True
        assert get_user_rule("new_user")["level"] == 3

        # 列出用户规则
        rules = list_user_rules()
        assert len(rules) >= 6  # 原有5个 + 新增1个

        # 删除用户规则
        result = remove_user_rule("new_user")
        assert result["success"] == True
        assert get_user_rule("new_user") is None

        # 添加资源规则
        result = add_resource_rule("C:\\Temp\\*", "public", "inherit")
        assert result["success"] == True

        # 列出资源规则
        resources = list_resource_rules()
        assert any(r["pattern"] == "C:\\Temp\\*" for r in resources)

        # 删除资源规则
        result = remove_resource_rule("C:\\Temp\\*")
        assert result["success"] == True
        resources = list_resource_rules()
        assert not any(r["pattern"] == "C:\\Temp\\*" for r in resources)

        print("✓ test_rule_management passed")
    finally:
        auth_gateway._store = old_store
        shutil.rmtree(tmpdir)


# ============================================================
# 测试 8: 多后端支持
# ============================================================

def test_sqlite_backend():
    """测试 SQLite 后端"""
    tmpdir = tempfile.mkdtemp()
    db_path = Path(tmpdir) / "test.db"

    backend = _SQLiteBackend(db_path)

    # 保存用户
    users = {
        "user_1": {"level": 2, "specials": ["tool:read_file"]},
        "user_2": {"level": 3, "specials": []},
    }
    backend.save_users(users)

    # 读取用户
    loaded = backend.load_users()
    assert loaded["user_1"]["level"] == 2
    assert loaded["user_1"]["specials"] == ["tool:read_file"]
    assert loaded["user_2"]["level"] == 3

    # 保存资源
    resources = [
        ("tool:write_file", 3, "flat"),
        ("C:\\Users\\*", 2, "inherit"),
    ]
    backend.save_resources(resources)

    # 读取资源
    loaded_res = backend.load_resources()
    assert len(loaded_res) == 2
    assert loaded_res[0][0] == "tool:write_file"
    assert loaded_res[0][1] == 3

    shutil.rmtree(tmpdir)
    print("✓ test_sqlite_backend passed")


# ============================================================
# 测试 9: check_reason 调试接口
# ============================================================

def test_check_reason():
    """测试 check_reason 返回详细原因"""
    tmpdir, users_file, resources_file = _setup_test_env()

    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}

    import auth_gateway
    old_store = auth_gateway._store
    auth_gateway._store = store

    try:
        # 测试 RBAC 模式
        os.environ["CLAWGUARD_MODE"] = "rbac"
        auth_gateway.ACCESS_CONTROL_MODE = "rbac"
        ok, reason = check_reason("user_internal", "", "tool:read_file", "")
        assert ok == True
        assert "allow" in reason

        ok, reason = check_reason("user_internal", "", "tool:write_file", "")
        assert ok == False
        assert "block" in reason

        # 测试 MAC 模式
        store.set_mac_label("user_mac", 3, {"财务"})
        store.set_resource_mac_label("tool:write_file", 3, {"财务"})
        os.environ["CLAWGUARD_MODE"] = "mac"
        auth_gateway.ACCESS_CONTROL_MODE = "mac"
        ok, reason = check_reason("user_mac", "", "tool:write_file", "")
        assert ok == True
        assert "MAC" in reason

        print("✓ test_check_reason passed")
    finally:
        auth_gateway._store = old_store
        shutil.rmtree(tmpdir)
        os.environ["CLAWGUARD_MODE"] = "rbac"
        auth_gateway.ACCESS_CONTROL_MODE = "rbac"


# ============================================================
# 测试 10: 外部用户同步
# ============================================================

def test_sync_external_user():
    """测试从外部系统同步用户等级"""
    tmpdir, users_file, resources_file = _setup_test_env()

    store = RuleStore.__new__(RuleStore)
    store._lock = __import__('threading').RLock()
    store._backend = _TextBackend(users_file, resources_file)
    store.users = store._backend.load_users()
    store.resources = store._backend.load_resources()
    store.mac_labels = {}
    store.resource_labels = {}

    import auth_gateway
    old_store = auth_gateway._store
    auth_gateway._store = store

    try:
        # 同步外部用户
        sync_external_user("external_user_1", "secret")
        assert store.get_user_level("external_user_1") == 3

        # 再次同步（更新等级）
        sync_external_user("external_user_1", "top_secret")
        assert store.get_user_level("external_user_1") == 4

        # 检查权限
        assert check("external_user_1", "", "tool:execute_bash", "") == True

        print("✓ test_sync_external_user passed")
    finally:
        auth_gateway._store = old_store
        shutil.rmtree(tmpdir)


# ============================================================
# 运行所有测试
# ============================================================

def run_all_tests():
    """运行全部测试"""
    print("=" * 60)
    print("Clawguard v3 测试套件")
    print("=" * 60)
    print()

    tests = [
        test_normalize_level,
        test_match_pattern,
        test_check_special,
        test_check_rbac,
        test_tree_matching,
        test_specificity_tiebreak,
        test_win_linux_path_rules,
        test_mac_label,
        test_mac_check,
        test_mac_tree_consistency,
        test_rule_management,
        test_sqlite_backend,
        test_check_reason,
        test_sync_external_user,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"✗ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()

    print()
    print("=" * 60)
    print(f"测试结果: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
