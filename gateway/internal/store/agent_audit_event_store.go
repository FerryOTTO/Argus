package store

import (
	"fmt"
	"strings"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
)

// AgentAuditFilter 定义终端审计事件的筛选条件。
// 时间字段（StartTime/EndTime）为已归一化的 UTC RFC3339 秒级定宽文本
// （model.AuditEventTimeLayout），文本比较即时间比较。
type AgentAuditFilter struct {
	TerminalID   *int64
	Stage        string
	Action       string
	SourceModule string
	RiskMin      *float64
	Q            string
	StartTime    string
	EndTime      string
	Page         int
	PageSize     int
}

// AgentAuditStats 是"审计日志 · 终端审计"板块的汇总统计。
type AgentAuditStats struct {
	TotalEvents   int64 `json:"total_events"`
	TodayEvents   int64 `json:"today_events"`
	AlertsToday   int64 `json:"alerts_today"`    // 今日 action != allow
	HighRiskToday int64 `json:"high_risk_today"` // 今日 risk_score >= 0.7
}

// AgentAuditEventStore 负责终端 Argus 审计事件（agent_audit_events）的读写。
type AgentAuditEventStore struct {
	db *sqlx.DB
}

// NewAgentAuditEventStore creates a new AgentAuditEventStore
func NewAgentAuditEventStore(db *sqlx.DB) *AgentAuditEventStore {
	return &AgentAuditEventStore{db: db}
}

// InsertBatch 幂等写入一批审计事件：以 (terminal_id, event_id) 判重，
// 已存在的行经 INSERT OR IGNORE 自动跳过。返回实际新增条数（重复数 = 传入数 - 返回值）。
func (s *AgentAuditEventStore) InsertBatch(events []model.AgentAuditEvent) (int64, error) {
	if len(events) == 0 {
		return 0, nil
	}

	DBWriteMu.Lock()
	defer DBWriteMu.Unlock()

	tx, err := s.db.Beginx()
	if err != nil {
		return 0, fmt.Errorf("failed to begin audit event insert: %w", err)
	}
	defer tx.Rollback()

	stmt, err := tx.Preparex(`
		INSERT OR IGNORE INTO agent_audit_events
			(terminal_id, terminal_name, event_id, trace_id, session_id, user_id,
			 event_time, stage, source_module, action, risk_score, reason, content, metadata)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`)
	if err != nil {
		return 0, fmt.Errorf("failed to prepare audit event insert: %w", err)
	}
	defer stmt.Close()

	var accepted int64
	for _, ev := range events {
		res, err := stmt.Exec(
			ev.TerminalID, ev.TerminalName, ev.EventID, ev.TraceID, ev.SessionID, ev.UserID,
			ev.EventTime, ev.Stage, ev.SourceModule, ev.Action, ev.RiskScore, ev.Reason,
			ev.Content, ev.Metadata,
		)
		if err != nil {
			return 0, fmt.Errorf("failed to insert audit event %q: %w", ev.EventID, err)
		}
		if n, err := res.RowsAffected(); err == nil {
			accepted += n
		}
	}

	if err := tx.Commit(); err != nil {
		return 0, fmt.Errorf("failed to commit audit event batch: %w", err)
	}
	return accepted, nil
}

// Query 返回满足筛选条件的分页审计事件（按 event_time 倒序）。
func (s *AgentAuditEventStore) Query(filter AgentAuditFilter) ([]model.AgentAuditEvent, int64, error) {
	where, args := buildAgentAuditWhere(filter)

	var total int64
	if err := s.db.Get(&total, "SELECT COUNT(*) FROM agent_audit_events"+where, args...); err != nil {
		return nil, 0, fmt.Errorf("failed to count agent audit events: %w", err)
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

	queryArgs := append(args, pageSize, offset)
	events := []model.AgentAuditEvent{}
	if err := s.db.Select(&events,
		"SELECT * FROM agent_audit_events"+where+" ORDER BY event_time DESC, id DESC LIMIT ? OFFSET ?",
		queryArgs...,
	); err != nil {
		return nil, 0, fmt.Errorf("failed to query agent audit events: %w", err)
	}

	return events, total, nil
}

// Stats 返回审计事件汇总统计（"今日"按服务器本地时区的自然日边界计）。
func (s *AgentAuditEventStore) Stats() (*AgentAuditStats, error) {
	bjMidnight := BeijingDayStart(time.Now())
	today := bjMidnight.UTC().Format(model.AuditEventTimeLayout)

	stats := &AgentAuditStats{}
	if err := s.db.Get(&stats.TotalEvents, "SELECT COUNT(*) FROM agent_audit_events"); err != nil {
		return nil, fmt.Errorf("failed to count total agent audit events: %w", err)
	}
	if err := s.db.Get(&stats.TodayEvents,
		"SELECT COUNT(*) FROM agent_audit_events WHERE event_time >= ?", today); err != nil {
		return nil, fmt.Errorf("failed to count today agent audit events: %w", err)
	}
	if err := s.db.Get(&stats.AlertsToday,
		"SELECT COUNT(*) FROM agent_audit_events WHERE event_time >= ? AND action != 'allow'", today); err != nil {
		return nil, fmt.Errorf("failed to count today alerts: %w", err)
	}
	if err := s.db.Get(&stats.HighRiskToday,
		"SELECT COUNT(*) FROM agent_audit_events WHERE event_time >= ? AND risk_score >= 0.7", today); err != nil {
		return nil, fmt.Errorf("failed to count today high-risk events: %w", err)
	}
	return stats, nil
}

// TerminalStats 返回每台终端的审计聚合统计（terminals LEFT JOIN 事件表，无审计事件的终端也返回、计数为 0），
// 供"审计日志 · 终端审计"以终端为单位的列表使用；按最近审计时间倒序，无审计者置后。
func (s *AgentAuditEventStore) TerminalStats() ([]model.AgentTerminalAuditStats, error) {
	bjMidnight := BeijingDayStart(time.Now())
	today := bjMidnight.UTC().Format(model.AuditEventTimeLayout)

	var stats []model.AgentTerminalAuditStats
	if err := s.db.Select(&stats, `
		SELECT t.id AS terminal_id, t.name AS terminal_name, t.agent_type, t.status,
		       t.hostname, t.os_info, t.agent_version, t.argus_version, t.last_seen_at,
		       COUNT(e.id) AS total_events,
		       COALESCE(SUM(CASE WHEN e.event_time >= ? THEN 1 ELSE 0 END), 0) AS today_events,
		       COALESCE(SUM(CASE WHEN e.event_time >= ? AND e.action != 'allow' THEN 1 ELSE 0 END), 0) AS alerts_today,
		       COALESCE(SUM(CASE WHEN e.event_time >= ? AND e.risk_score >= 0.7 THEN 1 ELSE 0 END), 0) AS high_risk_today,
		       MAX(e.event_time) AS last_event_time
		FROM agent_terminals t
		LEFT JOIN agent_audit_events e ON e.terminal_id = t.id
		GROUP BY t.id
		ORDER BY last_event_time IS NULL ASC, last_event_time DESC, t.id ASC
	`, today, today, today); err != nil {
		return nil, fmt.Errorf("failed to query terminal audit stats: %w", err)
	}
	return stats, nil
}

// CleanupOldEvents 删除 event_time 早于保留期的审计事件，返回删除条数。
func (s *AgentAuditEventStore) CleanupOldEvents(retentionDays int) (int64, error) {
	cutoff := time.Now().AddDate(0, 0, -retentionDays).UTC().Format(model.AuditEventTimeLayout)
	res, err := ExecWithRetry(s.db, "DELETE FROM agent_audit_events WHERE event_time < ?", cutoff)
	if err != nil {
		return 0, fmt.Errorf("failed to cleanup agent audit events: %w", err)
	}
	return res.RowsAffected()
}

// DeleteByTerminal 删除指定终端的全部审计事件（删除终端时级联清理），返回删除条数。
func (s *AgentAuditEventStore) DeleteByTerminal(terminalID int64) (int64, error) {
	res, err := ExecWithRetry(s.db, "DELETE FROM agent_audit_events WHERE terminal_id = ?", terminalID)
	if err != nil {
		return 0, fmt.Errorf("failed to delete agent audit events for terminal %d: %w", terminalID, err)
	}
	return res.RowsAffected()
}

// buildAgentAuditWhere 构造终端审计事件的 WHERE 子句（条件参数顺序与占位符一致）。
func buildAgentAuditWhere(filter AgentAuditFilter) (string, []interface{}) {
	var conditions []string
	var args []interface{}

	if filter.TerminalID != nil {
		conditions = append(conditions, "terminal_id = ?")
		args = append(args, *filter.TerminalID)
	}
	if filter.Stage != "" {
		conditions = append(conditions, "stage = ?")
		args = append(args, filter.Stage)
	}
	if filter.Action != "" {
		conditions = append(conditions, "action = ?")
		args = append(args, filter.Action)
	}
	if filter.SourceModule != "" {
		conditions = append(conditions, "source_module = ?")
		args = append(args, filter.SourceModule)
	}
	if filter.RiskMin != nil {
		conditions = append(conditions, "risk_score >= ?")
		args = append(args, *filter.RiskMin)
	}
	if q := strings.TrimSpace(filter.Q); q != "" {
		pattern := "%" + q + "%"
		conditions = append(conditions, `(terminal_name LIKE ? OR trace_id LIKE ? OR session_id LIKE ? OR user_id LIKE ? OR event_id LIKE ? OR reason LIKE ?)`)
		for i := 0; i < 6; i++ {
			args = append(args, pattern)
		}
	}
	if filter.StartTime != "" {
		conditions = append(conditions, "event_time >= ?")
		args = append(args, filter.StartTime)
	}
	if filter.EndTime != "" {
		conditions = append(conditions, "event_time <= ?")
		args = append(args, filter.EndTime)
	}

	if len(conditions) == 0 {
		return "", nil
	}
	return " WHERE " + strings.Join(conditions, " AND "), args
}
