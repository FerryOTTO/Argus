package store

import (
	"database/sql"
	"fmt"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
)

// QuotaStore handles quota and usage database operations
type QuotaStore struct {
	db *sqlx.DB
}

// NewQuotaStore creates a new QuotaStore
func NewQuotaStore(db *sqlx.DB) *QuotaStore {
	return &QuotaStore{db: db}
}

// --- Quota methods ---

// Create inserts a new quota
func (s *QuotaStore) Create(quota *model.Quota) error {
	query := `
		INSERT INTO quotas (user_id, model_id, quota_type, limit_value, is_active)
		VALUES (:user_id, :model_id, :quota_type, :limit_value, :is_active)
	`
	result, err := s.db.NamedExec(query, quota)
	if err != nil {
		return fmt.Errorf("failed to create quota: %w", err)
	}

	id, err := result.LastInsertId()
	if err != nil {
		return fmt.Errorf("failed to get last insert id: %w", err)
	}
	quota.ID = id

	return nil
}

// GetByUserID retrieves all quotas for a user
func (s *QuotaStore) GetByUserID(userID int64) ([]model.Quota, error) {
	quotas := []model.Quota{}
	query := `SELECT * FROM quotas WHERE user_id = ? AND is_active = 1`
	if err := s.db.Select(&quotas, query, userID); err != nil {
		return nil, fmt.Errorf("failed to get quotas by user: %w", err)
	}
	return quotas, nil
}

// GetByUserAndModel retrieves quotas for a specific user and model
func (s *QuotaStore) GetByUserAndModel(userID int64, modelID string) ([]model.Quota, error) {
	quotas := []model.Quota{}
	query := `SELECT * FROM quotas WHERE user_id = ? AND (model_id = ? OR model_id = '*') AND is_active = 1`
	if err := s.db.Select(&quotas, query, userID, modelID); err != nil {
		return nil, fmt.Errorf("failed to get quotas by user and model: %w", err)
	}
	return quotas, nil
}

// Update updates a quota
func (s *QuotaStore) Update(quota *model.Quota) error {
	query := `
		UPDATE quotas
		SET model_id = :model_id, quota_type = :quota_type, limit_value = :limit_value, is_active = :is_active
		WHERE id = :id
	`
	result, err := s.db.NamedExec(query, quota)
	if err != nil {
		return fmt.Errorf("failed to update quota: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("quota not found")
	}

	return nil
}

// Delete deletes a quota by ID
func (s *QuotaStore) Delete(id int64) error {
	query := `DELETE FROM quotas WHERE id = ?`
	result, err := ExecWithRetry(s.db, query, id)
	if err != nil {
		return fmt.Errorf("failed to delete quota: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("quota not found")
	}

	return nil
}

// --- Usage methods ---

// RecordUsage inserts a usage record
func (s *QuotaStore) RecordUsage(record *model.UsageRecord) error {
	query := `
		INSERT INTO usage_records (api_key_id, user_id, model_id, prompt_tokens, completion_tokens, latency_ms, status_code, error_message, client_ip, created_at)
		VALUES (:api_key_id, :user_id, :model_id, :prompt_tokens, :completion_tokens, :latency_ms, :status_code, :error_message, :client_ip, :created_at)
	`
	result, err := s.db.NamedExec(query, record)
	if err != nil {
		return fmt.Errorf("failed to record usage: %w", err)
	}

	id, err := result.LastInsertId()
	if err != nil {
		return fmt.Errorf("failed to get last insert id: %w", err)
	}
	record.ID = id

	return nil
}

// GetUsageByAPIKey retrieves usage records for a specific API key since a given time
func (s *QuotaStore) GetUsageByAPIKey(apiKeyID int64, since time.Time) ([]model.UsageRecord, error) {
	records := []model.UsageRecord{}
	query := `SELECT * FROM usage_records WHERE api_key_id = ? AND created_at >= ? ORDER BY created_at DESC`
	if err := s.db.Select(&records, query, apiKeyID, since); err != nil {
		return nil, fmt.Errorf("failed to get usage by api key: %w", err)
	}
	return records, nil
}

// GetUsageByUserID retrieves usage records for a specific user since a given time
func (s *QuotaStore) GetUsageByUserID(userID int64, since time.Time) ([]model.UsageRecord, error) {
	records := []model.UsageRecord{}
	query := `SELECT * FROM usage_records WHERE user_id = ? AND created_at >= ? ORDER BY created_at DESC`
	if err := s.db.Select(&records, query, userID, since); err != nil {
		return nil, fmt.Errorf("failed to get usage by user: %w", err)
	}
	return records, nil
}

// GetCurrentWindowUsage calculates the current usage within the quota window
// For rpm/rpd: COUNT records in window
// For tpm/tpd: SUM(prompt_tokens + completion_tokens) in window
// Window: rpm=last 60s, rpd=today 00:00, tpm=last 60s, tpd=today 00:00
func (s *QuotaStore) GetCurrentWindowUsage(userID int64, modelID string, quotaType string) (float64, error) {
	var windowStart time.Time
	now := time.Now()

	switch quotaType {
	case "rpm", "tpm":
		windowStart = now.Add(-60 * time.Second)
	case "rpd", "tpd":
		windowStart = time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location())
	default:
		return 0, fmt.Errorf("unknown quota type: %s", quotaType)
	}

	var result sql.NullFloat64
	var query string

	switch quotaType {
	case "rpm", "rpd":
		query = `SELECT COUNT(*) FROM usage_records WHERE user_id = ? AND created_at >= ?`
		if modelID != "*" {
			query = `SELECT COUNT(*) FROM usage_records WHERE user_id = ? AND model_id = ? AND created_at >= ?`
			if err := s.db.Get(&result, query, userID, modelID, windowStart); err != nil {
				return 0, fmt.Errorf("failed to get current window usage: %w", err)
			}
		} else {
			if err := s.db.Get(&result, query, userID, windowStart); err != nil {
				return 0, fmt.Errorf("failed to get current window usage: %w", err)
			}
		}
	case "tpm", "tpd":
		query = `SELECT SUM(prompt_tokens + completion_tokens) FROM usage_records WHERE user_id = ? AND created_at >= ?`
		if modelID != "*" {
			query = `SELECT SUM(prompt_tokens + completion_tokens) FROM usage_records WHERE user_id = ? AND model_id = ? AND created_at >= ?`
			if err := s.db.Get(&result, query, userID, modelID, windowStart); err != nil {
				return 0, fmt.Errorf("failed to get current window usage: %w", err)
			}
		} else {
			if err := s.db.Get(&result, query, userID, windowStart); err != nil {
				return 0, fmt.Errorf("failed to get current window usage: %w", err)
			}
		}
	}

	if !result.Valid {
		return 0, nil
	}
	return result.Float64, nil
}
