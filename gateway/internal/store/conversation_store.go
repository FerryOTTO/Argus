package store

import (
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
)

// ConversationFilter defines the filter criteria for querying conversation logs
type ConversationFilter struct {
	UserID    int64  `json:"user_id"`
	ModelID   string `json:"model_id"`
	StartTime string `json:"start_time"`
	EndTime   string `json:"end_time"`
	Page      int    `json:"page"`
	PageSize  int    `json:"page_size"`
}

// ConversationStore handles conversation log storage with async batch writing
type ConversationStore struct {
	db     *sqlx.DB
	ch     chan *model.ConversationLog
	done   chan struct{}
	mu     sync.Mutex
	closed bool
}

// NewConversationStore creates a new ConversationStore and starts the background worker
func NewConversationStore(db *sqlx.DB, batchSize int) *ConversationStore {
	if batchSize <= 0 {
		batchSize = 16
	}
	s := &ConversationStore{
		db:   db,
		ch:   make(chan *model.ConversationLog, 128),
		done: make(chan struct{}),
	}
	go s.worker()
	return s
}

// Log sends a conversation log entry to the async writer (non-blocking)
func (s *ConversationStore) Log(entry *model.ConversationLog) {
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
		slog.Warn("conversation log channel full, dropping entry", "user_id", entry.UserID, "model_id", entry.ModelID)
	}
}

// WriteSync writes a conversation log entry synchronously,
// using the shared DBWriteMu to avoid SQLITE_BUSY contention with audit store.
func (s *ConversationStore) WriteSync(entry *model.ConversationLog) {
	isStream := 0
	if entry.IsStream {
		isStream = 1
	}

	DBWriteMu.Lock()
	defer DBWriteMu.Unlock()

	_, err := ExecWithRetry(s.db, `
		INSERT INTO conversation_logs (audit_log_id, user_id, api_key_id, model_id, request_body, response_body, is_stream, prompt_tokens, completion_tokens, status_code, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, entry.AuditLogID, entry.UserID, entry.APIKeyID, entry.ModelID,
		entry.RequestBody, entry.ResponseBody, isStream,
		entry.PromptTokens, entry.CompletionTokens, entry.StatusCode, entry.CreatedAt,
	)
	if err != nil {
		slog.Error("failed to insert conversation log (sync)", "error", err, "user_id", entry.UserID)
	}
}

// Query returns paginated conversation logs matching the filter (without request_body/response_body)
func (s *ConversationStore) Query(filter ConversationFilter) ([]model.ConversationLog, int, error) {
	where, args := buildConvWhere(filter)

	var total int
	countQuery := "SELECT COUNT(*) FROM conversation_logs" + where
	if err := s.db.Get(&total, countQuery, args...); err != nil {
		return nil, 0, fmt.Errorf("failed to count conversation logs: %w", err)
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

	query := "SELECT id, audit_log_id, user_id, api_key_id, model_id, is_stream, prompt_tokens, completion_tokens, status_code, created_at FROM conversation_logs" + where + " ORDER BY created_at DESC LIMIT ? OFFSET ?"
	queryArgs := append(args, pageSize, offset)

	logs := []model.ConversationLog{}
	if err := s.db.Select(&logs, query, queryArgs...); err != nil {
		return nil, 0, fmt.Errorf("failed to query conversation logs: %w", err)
	}

	return logs, total, nil
}

// GetDetail returns a single conversation log with full body content
func (s *ConversationStore) GetDetail(id int64) (*model.ConversationLog, error) {
	var log model.ConversationLog
	if err := s.db.Get(&log, "SELECT * FROM conversation_logs WHERE id = ?", id); err != nil {
		return nil, fmt.Errorf("failed to get conversation log detail: %w", err)
	}
	return &log, nil
}

// CleanupOldLogs deletes conversation logs older than retentionDays
func (s *ConversationStore) CleanupOldLogs(retentionDays int) (int64, error) {
	cutoff := fmt.Sprintf("datetime('now', '-%d days')", retentionDays)
	result, err := ExecWithRetry(s.db, "DELETE FROM conversation_logs WHERE created_at < " + cutoff)
	if err != nil {
		return 0, fmt.Errorf("failed to cleanup conversation logs: %w", err)
	}
	deleted, _ := result.RowsAffected()
	return deleted, nil
}

// Close signals the background worker to stop and drains remaining entries
func (s *ConversationStore) Close() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.closed {
		s.closed = true
		close(s.done)
	}
}

// worker runs in a background goroutine and batch-writes conversation logs
func (s *ConversationStore) worker() {
	batch := make([]*model.ConversationLog, 0, 32)
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
			if len(batch) >= 32 {
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

// flushBatch writes a batch of conversation logs to the database.
// Uses individual INSERT statements (no transaction) to minimize lock hold time,
// since conversation records contain large text fields.
// Holds DBWriteMu for the entire batch to serialize with audit store writes.
func (s *ConversationStore) flushBatch(batch []*model.ConversationLog) {
	if len(batch) == 0 {
		return
	}

	DBWriteMu.Lock()
	defer DBWriteMu.Unlock()

	for _, entry := range batch {
		isStream := 0
		if entry.IsStream {
			isStream = 1
		}
		_, err := ExecWithRetry(s.db, `
			INSERT INTO conversation_logs (audit_log_id, user_id, api_key_id, model_id, request_body, response_body, is_stream, prompt_tokens, completion_tokens, status_code, created_at)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`, entry.AuditLogID, entry.UserID, entry.APIKeyID, entry.ModelID,
			entry.RequestBody, entry.ResponseBody, isStream,
			entry.PromptTokens, entry.CompletionTokens, entry.StatusCode, entry.CreatedAt,
		)
		if err != nil {
			slog.Error("failed to insert conversation log", "error", err, "user_id", entry.UserID)
		}
	}
}

// buildConvWhere constructs the WHERE clause for conversation log queries
func buildConvWhere(filter ConversationFilter) (string, []interface{}) {
	var conditions []string
	var args []interface{}

	if filter.UserID > 0 {
		conditions = append(conditions, "user_id = ?")
		args = append(args, filter.UserID)
	}
	if filter.ModelID != "" {
		conditions = append(conditions, "model_id = ?")
		args = append(args, filter.ModelID)
	}
	if filter.StartTime != "" {
		conditions = append(conditions, "created_at >= ?")
		args = append(args, filter.StartTime)
	}
	if filter.EndTime != "" {
		conditions = append(conditions, "created_at <= ?")
		args = append(args, filter.EndTime)
	}

	if len(conditions) == 0 {
		return "", nil
	}
	return " WHERE " + strings.Join(conditions, " AND "), args
}
