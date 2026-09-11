-- 010: usage_records and conversation_logs user columns nullable.
-- JWT proxy calls carry no api_key_id; unowned keys carry no user_id.
-- Models use pointer fields; schemas must allow NULL. SQLite rebuild:
CREATE TABLE IF NOT EXISTS usage_records_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id INTEGER,
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
CREATE TABLE IF NOT EXISTS conversation_logs_new (
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
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
