"""
Argus 访问控制网关 (auth_gateway.py)
============================================================

核心：一个函数，输入 4 个字段，输出 allow / block。

    check(user_id, path, tool, database) -> bool
        True  = allow (放行)
        False = block (拦截)

权限规则与代码逻辑分离，写在两个简单文本文件里：
    rules/users.txt      用户规则：用户ID | 权限等级 | 特殊允许
    rules/resources.txt  资源规则：资源模式 | 所需等级

设计原则（对接需求方刘欣亚的明确要求）：
  1. 只关心输入输出，不关心底层实现，也不依赖前端多用户插件。
  2. 规则用最简单的文本文件，竖线 | 分割，一行一个用户/资源。
  3. 砍掉注入检测、Recuse、OPA 等周边功能，只保留"等级 + 特例"双机制。
"""

from __future__ import annotations

import os
import fnmatch
from pathlib import Path

# ============================================================
# 配置（可用环境变量覆盖；不写死在代码里）
# ============================================================

BASE_DIR = Path(__file__).parent
USERS_FILE = Path(os.getenv("ARGUS_USERS_FILE", BASE_DIR / "rules" / "users.txt"))
RESOURCES_FILE = Path(os.getenv("ARGUS_RESOURCES_FILE", BASE_DIR / "rules" / "resources.txt"))

# 未在 users.txt 中出现的用户：False=按默认等级放行，True=直接拦截
BLOCK_UNKNOWN_USERS = os.getenv("ARGUS_BLOCK_UNKNOWN_USERS", "false").lower() == "true"
# 未知用户的默认等级 / 未知资源的默认所需等级
DEFAULT_USER_LEVEL = 1
DEFAULT_RESOURCE_LEVEL = 99   # 未匹配的资源默认拦截（零信任）

# 等级别名 -> 数字 1..4
_LEVEL_ALIASES = {
    "1": 1, "2": 2, "3": 3, "4": 4,
    "a": 1, "b": 2, "c": 3, "d": 4,
    "public": 1, "internal": 2, "secret": 3, "top_secret": 4, "topsecret": 4,
}


def _normalize_level(raw: str) -> int:
    """把 '2' / 'B' / 'secret' 等统一成 1..4 的整数。无法识别返回 1。"""
    s = str(raw).strip().lower()
    return _LEVEL_ALIASES.get(s, 1)


# ============================================================
# 规则文件解析（极简：竖线 | 分割，# 注释，空行跳过）
# ============================================================

class RuleStore:
    """规则缓存。改动文件后调用 reload() 即可热更新，无需重启。"""

    def __init__(self, users_file: Path = USERS_FILE, resources_file: Path = RESOURCES_FILE):
        self.users_file = users_file
        self.resources_file = resources_file
        self.users: dict[str, dict] = {}        # user_id -> {level, specials}
        self.resources: list[tuple[str, int]] = []  # [(pattern, required_level), ...]
        self.reload()

    def reload(self) -> None:
        self.users = self._load_users(self.users_file)
        self.resources = self._load_resources(self.resources_file)

    @staticmethod
    def _split_line(line: str) -> list[str]:
        return [seg.strip() for seg in line.split("|")]

    def _load_users(self, path: Path) -> dict[str, dict]:
        users: dict[str, dict] = {}
        if not path.exists():
            return users
        for line in path.read_text(encoding="utf-8").splitlines():
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

    def _load_resources(self, path: Path) -> list[tuple[str, int]]:
        resources: list[tuple[str, int]] = []
        if not path.exists():
            return resources
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            segs = self._split_line(line)
            if len(segs) < 2:
                continue
            pattern, required = segs[0], _normalize_level(segs[1])
            if pattern:
                resources.append((pattern, required))
        return resources

    # ---- 查询 ----

    def get_user_level(self, user_id: str) -> int | None:
        u = self.users.get(user_id)
        return u["level"] if u else None

    def get_user_specials(self, user_id: str) -> list[str]:
        u = self.users.get(user_id)
        return u["specials"] if u else []

    def set_user_level(self, user_id: str, level: int) -> None:
        """从外部注入/更新用户等级（保留已有特例规则）。"""
        if user_id in self.users:
            self.users[user_id]["level"] = level
        else:
            self.users[user_id] = {"level": level, "specials": []}


# 全局单例（默认加载 rules/ 目录）
_store = RuleStore()


def reload_rules() -> None:
    """外部修改规则文件后调用，热更新。"""
    _store.reload()


def sync_external_user(user_id: str, security_level: str) -> None:
    """
    从外部认证系统（如 JWT / SQLite）同步用户等级到规则引擎。

    对接同学的多用户模块时调用：从 JWT 中解析出 user_id + security_level，
    注入到 RuleStore，这样 check() 就无需在 users.txt 中预先配置每个用户。

    如果 users.txt 中已有该用户的特例规则，则保留特例，仅更新等级；
    否则新建一条纯等级记录。
    """
    level = _normalize_level(security_level)
    _store.set_user_level(user_id, level)


# ============================================================
# 匹配逻辑
# ============================================================

def _match_pattern(pattern: str, value: str) -> bool:
    """
    判断 value 是否命中 pattern。
      - 含通配符 * ? 用 glob 匹配
      - 含 :  按 前缀/精确 匹配（如 tool:read_file / tool:*）
      - 其余按子串匹配（适配路径）
    """
    if not value:
        return False
    if "*" in pattern or "?" in pattern:
        return fnmatch.fnmatch(value, pattern)
    if ":" in pattern:
        # tool:read_file  精确 / 前缀
        if pattern.endswith(":*"):
            return value.startswith(pattern[:-2])
        return value == pattern or value.startswith(pattern + ":") or value.startswith(pattern)
    return pattern in value


def _resource_required_level(path: str, tool: str, database: str) -> int:
    """在 resources.txt 中查该资源所需等级；未命中返回默认等级。"""
    candidates = [p for p in (path, tool, database) if p]
    for pattern, required in _store.resources:
        for value in candidates:
            if _match_pattern(pattern, value):
                return required
    return DEFAULT_RESOURCE_LEVEL


def _check_special(specials: list[str], path: str, tool: str, database: str) -> str | None:
    """
    扫描用户的特例表。返回 'allow' / 'block' / None(无命中)。
    特例条目：! 前缀表示禁止，其余表示特别允许。
    """
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


# ============================================================
# 核心函数（唯一对外接口）
# ============================================================

def check(user_id: str, path: str = "", tool: str = "", database: str = "") -> bool:
    """
    访问控制网关核心函数。

    输入：
        user_id   - 用户 ID
        path      - 要访问的目录 / 文件
        tool      - 被调用工具的 ID / 名称
        database  - 要访问的数据库
        （后三个至少给一个，全空视为可疑请求，返回 block）

    输出：
        True  = allow 放行
        False = block 拦截
    """
    # 1. 请求必须有资源目标
    if not any([path, tool, database]):
        return False

    # 2. 解析用户等级
    level = _store.get_user_level(user_id)
    if level is None:
        if BLOCK_UNKNOWN_USERS:
            return False
        level = DEFAULT_USER_LEVEL

    # 3. 特例优先（特例可越级放行，也可显式拒绝）
    specials = _store.get_user_specials(user_id)
    special = _check_special(specials, path, tool, database)
    if special == "block":
        return False
    if special == "allow":
        return True

    # 4. 等级比对：user_level >= required_level 则放行
    required = _resource_required_level(path, tool, database)
    return level >= required


def check_reason(user_id: str, path: str = "", tool: str = "", database: str = "") -> tuple[bool, str]:
    """
    调试用：返回 (allow, 原因)。核心契约仍由 check() 的布尔值承担。
    """
    if not any([path, tool, database]):
        return False, "block: 请求缺少资源目标"

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

    required = _resource_required_level(path, tool, database)
    if level >= required:
        return True, f"allow: 用户等级 {level} ≥ 资源所需 {required}"
    return False, f"block: 用户等级 {level} < 资源所需 {required}"


# ============================================================
# CLI：便于演示与人工验证
# ============================================================

if __name__ == "__main__":
    import sys
    import io

    # Windows 控制台 GBK 编码无法输出中文/emoji，统一切到 UTF-8
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    def _usage():
        print("用法:")
        print("  python auth_gateway.py check <user_id> <path> <tool> <database>")
        print("  python auth_gateway.py demo")
        print("示例:")
        print("  python auth_gateway.py check user_01 /data/reports/q3.txt '' ''")
        print("  python auth_gateway.py check intern_01 '' tool:write_file ''")

    if len(sys.argv) < 2:
        _usage()
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "demo":
        from test_auth_gateway import run_demo
        run_demo()
    elif cmd == "check":
        if len(sys.argv) < 6:
            _usage()
            sys.exit(1)
        uid, p, t, d = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
        ok, reason = check_reason(uid, p, t, d)
        print(("ALLOW" if ok else "BLOCK"), "—", reason)
    elif cmd == "reload":
        reload_rules()
        print("规则已热更新")
    else:
        _usage()