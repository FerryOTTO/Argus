"""Clawguard — 访问控制网关模块"""

from __future__ import annotations

import os
import fnmatch
import re
import sqlite3
import threading
from pathlib import Path
from dataclasses import dataclass, field


# 配置

BASE_DIR = Path(__file__).parent
USERS_FILE = Path(os.getenv("CLAWGUARD_USERS_FILE", BASE_DIR / "rules" / "users.txt"))
RESOURCES_FILE = Path(os.getenv("CLAWGUARD_RESOURCES_FILE", BASE_DIR / "rules" / "resources.txt"))

ACCESS_CONTROL_MODE = os.getenv("CLAWGUARD_MODE", "rbac")  # rbac | mac | hybrid
BLOCK_UNKNOWN_USERS = os.getenv("CLAWGUARD_BLOCK_UNKNOWN_USERS", "false").lower() == "true"

DEFAULT_USER_LEVEL = 1
DEFAULT_RESOURCE_LEVEL = 99  # 零信任：未匹配资源默认拦截

_LEVEL_ALIASES = {
    "1": 1, "2": 2, "3": 3, "4": 4,
    "a": 1, "b": 2, "c": 3, "d": 4,
    "public": 1, "internal": 2, "secret": 3, "top_secret": 4, "topsecret": 4,
}


def _normalize_level(raw: str) -> int:
    """把 '2' / 'B' / 'secret' 等统一成 1..4 的整数。"""
    s = str(raw).strip().lower()
    return _LEVEL_ALIASES.get(s, 1)


# MAC 安全标签

@dataclass(frozen=True)
class SecurityLabel:
    level: int = 1
    categories: frozenset = field(default_factory=frozenset)

    def dominates(self, other: "SecurityLabel") -> bool:
        return self.level >= other.level and self.categories >= other.categories

    def __str__(self) -> str:
        cats = ",".join(sorted(self.categories)) if self.categories else ""
        level_name = {1: "public", 2: "internal", 3: "secret", 4: "top_secret"}.get(self.level, "public")
        return f"{level_name}:{cats}" if cats else level_name


# 后端接口抽象

class _RuleBackend:
    def load_users(self) -> dict[str, dict]: raise NotImplementedError
    def save_users(self, users: dict[str, dict]) -> None: raise NotImplementedError
    def load_resources(self) -> list[tuple]: raise NotImplementedError
    def save_resources(self, resources: list[tuple]) -> None: raise NotImplementedError


class _TextBackend(_RuleBackend):
    """文本文件后端"""

    def __init__(self, users_file: Path, resources_file: Path):
        self.users_file = users_file
        self.resources_file = resources_file

    @staticmethod
    def _split_line(line: str) -> list[str]:
        return [re.sub(r"\s+#.*$", "", seg).strip() for seg in line.split("|")]

    def load_users(self) -> dict[str, dict]:
        users: dict[str, dict] = {}
        if not self.users_file.exists():
            return users
        for line in self.users_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            segs = self._split_line(line)
            if len(segs) < 2:
                continue
            uid = segs[0]
            if not uid:
                continue
            level = _normalize_level(segs[1])
            specials = [s.strip() for s in segs[2].split(",")] if len(segs) >= 3 and segs[2] else []
            specials = [s for s in specials if s]
            users[uid] = {"level": level, "specials": specials}
        return users

    def save_users(self, users: dict[str, dict]) -> None:
        lines = ["# Clawguard 用户规则", "# 格式: 用户名或ID | 默认等级 | 特例(逗号分隔,可选)", ""]
        for uid, data in users.items():
            level_name = {1: "public", 2: "internal", 3: "secret", 4: "top_secret"}.get(data["level"], "internal")
            specials = ",".join(data["specials"]) if data.get("specials") else ""
            lines.append(f"{uid} | {level_name} | {specials}")
        self.users_file.write_text("\n".join(lines), encoding="utf-8")

    def load_resources(self) -> list[tuple]:
        resources: list[tuple] = []
        if not self.resources_file.exists():
            return resources
        for line in self.resources_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            segs = self._split_line(line)
            if len(segs) < 2:
                continue
            pattern, required = segs[0], _normalize_level(segs[1])
            inherit_mode = segs[2].strip() if len(segs) >= 3 else "flat"
            if pattern:
                resources.append((pattern, required, inherit_mode))
        return resources

    def save_resources(self, resources: list[tuple]) -> None:
        lines = ["# Clawguard 资源规则", "# 格式: 路径模式 | 所需等级 | 继承模式(flat/inherit/override)", ""]
        for pattern, required, inherit_mode in resources:
            level_name = {1: "public", 2: "internal", 3: "secret", 4: "top_secret"}.get(required, "internal")
            lines.append(f"{pattern} | {level_name} | {inherit_mode}")
        self.resources_file.write_text("\n".join(lines), encoding="utf-8")


class _SQLiteBackend(_RuleBackend):
    """SQLite 后端"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, level INTEGER NOT NULL, specials TEXT DEFAULT '')")
        cursor.execute("CREATE TABLE IF NOT EXISTS resources (pattern TEXT PRIMARY KEY, required_level INTEGER NOT NULL, inherit_mode TEXT DEFAULT 'flat')")
        conn.commit()
        conn.close()

    def load_users(self) -> dict[str, dict]:
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, level, specials FROM users")
        users = {}
        for row in cursor.fetchall():
            uid, level, specials = row
            users[uid] = {"level": level, "specials": [s.strip() for s in specials.split(",")] if specials else []}
        conn.close()
        return users

    def save_users(self, users: dict[str, dict]) -> None:
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users")
        for uid, data in users.items():
            specials = ",".join(data["specials"]) if data.get("specials") else ""
            cursor.execute("INSERT INTO users (user_id, level, specials) VALUES (?, ?, ?)", (uid, data["level"], specials))
        conn.commit()
        conn.close()

    def load_resources(self) -> list[tuple]:
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT pattern, required_level, inherit_mode FROM resources")
        resources = cursor.fetchall()
        conn.close()
        return resources

    def save_resources(self, resources: list[tuple]) -> None:
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM resources")
        for pattern, required, inherit_mode in resources:
            cursor.execute("INSERT INTO resources (pattern, required_level, inherit_mode) VALUES (?, ?, ?)", (pattern, required, inherit_mode))
        conn.commit()
        conn.close()


# 规则存储

class RuleStore:
    def __init__(self, backend_type: str = "auto"):
        self._lock = threading.RLock()

        if backend_type == "auto":
            sqlite_path = BASE_DIR / "rules.db"
            backend_type = "sqlite" if sqlite_path.exists() else "text"

        if backend_type == "sqlite":
            self._backend = _SQLiteBackend(BASE_DIR / "rules.db")
        else:
            self._backend = _TextBackend(USERS_FILE, RESOURCES_FILE)

        self.users: dict[str, dict] = {}
        self.resources: list[tuple] = []
        self.mac_labels: dict[str, SecurityLabel] = {}
        self.resource_labels: dict[str, SecurityLabel] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            self.users = self._backend.load_users()
            self.resources = self._backend.load_resources()

    def get_user_level(self, user_id: str) -> int | None:
        with self._lock:
            u = self.users.get(user_id)
            return u["level"] if u else None

    def get_user_specials(self, user_id: str) -> list[str]:
        with self._lock:
            u = self.users.get(user_id)
            return u["specials"] if u else []

    def set_user_level(self, user_id: str, level: int) -> None:
        with self._lock:
            if user_id in self.users:
                self.users[user_id]["level"] = level
            else:
                self.users[user_id] = {"level": level, "specials": []}
            self._backend.save_users(self.users)

    def add_user_rule(self, user_id: str, level: str, specials: list[str] = None) -> dict:
        with self._lock:
            self.users[user_id] = {"level": _normalize_level(level), "specials": [s.strip() for s in (specials or []) if s.strip()]}
            self._backend.save_users(self.users)
        return {"success": True, "message": f"用户 {user_id} 规则已更新", "user": self.users[user_id]}

    def remove_user_rule(self, user_id: str) -> dict:
        with self._lock:
            if user_id not in self.users:
                return {"success": False, "message": f"用户 {user_id} 不存在"}
            del self.users[user_id]
            self._backend.save_users(self.users)
        return {"success": True, "message": f"用户 {user_id} 规则已删除"}

    def list_user_rules(self, level: str = None, has_specials: bool = None) -> list[dict]:
        with self._lock:
            result = []
            for uid, data in self.users.items():
                if level is not None and data["level"] != _normalize_level(level):
                    continue
                if has_specials is not None and bool(data["specials"]) != has_specials:
                    continue
                result.append({"user_id": uid, **data})
            return result

    def add_resource_rule(self, pattern: str, required_level: str, inherit_mode: str = "flat") -> dict:
        with self._lock:
            self.resources = [(p, r, i) for p, r, i in self.resources if p != pattern]
            self.resources.append((pattern, _normalize_level(required_level), inherit_mode))
            self._backend.save_resources(self.resources)
        return {"success": True, "message": f"资源规则 {pattern} 已添加"}

    def remove_resource_rule(self, pattern: str) -> dict:
        with self._lock:
            self.resources = [(p, r, i) for p, r, i in self.resources if p != pattern]
            self._backend.save_resources(self.resources)
        return {"success": True, "message": f"资源规则 {pattern} 已删除"}

    def list_resource_rules(self, min_level: int = None, max_level: int = None) -> list[dict]:
        with self._lock:
            result = []
            for pattern, required, inherit_mode in self.resources:
                if min_level is not None and required < min_level:
                    continue
                if max_level is not None and required > max_level:
                    continue
                result.append({"pattern": pattern, "required_level": required, "inherit_mode": inherit_mode})
            return result

    def set_mac_label(self, user_id: str, level: int, categories: set[str] = None) -> None:
        with self._lock:
            self.mac_labels[user_id] = SecurityLabel(level, frozenset(categories or set()))

    def get_mac_label(self, user_id: str) -> SecurityLabel | None:
        with self._lock:
            return self.mac_labels.get(user_id)

    def set_resource_mac_label(self, pattern: str, level: int, categories: set[str] = None) -> None:
        with self._lock:
            self.resource_labels[pattern] = SecurityLabel(level, frozenset(categories or set()))

    def get_resource_mac_label(self, pattern: str) -> SecurityLabel | None:
        with self._lock:
            return self.resource_labels.get(pattern)


_store = RuleStore()


def reload_rules() -> None:
    _store.reload()


def sync_external_user(user_id: str, security_level: str) -> None:
    level = _normalize_level(security_level)
    _store.set_user_level(user_id, level)


# 匹配逻辑

def _is_namespace_pattern(pattern: str) -> bool:
    if ":" not in pattern:
        return False
    if len(pattern) >= 2 and pattern[1] == ":" and pattern[0].isalpha():
        return False
    return True


def _match_pattern(pattern: str, value: str) -> bool:
    if not value or not pattern:
        return False
    if "*" in pattern or "?" in pattern:
        return fnmatch.fnmatch(value, pattern)
    if _is_namespace_pattern(pattern):
        if pattern.endswith(":*"):
            return value.startswith(pattern[:-2])
        return value == pattern or value.startswith(pattern + ":") or value.startswith(pattern)
    if "\\" in pattern or "/" in pattern:
        return value == pattern or value.startswith(pattern + "\\") or value.startswith(pattern + "/")
    return pattern in value


def _pattern_specificity(pattern: str) -> tuple:
    wildcards = pattern.count("*") + pattern.count("?")
    return (-wildcards, len(pattern))


def _resource_required_level_tree(path: str = "", tool: str = "", database: str = "") -> int:
    candidates = [p for p in (path, tool, database) if p]
    if not candidates:
        return DEFAULT_RESOURCE_LEVEL

    req_levels = [_resource_match_tree(p)[1] for p in candidates]
    return max(req_levels) if req_levels else DEFAULT_RESOURCE_LEVEL


def _resource_match_tree(value: str) -> tuple[str, int]:
    best_pattern, best_level = "", DEFAULT_RESOURCE_LEVEL
    best_depth, best_is_override, best_spec = -1, False, _pattern_specificity("")

    for pattern, level, inherit_mode in _store.resources:
        if not _match_pattern(pattern, value):
            continue

        if _is_namespace_pattern(pattern):
            current_depth = 100 + pattern.count(":")
        else:
            current_depth = pattern.count("\\") + pattern.count("/")

        is_override = inherit_mode == "override"
        spec = _pattern_specificity(pattern)

        better = False
        if current_depth > best_depth:
            better = True
        elif current_depth == best_depth:
            if is_override != best_is_override:
                better = is_override
            else:
                better = spec > best_spec

        if not better:
            continue
        best_pattern, best_level = pattern, level
        best_depth, best_is_override, best_spec = current_depth, is_override, spec

    return best_pattern, best_level


def _check_special(specials: list[str], path: str, tool: str, database: str) -> str | None:
    candidates = [p for p in (path, tool, database) if p]
    for spec in specials:
        spec = spec.strip()
        if not spec:
            continue
        deny = spec.startswith("!")
        pat = spec[1:].strip() if deny else spec
        if pat == "*":
            return "block" if deny else "allow"
        for value in candidates:
            if _match_pattern(pat, value):
                return "block" if deny else "allow"
    return None


# MAC 访问控制

def _check_mac(user_id: str, path: str = "", tool: str = "", database: str = "") -> bool:
    user_label = _store.get_mac_label(user_id)
    if user_label is None:
        level = _store.get_user_level(user_id)
        if level is None:
            level = DEFAULT_USER_LEVEL if not BLOCK_UNKNOWN_USERS else 1
        user_label = SecurityLabel(level)

    candidates = [p for p in (path, tool, database) if p]
    if not candidates:
        return False

    for value in candidates:
        pattern, req_level = _resource_match_tree(value)
        explicit = _store.get_resource_mac_label(pattern) if pattern else None
        resource_label = explicit if explicit is not None else SecurityLabel(req_level)
        if not user_label.dominates(resource_label):
            return False

    return True


# RBAC 访问控制

def _check_rbac(user_id: str, path: str = "", tool: str = "", database: str = "",
                penalty: int = 0) -> bool:
    if not any([path, tool, database]):
        return False

    level = _store.get_user_level(user_id)
    if level is None:
        if BLOCK_UNKNOWN_USERS:
            return False
        level = DEFAULT_USER_LEVEL

    specials = _store.get_user_specials(user_id)
    special = _check_special(specials, path, tool, database)
    if special == "block":
        return False
    if special == "allow":
        return True

    required = _resource_required_level_tree(path, tool, database) + penalty
    return level >= required


# 核心函数

def check(user_id: str, path: str = "", tool: str = "", database: str = "") -> bool:
    if ACCESS_CONTROL_MODE == "rbac":
        return _check_rbac(user_id, path, tool, database)
    elif ACCESS_CONTROL_MODE == "mac":
        return _check_mac(user_id, path, tool, database)
    elif ACCESS_CONTROL_MODE == "hybrid":
        return _check_rbac(user_id, path, tool, database) and _check_mac(user_id, path, tool, database)
    else:
        return _check_rbac(user_id, path, tool, database)


def check_reason(user_id: str, path: str = "", tool: str = "", database: str = "",
                 penalty: int = 0) -> tuple[bool, str]:
    if not any([path, tool, database]):
        return False, "block: 请求缺少资源目标"

    if ACCESS_CONTROL_MODE == "mac":
        ok = _check_mac(user_id, path, tool, database)
        if not ok:
            return False, "block: MAC 安全标签校验失败"
        return True, "allow: MAC 安全标签校验通过"
    elif ACCESS_CONTROL_MODE == "hybrid":
        rbac_ok = _check_rbac(user_id, path, tool, database, penalty=penalty)
        mac_ok = _check_mac(user_id, path, tool, database)
        if not rbac_ok:
            return False, "block: RBAC 校验失败"
        if not mac_ok:
            return False, "block: MAC 校验失败"
        return True, "allow: RBAC + MAC 双重校验通过"
    else:
        level = _store.get_user_level(user_id)
        if level is None:
            if BLOCK_UNKNOWN_USERS:
                return False, f"block: 未知用户 {user_id}（已被策略拦截）"
            level = DEFAULT_USER_LEVEL

        specials = _store.get_user_specials(user_id)
        special = _check_special(specials, path, tool, database)
        if special == "block":
            return False, f"block: 用户 {user_id} 的特例规则显式拒绝该资源"
        if special == "allow":
            return True, f"allow: 用户 {user_id} 的特例规则放行该资源"

        required = _resource_required_level_tree(path, tool, database) + penalty
        if level >= required:
            return True, f"allow: 用户等级 {level} ≥ 资源所需 {required}"
        return False, f"block: 用户等级 {level} < 资源所需 {required}"


# 统一接口适配入口

def check_v4(user_id: str, path: str = "", tool: str = "", database: str = "",
             penalty: int = 0) -> dict:
    """统一接口入口，调用 check_reason() 返回字典格式判定结果。

    penalty: 防线升级参数（≥0），把资源所需等级临时提高 penalty 级，
             供审计联动模块在检测到频发试探时动态收紧防线。
    """
    allowed, reason = check_reason(user_id, path, tool, database, penalty=penalty)
    return {
        "allowed": allowed,
        "reason": reason,
        "user_id": user_id,
        "path": path,
        "tool": tool,
        "database": database,
        "penalty": penalty,
    }


# 规则管理接口

def add_user_rule(user_id: str, level: str, specials: list[str] = None) -> dict:
    return _store.add_user_rule(user_id, level, specials)


def remove_user_rule(user_id: str) -> dict:
    return _store.remove_user_rule(user_id)


def get_user_rule(user_id: str) -> dict | None:
    level = _store.get_user_level(user_id)
    if level is None:
        return None
    return {"user_id": user_id, "level": level, "specials": _store.get_user_specials(user_id)}


def list_user_rules(level: str = None, has_specials: bool = None) -> list[dict]:
    return _store.list_user_rules(level, has_specials)


def add_resource_rule(pattern: str, required_level: str, inherit_mode: str = "flat") -> dict:
    return _store.add_resource_rule(pattern, required_level, inherit_mode)


def remove_resource_rule(pattern: str) -> dict:
    return _store.remove_resource_rule(pattern)


def list_resource_rules(min_level: int = None, max_level: int = None) -> list[dict]:
    return _store.list_resource_rules(min_level, max_level)


# MAC 标签管理

def set_mac_label(user_id: str, level: int, categories: set[str] = None) -> None:
    _store.set_mac_label(user_id, level, categories)


def get_mac_label(user_id: str) -> SecurityLabel | None:
    return _store.get_mac_label(user_id)


# CLI

if __name__ == "__main__":
    import sys
    import io

    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    def _usage():
        print("用法:")
        print("  python auth_gateway.py check <user_id> <path> <tool> <database>")
        print("  python auth_gateway.py demo")
        print("  python auth_gateway.py mode <rbac|mac|hybrid>")
        print("  python auth_gateway.py add-user <user_id> <level> [specials...]")
        print("  python auth_gateway.py remove-user <user_id>")
        print("  python auth_gateway.py add-resource <pattern> <level> [inherit_mode]")
        print("  python auth_gateway.py remove-resource <pattern>")
        print("示例:")
        print("  python auth_gateway.py check user_01 /data/reports/q3.txt '' ''")
        print("  python auth_gateway.py check intern_01 '' tool:write_file ''")
        print("  python auth_gateway.py mode hybrid")

    if len(sys.argv) < 2:
        _usage()
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "demo":
        print("Clawguard 演示")
        print(f"当前模式: {ACCESS_CONTROL_MODE}")
        print("\n用户规则:")
        for u in list_user_rules():
            print(f"  {u['user_id']}: level={u['level']}, specials={u['specials']}")
        print("\n资源规则:")
        for r in list_resource_rules():
            print(f"  {r['pattern']}: required={r['required_level']}, mode={r['inherit_mode']}")
    elif cmd == "check":
        if len(sys.argv) < 6:
            _usage()
            sys.exit(1)
        uid, p, t, d = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
        ok, reason = check_reason(uid, p, t, d)
        print(("ALLOW" if ok else "BLOCK"), "—", reason)
    elif cmd == "mode":
        if len(sys.argv) < 3:
            _usage()
            sys.exit(1)
        new_mode = sys.argv[2]
        if new_mode not in ("rbac", "mac", "hybrid"):
            print(f"错误: 未知模式 {new_mode}")
            sys.exit(1)
        os.environ["CLAWGUARD_MODE"] = new_mode
        print(f"模式已切换为: {new_mode}")
    elif cmd == "add-user":
        if len(sys.argv) < 4:
            _usage()
            sys.exit(1)
        uid, level = sys.argv[2], sys.argv[3]
        specials = sys.argv[4].split(",") if len(sys.argv) > 4 else []
        result = add_user_rule(uid, level, specials)
        print(result["message"])
    elif cmd == "remove-user":
        if len(sys.argv) < 3:
            _usage()
            sys.exit(1)
        result = remove_user_rule(sys.argv[2])
        print(result["message"])
    elif cmd == "add-resource":
        if len(sys.argv) < 4:
            _usage()
            sys.exit(1)
        pattern, level = sys.argv[2], sys.argv[3]
        inherit_mode = sys.argv[4] if len(sys.argv) > 4 else "flat"
        result = add_resource_rule(pattern, level, inherit_mode)
        print(result["message"])
    elif cmd == "remove-resource":
        if len(sys.argv) < 3:
            _usage()
            sys.exit(1)
        result = remove_resource_rule(sys.argv[2])
        print(result["message"])
    elif cmd == "reload":
        reload_rules()
        print("规则已热更新")
    else:
        _usage()
