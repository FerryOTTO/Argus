-- ============================================================================
-- 008: 平台 LLM 凭据下发与系统设置
-- 背景：终端用注册码注册时，由平台签发 LLM API key（随注册响应下发 base_url+key），
--       密钥进入 api_keys（密钥管理）并可归属到终端绑定用户。
-- 1) api_keys：user_id 允许 NULL（终端未绑定用户时签发"无主"key），
--    新增 terminal_id（注册自动签发来源标记；终端删除时置 NULL 保留历史密钥）；
-- 2) conversation_logs / usage_records：user_id 允许 NULL（无主 key 请求的记账）；
-- 3) settings：键值表（企业名称 / 系统根地址 / 开放模型白名单）；
-- 4) agent_terminals：新增 llm_api_key_id（当前生效下发的 LLM key）。
-- SQLite 变更列约束需重建表；整个文件由迁移器在同一条连接执行，临时关闭外键。
-- ============================================================================

PRAGMA foreign_keys = OFF;

-- ── api_keys：user_id 可空 + terminal_id ──────────────────────────────────────
CREATE TABLE api_keys_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    terminal_id INTEGER,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    permissions TEXT NOT NULL DEFAULT '[]',
    is_active INTEGER NOT NULL DEFAULT 1,
    expires_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (terminal_id) REFERENCES agent_terminals(id) ON DELETE SET NULL
);

INSERT INTO api_keys_new (id, user_id, terminal_id, name, key_hash, key_prefix, permissions, is_active, expires_at, created_at)
    SELECT id, user_id, NULL, name, key_hash, key_prefix, permissions, is_active, expires_at, created_at FROM api_keys;
DROP TABLE api_keys;
ALTER TABLE api_keys_new RENAME TO api_keys;

CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_terminal_id ON api_keys(terminal_id);

-- ── conversation_logs：user_id 可空（无主 key 的网关请求） ───────────────────
CREATE TABLE conversation_logs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_log_id INTEGER,
    user_id INTEGER,
    api_key_id INTEGER,
    model_id TEXT,
    request_body TEXT NOT NULL,
    response_body TEXT,
    is_stream INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    status_code INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (audit_log_id) REFERENCES audit_logs(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
);

INSERT INTO conversation_logs_new (id, audit_log_id, user_id, api_key_id, model_id, request_body, response_body, is_stream, prompt_tokens, completion_tokens, status_code, created_at)
    SELECT id, audit_log_id, user_id, api_key_id, model_id, request_body, response_body, is_stream, prompt_tokens, completion_tokens, status_code, created_at FROM conversation_logs;
DROP TABLE conversation_logs;
ALTER TABLE conversation_logs_new RENAME TO conversation_logs;

CREATE INDEX IF NOT EXISTS idx_conversation_logs_user_id ON conversation_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_conversation_logs_model_id ON conversation_logs(model_id);
CREATE INDEX IF NOT EXISTS idx_conversation_logs_created_at ON conversation_logs(created_at);

-- ── usage_records：user_id 可空 ───────────────────────────────────────────────
CREATE TABLE usage_records_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id INTEGER NOT NULL,
    user_id INTEGER,
    model_id TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL,
    status_code INTEGER NOT NULL,
    error_message TEXT,
    client_ip TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
);

INSERT INTO usage_records_new (id, api_key_id, user_id, model_id, prompt_tokens, completion_tokens, latency_ms, status_code, error_message, client_ip, created_at)
    SELECT id, api_key_id, user_id, model_id, prompt_tokens, completion_tokens, latency_ms, status_code, error_message, client_ip, created_at FROM usage_records;
DROP TABLE usage_records;
ALTER TABLE usage_records_new RENAME TO usage_records;

CREATE INDEX IF NOT EXISTS idx_usage_records_created ON usage_records(created_at);

-- ── settings：系统设置键值表 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── agent_terminals：当前下发的 LLM key ───────────────────────────────────────
ALTER TABLE agent_terminals ADD COLUMN llm_api_key_id INTEGER REFERENCES api_keys(id);

PRAGMA foreign_keys = ON;
