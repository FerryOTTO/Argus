package model

import "time"

type ConversationLog struct {
	ID               int64     `db:"id" json:"id"`
	AuditLogID       *int64    `db:"audit_log_id" json:"audit_log_id,omitempty"`
	UserID           *int64    `db:"user_id" json:"user_id,omitempty"`
	APIKeyID         *int64    `db:"api_key_id" json:"api_key_id,omitempty"`
	ModelID          *string   `db:"model_id" json:"model_id,omitempty"`
	RequestBody      string    `db:"request_body" json:"request_body"`
	ResponseBody     *string   `db:"response_body" json:"response_body,omitempty"`
	IsStream         bool      `db:"is_stream" json:"is_stream"`
	PromptTokens     int       `db:"prompt_tokens" json:"prompt_tokens"`
	CompletionTokens int       `db:"completion_tokens" json:"completion_tokens"`
	StatusCode       int       `db:"status_code" json:"status_code"`
	CreatedAt        time.Time `db:"created_at" json:"created_at"`
}
