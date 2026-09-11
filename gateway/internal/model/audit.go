package model

import "time"

// AuditEventTimeLayout 是终端审计事件 event_time 的落库定宽格式（UTC RFC3339 秒级）。
// 客户端上报的时间一律归一化为此格式，保证文本序 = 时间序，可做区间与排序查询。
const AuditEventTimeLayout = "2006-01-02T15:04:05Z"

type AuditLog struct {
	ID               int64     `db:"id" json:"id"`
	APIKeyID         *int64    `db:"api_key_id" json:"api_key_id,omitempty"`
	UserID           int64     `db:"user_id" json:"user_id"`
	Action           string    `db:"action" json:"action"`
	ModelID          *string   `db:"model_id" json:"model_id,omitempty"`
	RequestPath      string    `db:"request_path" json:"request_path"`
	StatusCode       int       `db:"status_code" json:"status_code"`
	PromptTokens     int       `db:"prompt_tokens" json:"prompt_tokens"`
	CompletionTokens int       `db:"completion_tokens" json:"completion_tokens"`
	LatencyMs        int64     `db:"latency_ms" json:"latency_ms"`
	ClientIP         *string   `db:"client_ip" json:"client_ip,omitempty"`
	UserAgent        *string   `db:"user_agent" json:"user_agent,omitempty"`
	ErrorMessage     *string   `db:"error_message" json:"error_message,omitempty"`
	CreatedAt        time.Time `db:"created_at" json:"created_at"`
}

// AgentAuditEvent 是终端 Argus 审计层上报的一条审计事件（agent_audit_events 行）。
// content/metadata 为 JSON 文本；event_time 为 UTC RFC3339 秒级定宽文本（见 AuditEventTimeLayout）。
type AgentAuditEvent struct {
	ID           int64     `db:"id" json:"id"`
	TerminalID   int64     `db:"terminal_id" json:"terminal_id"`
	TerminalName string    `db:"terminal_name" json:"terminal_name"`
	EventID      string    `db:"event_id" json:"event_id"`
	TraceID      string    `db:"trace_id" json:"trace_id"`
	SessionID    string    `db:"session_id" json:"session_id"`
	UserID       string    `db:"user_id" json:"user_id"`
	EventTime    string    `db:"event_time" json:"event_time"`
	Stage        string    `db:"stage" json:"stage"`
	SourceModule string    `db:"source_module" json:"source_module"`
	Action       string    `db:"action" json:"action"`
	RiskScore    float64   `db:"risk_score" json:"risk_score"`
	Reason       string    `db:"reason" json:"reason"`
	Content      string    `db:"content" json:"content"`
	Metadata     string    `db:"metadata" json:"metadata"`
	ReceivedAt   time.Time `db:"received_at" json:"received_at"`
}

// AgentTerminalAuditStats 是"审计日志 · 终端审计"左栏终端列表的审计聚合
// （terminals LEFT JOIN agent_audit_events 按终端 GROUP BY；无审计事件的终端计数为 0）。
type AgentTerminalAuditStats struct {
	TerminalID       int64      `db:"terminal_id" json:"terminal_id"`
	TerminalName     string     `db:"terminal_name" json:"terminal_name"`
	AgentType        string     `db:"agent_type" json:"agent_type"`
	Status           string     `db:"status" json:"status"`
	Hostname         string     `db:"hostname" json:"hostname"`
	OSInfo           string     `db:"os_info" json:"os_info"`
	AgentVersion     string     `db:"agent_version" json:"agent_version"`
	ArgusVersion string     `db:"argus_version" json:"argus_version"`
	LastSeenAt       *time.Time `db:"last_seen_at" json:"last_seen_at,omitempty"`
	// Online 由 handler 依 last_seen_at 动态计算（口径同终端管理），非库字段
	Online        bool    `db:"-" json:"online"`
	TotalEvents   int64   `db:"total_events" json:"total_events"`
	TodayEvents   int64   `db:"today_events" json:"today_events"`
	AlertsToday   int64   `db:"alerts_today" json:"alerts_today"`
	HighRiskToday int64   `db:"high_risk_today" json:"high_risk_today"`
	LastEventTime *string `db:"last_event_time" json:"last_event_time,omitempty"`
}

type UsageHourly struct {
	ID               int64     `db:"id" json:"id"`
	UserID           int64     `db:"user_id" json:"user_id"`
	ModelID          string    `db:"model_id" json:"model_id"`
	HourStart        time.Time `db:"hour_start" json:"hour_start"`
	RequestCount     int       `db:"request_count" json:"request_count"`
	PromptTokens     int       `db:"prompt_tokens" json:"prompt_tokens"`
	CompletionTokens int       `db:"completion_tokens" json:"completion_tokens"`
}

type UsageDaily struct {
	ID               int64  `db:"id" json:"id"`
	UserID           int64  `db:"user_id" json:"user_id"`
	ModelID          string `db:"model_id" json:"model_id"`
	DayStart         string `db:"day_start" json:"day_start"`
	RequestCount     int    `db:"request_count" json:"request_count"`
	PromptTokens     int    `db:"prompt_tokens" json:"prompt_tokens"`
	CompletionTokens int    `db:"completion_tokens" json:"completion_tokens"`
}
