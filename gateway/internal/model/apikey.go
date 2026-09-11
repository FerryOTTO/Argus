package model

import "time"

type APIKey struct {
	ID          int64      `db:"id" json:"id"`
	UserID      *int64     `db:"user_id" json:"user_id,omitempty"`
	TerminalID  *int64     `db:"terminal_id" json:"terminal_id,omitempty"`
	Name        string     `db:"name" json:"name"`
	KeyHash     string     `db:"key_hash" json:"-"`
	KeyPrefix   string     `db:"key_prefix" json:"key_prefix"`
	Permissions string     `db:"permissions" json:"permissions"`
	IsActive    bool       `db:"is_active" json:"is_active"`
	ExpiresAt   *time.Time `db:"expires_at" json:"expires_at,omitempty"`
	CreatedAt   time.Time  `db:"created_at" json:"created_at"`
	// OwnerUsername/TerminalName 仅管理端列表 JOIN 展示字段，非 api_keys 表列
	OwnerUsername *string `db:"owner_username" json:"owner_username,omitempty"`
	TerminalName  *string `db:"terminal_name" json:"terminal_name,omitempty"`
}
