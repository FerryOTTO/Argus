-- Agent Terminals: 遥测/集控管理的智能体终端（当前仅 OpenClaw，agent_type 可扩展）
CREATE TABLE IF NOT EXISTS agent_terminals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    -- 终端 Agent 类型: openclaw（后续可扩展 claude-code 等）
    agent_type TEXT NOT NULL DEFAULT 'openclaw',
    -- 绑定的 LLMGate 用户（可空，管理员在“添加终端”时选择）
    bound_user_id INTEGER,
    description TEXT NOT NULL DEFAULT '',
    -- 注册状态: pending（已创建/已吊销，未注册或待重注册）| active（已注册，遥测令牌有效）
    status TEXT NOT NULL DEFAULT 'pending',
    -- 凭据仅存 SHA-256 哈希，明文只在生成时返回一次；空串表示未签发/已吊销
    registration_code_hash TEXT NOT NULL DEFAULT '',
    telemetry_token_hash TEXT NOT NULL DEFAULT '',
    -- 以下为客户端心跳/上报填充的运行数据
    hostname TEXT NOT NULL DEFAULT '',
    os_info TEXT NOT NULL DEFAULT '',
    agent_version TEXT NOT NULL DEFAULT '',
    clawguard_version TEXT NOT NULL DEFAULT '',
    last_seen_at DATETIME,
    token_usage_total INTEGER NOT NULL DEFAULT 0,
    alert_count_total INTEGER NOT NULL DEFAULT 0,
    -- 集控下发的 Clawguard 配置（原样文本，语义由客户端解释，见 REMOTE.md）
    desired_config TEXT NOT NULL DEFAULT '',
    config_version INTEGER NOT NULL DEFAULT 0,
    config_updated_at DATETIME,
    config_applied_version INTEGER NOT NULL DEFAULT 0,
    config_applied_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY (bound_user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_agent_terminals_agent_type ON agent_terminals(agent_type);
CREATE INDEX IF NOT EXISTS idx_agent_terminals_bound_user ON agent_terminals(bound_user_id);
CREATE INDEX IF NOT EXISTS idx_agent_terminals_status ON agent_terminals(status);
CREATE INDEX IF NOT EXISTS idx_agent_terminals_last_seen ON agent_terminals(last_seen_at);
