package model

import "time"

type Provider struct {
	ID           int64     `db:"id" json:"id"`
	Name         string    `db:"name" json:"name"`
	DisplayName  string    `db:"display_name" json:"display_name"`
	ProviderType string    `db:"provider_type" json:"provider_type"`
	APIBaseURL   string    `db:"api_base_url" json:"api_base_url"`
	APIKey       string    `db:"api_key" json:"-"`
	IsActive     bool      `db:"is_active" json:"is_active"`
	CreatedAt    time.Time `db:"created_at" json:"created_at"`
	UpdatedAt    time.Time `db:"updated_at" json:"updated_at"`
}

type Model struct {
	ID          int64     `db:"id" json:"id"`
	ProviderID  int64     `db:"provider_id" json:"provider_id"`
	ModelID     string    `db:"model_id" json:"model_id"`
	DisplayName string    `db:"display_name" json:"display_name"`
	IsActive    bool      `db:"is_active" json:"is_active"`
	CreatedAt   time.Time `db:"created_at" json:"created_at"`
}

// ModelWithProvider is used for admin display
type ModelWithProvider struct {
	Model
	ProviderName string `db:"provider_name" json:"provider_name"`
	ProviderType string `db:"provider_type" json:"provider_type"`
}
