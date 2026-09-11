package model

import "time"

type Quota struct {
	ID         int64     `db:"id" json:"id"`
	UserID     int64     `db:"user_id" json:"user_id"`
	ModelID    string    `db:"model_id" json:"model_id"`
	QuotaType  string    `db:"quota_type" json:"quota_type"`
	LimitValue float64   `db:"limit_value" json:"limit_value"`
	IsActive   bool      `db:"is_active" json:"is_active"`
	CreatedAt  time.Time `db:"created_at" json:"created_at"`
}

type UsageRecord struct {
	ID               int64     `db:"id" json:"id"`
	APIKeyID         *int64    `db:"api_key_id" json:"api_key_id,omitempty"`
	UserID           *int64    `db:"user_id" json:"user_id,omitempty"`
	ModelID          string    `db:"model_id" json:"model_id"`
	PromptTokens     int       `db:"prompt_tokens" json:"prompt_tokens"`
	CompletionTokens int       `db:"completion_tokens" json:"completion_tokens"`
	LatencyMs        int64     `db:"latency_ms" json:"latency_ms"`
	StatusCode       int       `db:"status_code" json:"status_code"`
	ErrorMessage     *string   `db:"error_message" json:"error_message,omitempty"`
	ClientIP         *string   `db:"client_ip" json:"client_ip,omitempty"`
	CreatedAt        time.Time `db:"created_at" json:"created_at"`
}
