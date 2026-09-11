package store

import (
	"database/sql"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
)

// AuditFilter defines the filter criteria for querying audit logs
type AuditFilter struct {
	UserID    *int64
	APIKeyID  *int64
	Action    string
	ModelID   string
	StartTime *time.Time
	EndTime   *time.Time
	Page      int
	PageSize  int
}

// DashboardStats holds aggregated statistics for the admin dashboard
//（网关流量侧：平台代理请求与 token 消耗，来源 audit_logs）
type DashboardStats struct {
	TotalRequests  int64 `json:"total_requests"`
	TotalUsers     int64 `json:"total_users"`
	TotalAPIKeys   int64 `json:"total_api_keys"`
	TotalProviders int64 `json:"total_providers"`
	RequestsToday  int64 `json:"requests_today"`
	TokensToday    int64 `json:"tokens_today"`
	TokensTotal    int64 `json:"tokens_total"`
}

// AuditStore handles audit log storage with async batch writing
type AuditStore struct {
	db     *sqlx.DB
	ch     chan *model.AuditLog
	done   chan struct{}
	mu     sync.Mutex
	closed bool
}

// NewAuditStore creates a new AuditStore and starts the background worker
func NewAuditStore(db *sqlx.DB, batchSize int) *AuditStore {
	if batchSize <= 0 {
		batchSize = 1024
	}
	s := &AuditStore{
		db:   db,
		ch:   make(chan *model.AuditLog, batchSize),
		done: make(chan struct{}),
	}
	go s.worker()
	return s
}

// Log sends an audit log entry to the async writer (non-blocking)
func (s *AuditStore) Log(entry *model.AuditLog) {
	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		return
	}
	s.mu.Unlock()

	select {
	case s.ch <- entry:
		// Successfully queued
	default:
		slog.Warn("audit log channel full, dropping entry", "action", entry.Action, "user_id", entry.UserID)
	}
}

// Query returns paginated audit logs matching the filter
func (s *AuditStore) Query(filter AuditFilter) ([]model.AuditLog, int64, error) {
	where, args := buildAuditWhere(filter)

	var total int64
	countQuery := "SELECT COUNT(*) FROM audit_logs" + where
	if err := s.db.Get(&total, countQuery, args...); err != nil {
		return nil, 0, fmt.Errorf("failed to count audit logs: %w", err)
	}

	page := filter.Page
	if page < 1 {
		page = 1
	}
	pageSize := filter.PageSize
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	offset := (page - 1) * pageSize

	query := "SELECT * FROM audit_logs" + where + " ORDER BY created_at DESC LIMIT ? OFFSET ?"
	queryArgs := append(args, pageSize, offset)

	logs := []model.AuditLog{}
	if err := s.db.Select(&logs, query, queryArgs...); err != nil {
		return nil, 0, fmt.Errorf("failed to query audit logs: %w", err)
	}

	return logs, total, nil
}

// GetDashboardStats returns aggregated statistics for the dashboard
func (s *AuditStore) GetDashboardStats() (*DashboardStats, error) {
	stats := &DashboardStats{}

	// Total requests
	if err := s.db.Get(&stats.TotalRequests, "SELECT COUNT(*) FROM audit_logs"); err != nil {
		return nil, fmt.Errorf("failed to get total requests: %w", err)
	}

	// Total users
	if err := s.db.Get(&stats.TotalUsers, "SELECT COUNT(*) FROM users"); err != nil {
		return nil, fmt.Errorf("failed to get total users: %w", err)
	}

	// Total API keys
	if err := s.db.Get(&stats.TotalAPIKeys, "SELECT COUNT(*) FROM api_keys"); err != nil {
		return nil, fmt.Errorf("failed to get total api keys: %w", err)
	}

	// Total providers
	if err := s.db.Get(&stats.TotalProviders, "SELECT COUNT(*) FROM providers"); err != nil {
		return nil, fmt.Errorf("failed to get total providers: %w", err)
	}

	// Requests today（北京时间自然日零点起）
	today := BeijingDayStart(time.Now())
	if err := s.db.Get(&stats.RequestsToday, "SELECT COUNT(*) FROM audit_logs WHERE created_at >= ?", today); err != nil {
		return nil, fmt.Errorf("failed to get requests today: %w", err)
	}

	// Tokens today
	var tokens sql.NullInt64
	if err := s.db.Get(&tokens, "SELECT SUM(prompt_tokens + completion_tokens) FROM audit_logs WHERE created_at >= ?", today); err != nil {
		return nil, fmt.Errorf("failed to get tokens today: %w", err)
	}
	if tokens.Valid {
		stats.TokensToday = tokens.Int64
	}

	// Tokens total（全部历史累计）
	var tokensAll sql.NullInt64
	if err := s.db.Get(&tokensAll, "SELECT SUM(prompt_tokens + completion_tokens) FROM audit_logs"); err != nil {
		return nil, fmt.Errorf("failed to get tokens total: %w", err)
	}
	if tokensAll.Valid {
		stats.TokensTotal = tokensAll.Int64
	}

	return stats, nil
}

// Close signals the background worker to stop
func (s *AuditStore) Close() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.closed {
		s.closed = true
		close(s.done)
	}
}

// CleanupOldLogs deletes audit logs and usage records older than retentionDays
func (s *AuditStore) CleanupOldLogs(retentionDays int) (int64, int64, error) {
	cutoff := fmt.Sprintf("datetime('now', '-%d days')", retentionDays)

	// Delete old audit logs
	result, err := ExecWithRetry(s.db, "DELETE FROM audit_logs WHERE created_at < " + cutoff)
	if err != nil {
		return 0, 0, fmt.Errorf("failed to cleanup audit logs: %w", err)
	}
	auditDeleted, _ := result.RowsAffected()

	// Delete old usage records
	var usageDeleted int64
	result, err = ExecWithRetry(s.db, "DELETE FROM usage_records WHERE created_at < " + cutoff)
	if err != nil {
		// usage_records table may not exist, ignore error
		slog.Warn("failed to cleanup usage records (table may not exist)", "error", err)
		usageDeleted = 0
	} else {
		usageDeleted, _ = result.RowsAffected()
	}

	return auditDeleted, usageDeleted, nil
}

// worker runs in a background goroutine and batch-writes audit logs
func (s *AuditStore) worker() {
	batch := make([]*model.AuditLog, 0, 128)
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case entry := <-s.ch:
			batch = append(batch, entry)
			// Drain more entries if available
			draining := true
			for draining {
				select {
				case e := <-s.ch:
					batch = append(batch, e)
				default:
					draining = false
				}
			}
			if len(batch) >= 64 {
				s.flushBatch(batch)
				batch = batch[:0]
			}
		case <-ticker.C:
			// Drain any pending entries
			draining := true
			for draining {
				select {
				case e := <-s.ch:
					batch = append(batch, e)
				default:
					draining = false
				}
			}
			if len(batch) > 0 {
				s.flushBatch(batch)
				batch = batch[:0]
			}
		case <-s.done:
			// Drain remaining entries before exit
			draining := true
			for draining {
				select {
				case e := <-s.ch:
					batch = append(batch, e)
				default:
					draining = false
				}
			}
			if len(batch) > 0 {
				s.flushBatch(batch)
			}
			return
		}
	}
}

// flushBatch writes a batch of audit logs to the database.
// Uses individual INSERT statements (no transaction) to minimize SQLite lock hold time.
// Holds DBWriteMu for the entire batch to serialize with conversation store writes.
func (s *AuditStore) flushBatch(batch []*model.AuditLog) {
	if len(batch) == 0 {
		return
	}

	DBWriteMu.Lock()
	defer DBWriteMu.Unlock()

	for _, entry := range batch {
		_, err := ExecWithRetry(s.db, `
			INSERT INTO audit_logs (api_key_id, user_id, action, model_id, request_path, status_code, prompt_tokens, completion_tokens, latency_ms, client_ip, user_agent, error_message, created_at)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`, entry.APIKeyID, entry.UserID, entry.Action, entry.ModelID,
			entry.RequestPath, entry.StatusCode, entry.PromptTokens, entry.CompletionTokens,
			entry.LatencyMs, entry.ClientIP, entry.UserAgent, entry.ErrorMessage, entry.CreatedAt,
		)
		if err != nil {
			slog.Error("failed to insert audit log", "error", err, "action", entry.Action)
			continue
		}
		// Update usage aggregations
		s.aggregateUsage(entry)
	}
}

// aggregateUsage updates hourly and daily usage aggregation tables
func (s *AuditStore) aggregateUsage(entry *model.AuditLog) {
	if entry.ModelID == nil || *entry.ModelID == "" {
		return
	}
	modelID := *entry.ModelID
	now := entry.CreatedAt

	// Hourly aggregation
	hourStart := time.Date(now.Year(), now.Month(), now.Day(), now.Hour(), 0, 0, 0, now.Location())
	_, err := ExecWithRetry(s.db, `
		INSERT INTO usage_hourly (user_id, model_id, hour_start, request_count, prompt_tokens, completion_tokens)
		VALUES (?, ?, ?, 1, ?, ?)
		ON CONFLICT(user_id, model_id, hour_start) DO UPDATE SET
			request_count = request_count + 1,
			prompt_tokens = prompt_tokens + ?,
			completion_tokens = completion_tokens + ?
	`, entry.UserID, modelID, hourStart, entry.PromptTokens, entry.CompletionTokens, entry.PromptTokens, entry.CompletionTokens)
	if err != nil {
		slog.Error("failed to update hourly usage", "error", err)
	}

	// Daily aggregation
	dayStart := now.Format("2006-01-02")
	_, err = ExecWithRetry(s.db, `
		INSERT INTO usage_daily (user_id, model_id, day_start, request_count, prompt_tokens, completion_tokens)
		VALUES (?, ?, ?, 1, ?, ?)
		ON CONFLICT(user_id, model_id, day_start) DO UPDATE SET
			request_count = request_count + 1,
			prompt_tokens = prompt_tokens + ?,
			completion_tokens = completion_tokens + ?
	`, entry.UserID, modelID, dayStart, entry.PromptTokens, entry.CompletionTokens, entry.PromptTokens, entry.CompletionTokens)
	if err != nil {
		slog.Error("failed to update daily usage", "error", err)
	}
}

// buildAuditWhere constructs the WHERE clause for audit log queries
func buildAuditWhere(filter AuditFilter) (string, []interface{}) {
	var conditions []string
	var args []interface{}

	if filter.UserID != nil {
		conditions = append(conditions, "user_id = ?")
		args = append(args, *filter.UserID)
	}
	if filter.APIKeyID != nil {
		conditions = append(conditions, "api_key_id = ?")
		args = append(args, *filter.APIKeyID)
	}
	if filter.Action != "" {
		conditions = append(conditions, "action = ?")
		args = append(args, filter.Action)
	}
	if filter.ModelID != "" {
		conditions = append(conditions, "model_id = ?")
		args = append(args, filter.ModelID)
	}
	if filter.StartTime != nil {
		conditions = append(conditions, "created_at >= ?")
		args = append(args, *filter.StartTime)
	}
	if filter.EndTime != nil {
		conditions = append(conditions, "created_at <= ?")
		args = append(args, *filter.EndTime)
	}

	if len(conditions) == 0 {
		return "", nil
	}
	return " WHERE " + strings.Join(conditions, " AND "), args
}
