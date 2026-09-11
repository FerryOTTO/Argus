package model

import "time"

// AgentTerminal 表示一台接入遥测/集控端的智能体终端（当前为运行 OpenClaw + Clawguard 的主机）。
// 敏感凭据字段（RegistrationCodeHash/TelemetryTokenHash）永不出现在 JSON 响应中。
type AgentTerminal struct {
	ID            int64   `db:"id" json:"id"`
	Name          string  `db:"name" json:"name"`
	AgentType     string  `db:"agent_type" json:"agent_type"`
	BoundUserID   *int64  `db:"bound_user_id" json:"bound_user_id,omitempty"`
	BoundUsername *string `db:"bound_username" json:"bound_username,omitempty"`
	Description   string  `db:"description" json:"description"`
	// 注册状态: pending（未注册/待重注册）| active（遥测令牌有效）
	Status           string     `db:"status" json:"status"`
	Hostname         string     `db:"hostname" json:"hostname"`
	OSInfo           string     `db:"os_info" json:"os_info"`
	AgentVersion     string     `db:"agent_version" json:"agent_version"`
	ClawguardVersion string     `db:"clawguard_version" json:"clawguard_version"`
	LastSeenAt       *time.Time `db:"last_seen_at" json:"last_seen_at,omitempty"`
	// 纯遥测上报聚合的运行指标（客户端累计增量上报，见 REMOTE.md）
	TokenUsageTotal int64 `db:"token_usage_total" json:"token_usage_total"`
	AlertCountTotal int64 `db:"alert_count_total" json:"alert_count_total"`
	// 集控下发的 Clawguard 配置（不透明文本，配置内容经独立端点读写）
	DesiredConfig        string     `db:"desired_config" json:"-"`
	ConfigVersion        int64      `db:"config_version" json:"config_version"`
	ConfigUpdatedAt      *time.Time `db:"config_updated_at" json:"config_updated_at,omitempty"`
	ConfigAppliedVersion int64      `db:"config_applied_version" json:"config_applied_version"`
	ConfigAppliedAt      *time.Time `db:"config_applied_at" json:"config_applied_at,omitempty"`
	// LLMAPIKeyID 为注册时平台签发并下发终端的 LLM key（空=未签发/已撤销）
	LLMAPIKeyID *int64 `db:"llm_api_key_id" json:"llm_api_key_id,omitempty"`
	// Online 由 handler 依据 last_seen_at 动态计算，非库字段
	Online               bool      `db:"-" json:"online"`
	RegistrationCodeHash string    `db:"registration_code_hash" json:"-"`
	TelemetryTokenHash   string    `db:"telemetry_token_hash" json:"-"`
	CreatedAt            time.Time `db:"created_at" json:"created_at"`
	UpdatedAt            time.Time `db:"updated_at" json:"updated_at"`
}

// TerminalOption 为扩展治理等场景的终端下拉/多选轻量选项（不含敏感与长文本字段）。
type TerminalOption struct {
	ID        int64  `db:"id" json:"id"`
	Name      string `db:"name" json:"name"`
	AgentType string `db:"agent_type" json:"agent_type"`
	Status    string `db:"status" json:"status"`
	Hostname  string `db:"hostname" json:"hostname"`
}
