# database.py — SQLite 数据库操作（简化版：仅保留 agent_skills 存储记录）
import aiosqlite
from config import config

_db: aiosqlite.Connection | None = None


async def init_db() -> aiosqlite.Connection:
    global _db
    config.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(str(config.sqlite_path), timeout=30.0)
    _db.row_factory = aiosqlite.Row
    await _db.executescript("""
        PRAGMA journal_mode = WAL;
        PRAGMA busy_timeout = 30000;
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS users (
            id             TEXT PRIMARY KEY,
            username       TEXT UNIQUE NOT NULL,
            password_hash  TEXT NOT NULL,
            role           TEXT NOT NULL DEFAULT 'user',
            security_level TEXT NOT NULL DEFAULT 'internal',
            status         TEXT NOT NULL DEFAULT 'active',
            created_at     INTEGER NOT NULL,
            last_login_at  INTEGER,
            quota_tier     TEXT DEFAULT 'free',
            daily_token_quota INTEGER
        );

        CREATE TABLE IF NOT EXISTS refresh_tokens (
            jti         TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_id  TEXT NOT NULL,
            token_hash  TEXT NOT NULL,
            expires_at  INTEGER NOT NULL,
            revoked_at  INTEGER,
            created_at  INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rt_user ON refresh_tokens(user_id);
        CREATE INDEX IF NOT EXISTS idx_rt_session ON refresh_tokens(session_id);

        CREATE TABLE IF NOT EXISTS user_agents (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            agent_id    TEXT UNIQUE NOT NULL,
            name        TEXT NOT NULL,
            is_default  INTEGER DEFAULT 1,
            status      TEXT DEFAULT 'active',
            created_at  INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ua_user ON user_agents(user_id);
        CREATE INDEX IF NOT EXISTS idx_ua_agent ON user_agents(agent_id);

        CREATE TABLE IF NOT EXISTS usage_records (
            id                TEXT PRIMARY KEY,
            user_id           TEXT,
            agent_id          TEXT,
            model             TEXT NOT NULL,
            prompt_tokens     INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens      INTEGER DEFAULT 0,
            created_at        INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_records(user_id);
        CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_records(created_at);

        CREATE TABLE IF NOT EXISTS sso_links (
            provider    TEXT NOT NULL,
            subject     TEXT NOT NULL,
            user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at  INTEGER NOT NULL,
            PRIMARY KEY (provider, subject)
        );
        CREATE INDEX IF NOT EXISTS idx_sso_user ON sso_links(user_id);

        -- ===== 用户技能存储记录（唯一保留的技能表） =====
        CREATE TABLE IF NOT EXISTS agent_skills (
            id                TEXT PRIMARY KEY,
            user_id           TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            agent_id          TEXT NOT NULL,
            skill_name        TEXT NOT NULL,
            skill_source      TEXT DEFAULT 'custom',
            installed_version TEXT,
            content_hash      TEXT,
            status            TEXT DEFAULT 'active',
            installed_at      INTEGER NOT NULL,
            updated_at        INTEGER NOT NULL,
            UNIQUE(agent_id, skill_name)
        );
        CREATE INDEX IF NOT EXISTS idx_as_user ON agent_skills(user_id);
        CREATE INDEX IF NOT EXISTS idx_as_agent ON agent_skills(agent_id);

        -- 技能定义目录：内容只存一次，公有/私有仅一个字段区分
        CREATE TABLE IF NOT EXISTS skills (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            description   TEXT,
            version       TEXT,
            content       TEXT,
            content_hash  TEXT NOT NULL,
            visibility    TEXT NOT NULL DEFAULT 'private',  -- 'public' | 'private'
            owner_user_id TEXT,                              -- 私有必填；公有 NULL
            created_at    INTEGER NOT NULL,
            updated_at    INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_skills_owner ON skills(owner_user_id);
        CREATE INDEX IF NOT EXISTS idx_skills_visibility ON skills(visibility);
        CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);

    """)
    try:
        await _db.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
    except Exception:
        pass
    try:
        await _db.execute("ALTER TABLE users ADD COLUMN quota_tier TEXT DEFAULT 'free'")
    except Exception:
        pass
    try:
        await _db.execute("ALTER TABLE users ADD COLUMN daily_token_quota INTEGER")
    except Exception:
        pass
    # 用户默认模型偏好（/api/me/model 持久化用）
    try:
        await _db.execute("ALTER TABLE user_agents ADD COLUMN model TEXT")
    except Exception:
        pass
    try:
        await _db.execute("ALTER TABLE user_agents ADD COLUMN updated_at INTEGER")
    except Exception:
        pass
    # 安装关系指向定义目录（skills.id）
    try:
        await _db.execute("ALTER TABLE agent_skills ADD COLUMN skill_id TEXT")
    except Exception:
        pass
    # LLM 计量：提供商 + 成本
    try:
        await _db.execute("ALTER TABLE usage_records ADD COLUMN provider TEXT")
    except Exception:
        pass
    try:
        await _db.execute("ALTER TABLE usage_records ADD COLUMN cost REAL")
    except Exception:
        pass
    await _db.commit()
    print(f"[DB] SQLite initialized at {config.sqlite_path}")
    return _db


def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("DB not initialized. Call init_db() first.")
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None
        print("[DB] SQLite closed")


# ====== users 表操作 ======

async def insert_user(user: dict) -> None:
    await get_db().execute(
        "INSERT INTO users (id, username, password_hash, role, security_level, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [user["id"], user["username"], user["password_hash"],
         user.get("role", "user"), user.get("security_level", "internal"),
         user.get("status", "active"), user["created_at"]]
    )
    await get_db().commit()


async def find_user_by_username(username: str) -> dict | None:
    cursor = await get_db().execute("SELECT * FROM users WHERE username = ?", [username])
    row = await cursor.fetchone()
    return dict(row) if row else None


async def find_user_by_id(user_id: str) -> dict | None:
    cursor = await get_db().execute("SELECT * FROM users WHERE id = ?", [user_id])
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_user_last_login(user_id: str, timestamp: int) -> None:
    await get_db().execute("UPDATE users SET last_login_at = ? WHERE id = ?", [timestamp, user_id])
    await get_db().commit()


async def list_users() -> list[dict]:
    cursor = await get_db().execute(
        "SELECT id, username, role, security_level, status, quota_tier, daily_token_quota, created_at, last_login_at "
        "FROM users ORDER BY created_at ASC"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def count_users() -> int:
    cursor = await get_db().execute("SELECT COUNT(*) as cnt FROM users")
    row = await cursor.fetchone()
    return row["cnt"] if row else 0


async def update_user_role(user_id: str, role: str) -> bool:
    cursor = await get_db().execute(
        "UPDATE users SET role = ? WHERE id = ?", [role, user_id]
    )
    await get_db().commit()
    return cursor.rowcount > 0


async def update_user_status(user_id: str, status: str) -> bool:
    cursor = await get_db().execute(
        "UPDATE users SET status = ? WHERE id = ?", [status, user_id]
    )
    await get_db().commit()
    return cursor.rowcount > 0


async def update_user_security_level(user_id: str, security_level: str) -> bool:
    cursor = await get_db().execute(
        "UPDATE users SET security_level = ? WHERE id = ?", [security_level, user_id]
    )
    await get_db().commit()
    return cursor.rowcount > 0


async def update_user_quota(user_id: str, quota_tier: str, daily_token_quota: int | None) -> bool:
    cursor = await get_db().execute(
        "UPDATE users SET quota_tier = ?, daily_token_quota = ? WHERE id = ?",
        [quota_tier, daily_token_quota, user_id]
    )
    await get_db().commit()
    return cursor.rowcount > 0


async def sum_user_tokens_since(user_id: str, since_ms: int) -> int:
    cursor = await get_db().execute(
        "SELECT COALESCE(SUM(total_tokens), 0) AS total FROM usage_records "
        "WHERE user_id = ? AND created_at >= ?",
        [user_id, since_ms]
    )
    row = await cursor.fetchone()
    return int(row["total"]) if row else 0


async def sum_user_cost_since(user_id: str, since_ms: int) -> float:
    """某用户某段时间的累计成本（元）。"""
    cursor = await get_db().execute(
        "SELECT COALESCE(SUM(cost), 0) AS total FROM usage_records "
        "WHERE user_id = ? AND created_at >= ?",
        [user_id, since_ms]
    )
    row = await cursor.fetchone()
    return float(row["total"]) if row else 0.0


async def delete_user_by_id(user_id: str) -> bool:
    cursor = await get_db().execute("DELETE FROM users WHERE id = ?", [user_id])
    await get_db().commit()
    return cursor.rowcount > 0


# ====== refresh_tokens 表操作 ======

async def insert_refresh_token(record: dict) -> None:
    await get_db().execute(
        "INSERT INTO refresh_tokens (jti, user_id, session_id, token_hash, expires_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [record["jti"], record["user_id"], record["session_id"],
         record["token_hash"], record["expires_at"], record["created_at"]]
    )
    await get_db().commit()


async def find_refresh_token(jti: str) -> dict | None:
    cursor = await get_db().execute("SELECT * FROM refresh_tokens WHERE jti = ?", [jti])
    row = await cursor.fetchone()
    return dict(row) if row else None


async def revoke_refresh_token(jti: str, revoked_at: int) -> None:
    await get_db().execute("UPDATE refresh_tokens SET revoked_at = ? WHERE jti = ?", [revoked_at, jti])
    await get_db().commit()


async def revoke_all_user_refresh_tokens(user_id: str, revoked_at: int) -> None:
    await get_db().execute(
        "UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        [revoked_at, user_id]
    )
    await get_db().commit()


# ====== user_agents 表操作 ======

async def insert_agent(agent: dict) -> None:
    await get_db().execute(
        "INSERT INTO user_agents (id, user_id, agent_id, name, is_default, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [agent["id"], agent["user_id"], agent["agent_id"], agent["name"],
         agent.get("is_default", 1), agent.get("status", "active"), agent["created_at"]]
    )
    await get_db().commit()


async def find_agent_by_user(user_id: str) -> dict | None:
    cursor = await get_db().execute(
        "SELECT * FROM user_agents WHERE user_id = ? AND is_default = 1 AND status = 'active'",
        [user_id]
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def list_user_agents(user_id: str) -> list[dict]:
    cursor = await get_db().execute(
        "SELECT id, agent_id, name, is_default, status, created_at "
        "FROM user_agents WHERE user_id = ? ORDER BY created_at ASC",
        [user_id]
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def find_user_by_agent_id(agent_id: str) -> dict | None:
    cursor = await get_db().execute(
        "SELECT u.* FROM users u JOIN user_agents ua ON ua.user_id = u.id "
        "WHERE ua.agent_id = ? AND ua.status = 'active'",
        [agent_id]
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


# ====== usage_records 操作 ======

async def insert_usage_record(record: dict) -> None:
    await get_db().execute(
        "INSERT INTO usage_records (id, user_id, agent_id, model, provider, prompt_tokens, completion_tokens, total_tokens, cost, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [record["id"], record["user_id"], record.get("agent_id"), record["model"],
         record.get("provider"), record.get("prompt_tokens", 0),
         record.get("completion_tokens", 0), record.get("total_tokens", 0),
         record.get("cost", 0.0), record["created_at"]]
    )
    await get_db().commit()


async def list_usage_records(limit: int = 200) -> list[dict]:
    cursor = await get_db().execute(
        "SELECT * FROM usage_records ORDER BY created_at DESC LIMIT ?", [limit])
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ====== 周度配额辅助函数 ======

def get_week_start_ms() -> int:
    """计算本周一零点（UTC）的毫秒时间戳。"""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    days_since_monday = now.weekday()
    monday = now - timedelta(days=days_since_monday)
    monday_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(monday_start.timestamp() * 1000)


def get_next_week_start_ms() -> int:
    """计算下周一零点（UTC）的毫秒时间戳。"""
    return get_week_start_ms() + 7 * 24 * 3600 * 1000


# ======================================================================
# ===== agent_skills：用户技能存储记录 CRUD（唯一保留的技能表）====
# ======================================================================
import uuid as _uuid
import time as _time
import hashlib as _hashlib
_now_ms = lambda: int(_time.time() * 1000)
_uid = lambda: _uuid.uuid4().hex[:20]
_skill_hash = lambda content: _hashlib.sha256((content or "").encode("utf-8")).hexdigest()


async def upsert_agent_skill(user_id: str, agent_id: str, skill_name: str,
        source: str = "custom", version: str = None, content_hash: str = None,
        skill_id: str = None):
    """写入/更新一条技能存储记录；UNIQUE 保证同一 agent 同名 skill 只存一条。
    skill_id 指向 skills 目录定义（安装关系为指针，不复制内容）。"""
    db = get_db(); now = _now_ms()
    cur = await db.execute(
        "SELECT id FROM agent_skills WHERE agent_id = ? AND skill_name = ?", [agent_id, skill_name])
    r = await cur.fetchone()
    if r:
        await db.execute(
            "UPDATE agent_skills SET skill_source=?, installed_version=?, content_hash=?, skill_id=?, status='active', updated_at=? "
            "WHERE id = ?", [source, version, content_hash, skill_id, now, r["id"]])
    else:
        await db.execute(
            "INSERT INTO agent_skills (id,user_id,agent_id,skill_name,skill_source,installed_version,content_hash,skill_id,status,installed_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,'active',?,?)",
            [_uid(), user_id, agent_id, skill_name, source, version, content_hash, skill_id, now, now])
    await db.commit()


async def list_user_skills(user_id: str) -> list[dict]:
    """列出某用户所有 agent 的技能存储记录。"""
    cur = await get_db().execute(
        "SELECT as_.*, ua.name AS agent_name FROM agent_skills as_ "
        "JOIN user_agents ua ON ua.agent_id = as_.agent_id "
        "WHERE as_.user_id = ? AND as_.status='active' ORDER BY as_.installed_at DESC",
        [user_id])
    return [dict(r) for r in await cur.fetchall()]


async def list_all_skills(limit: int = 500) -> list[dict]:
    """管理员：列出所有用户的技能存储记录。"""
    cur = await get_db().execute(
        "SELECT as_.*, u.username, ua.name AS agent_name FROM agent_skills as_ "
        "JOIN users u ON u.id = as_.user_id "
        "JOIN user_agents ua ON ua.agent_id = as_.agent_id "
        "WHERE as_.status='active' ORDER BY as_.installed_at DESC LIMIT ?", [limit])
    return [dict(r) for r in await cur.fetchall()]


async def find_agent_skill(agent_id: str, skill_name: str) -> dict | None:
    cur = await get_db().execute(
        "SELECT * FROM agent_skills WHERE agent_id = ? AND skill_name = ?", [agent_id, skill_name])
    r = await cur.fetchone()
    return dict(r) if r else None


async def remove_agent_skill(agent_id: str, skill_name: str) -> bool:
    cur = await get_db().execute(
        "DELETE FROM agent_skills WHERE agent_id = ? AND skill_name = ?", [agent_id, skill_name])
    await get_db().commit()
    return cur.rowcount > 0


async def delete_skill_by_id(skill_id: str) -> bool:
    """管理员：按 ID 删除技能记录。"""
    cur = await get_db().execute("DELETE FROM agent_skills WHERE id = ?", [skill_id])
    await get_db().commit()
    return cur.rowcount > 0


async def verify_agent_owned_by_user(agent_id: str, user_id: str) -> bool:
    """隔离校验：确保操作该 agent 的一定是它归属的 user。"""
    cur = await get_db().execute(
        "SELECT 1 FROM user_agents WHERE agent_id = ? AND user_id = ? AND status='active'",
        [agent_id, user_id])
    return bool(await cur.fetchone())


async def count_skills_by_user(user_id: str) -> int:
    cur = await get_db().execute(
        "SELECT COUNT(*) AS cnt FROM agent_skills WHERE user_id = ? AND status='active'", [user_id])
    r = await cur.fetchone()
    return r["cnt"] if r else 0


# ======================================================================
# ===== skills：技能定义目录（公有/私有，内容只存一次） =====
# ======================================================================

async def create_skill_definition(defn: dict) -> str:
    """写入技能定义，返回 skill id。去重与权限由调用方负责。"""
    await get_db().execute(
        "INSERT INTO skills (id, name, description, version, content, content_hash, visibility, owner_user_id, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [defn["id"], defn["name"], defn.get("description"), defn.get("version"),
         defn.get("content"), defn["content_hash"], defn.get("visibility", "private"),
         defn.get("owner_user_id"), defn["created_at"], defn["updated_at"]]
    )
    await get_db().commit()
    return defn["id"]


async def find_skill_by_id(skill_id: str) -> dict | None:
    cur = await get_db().execute("SELECT * FROM skills WHERE id = ?", [skill_id])
    r = await cur.fetchone()
    return dict(r) if r else None


async def find_skill_by_owner_name(owner_user_id: str, name: str) -> dict | None:
    """按 owner+name 查找私有技能定义。"""
    cur = await get_db().execute(
        "SELECT * FROM skills WHERE owner_user_id = ? AND name = ? AND visibility = 'private'",
        [owner_user_id, name])
    r = await cur.fetchone()
    return dict(r) if r else None


async def find_public_skill_by_name(name: str) -> dict | None:
    """按 name 查找公有技能定义。"""
    cur = await get_db().execute(
        "SELECT * FROM skills WHERE name = ? AND visibility = 'public'", [name])
    r = await cur.fetchone()
    return dict(r) if r else None


async def list_skill_catalog(user_id: str) -> list[dict]:
    """用户可见目录：所有公有 + 本人私有。"""
    cur = await get_db().execute(
        "SELECT * FROM skills WHERE visibility = 'public' OR owner_user_id = ? ORDER BY created_at DESC",
        [user_id])
    return [dict(r) for r in await cur.fetchall()]


async def update_skill_definition(skill_id: str, *, description=None, version=None,
                                  content=None) -> bool:
    """更新技能定义的可选字段；未传字段保持原值。"""
    existing = await find_skill_by_id(skill_id)
    if not existing:
        return False
    new_desc = description if description is not None else existing.get("description")
    new_version = version if version is not None else existing.get("version")
    new_content = content if content is not None else existing.get("content")
    await get_db().execute(
        "UPDATE skills SET description=?, version=?, content=?, content_hash=?, updated_at=? WHERE id=?",
        [new_desc, new_version, new_content, _skill_hash(new_content), _now_ms(), skill_id])
    await get_db().commit()
    return True


async def delete_skill_definition(skill_id: str) -> bool:
    """删除技能定义，并级联删除引用它的安装记录（避免孤儿记录）。"""
    db = get_db()
    await db.execute("DELETE FROM agent_skills WHERE skill_id = ?", [skill_id])
    cur = await db.execute("DELETE FROM skills WHERE id = ?", [skill_id])
    await db.commit()
    return cur.rowcount > 0


async def count_installs_by_skill() -> dict[str, int]:
    """统计每个技能定义的安装次数（用于目录热度展示）。"""
    cur = await get_db().execute(
        "SELECT skill_id, COUNT(*) AS cnt FROM agent_skills WHERE skill_id IS NOT NULL GROUP BY skill_id")
    return {r["skill_id"]: r["cnt"] for r in await cur.fetchall()}


async def list_all_skill_definitions() -> list[dict]:
    """管理员：列出所有技能定义（公有 + 所有用户私有）。"""
    cur = await get_db().execute("SELECT * FROM skills ORDER BY created_at DESC")
    return [dict(r) for r in await cur.fetchall()]


async def list_agents_by_skill(skill_id: str) -> list[str]:
    """返回安装过某技能的所有 agent_id（用于删除定义时清理各 agent 的文件）。"""
    cur = await get_db().execute(
        "SELECT DISTINCT agent_id FROM agent_skills WHERE skill_id = ?", [skill_id])
    return [r["agent_id"] for r in await cur.fetchall()]


# ====== sso_links 表操作 ======

async def insert_sso_link(record: dict) -> None:
    await get_db().execute(
        "INSERT OR REPLACE INTO sso_links (provider, subject, user_id, created_at) "
        "VALUES (?, ?, ?, ?)",
        [record["provider"], record["subject"], record["user_id"], record["created_at"]]
    )
    await get_db().commit()


async def find_sso_link(provider: str, subject: str) -> dict | None:
    cur = await get_db().execute(
        "SELECT * FROM sso_links WHERE provider = ? AND subject = ?",
        [provider, subject]
    )
    row = await cur.fetchone()
    return dict(row) if row else None
