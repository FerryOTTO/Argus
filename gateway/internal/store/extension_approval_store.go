package store

import (
	"fmt"
	"strings"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
)

// ExtensionApprovalStore 负责 skill/MCP 安装审批单（extension_approvals）的存取。
type ExtensionApprovalStore struct {
	db *sqlx.DB
}

// NewExtensionApprovalStore creates a new ExtensionApprovalStore
func NewExtensionApprovalStore(db *sqlx.DB) *ExtensionApprovalStore {
	return &ExtensionApprovalStore{db: db}
}

// ApprovalFilter 为管理端审批列表的筛选条件。
type ApprovalFilter struct {
	State      string
	Kind       string
	TerminalID int64
	Keyword    string // 模糊匹配终端名/申请名
	Page       int
	PageSize   int
}

const approvalColumns = `
	id, terminal_id, terminal_name, kind, name, source, payload, reason,
	state, approve_mode, reviewer_id, review_note, reviewed_at, created_at, updated_at`

// Create 落一条新审批单（terminal_id 由遥测认证注入，name/终端名做快照）。
func (s *ExtensionApprovalStore) Create(a *model.ExtensionApproval) error {
	now := time.Now()
	a.CreatedAt = now
	a.UpdatedAt = now
	query := `INSERT INTO extension_approvals
		(terminal_id, terminal_name, kind, name, source, payload, reason,
		 state, approve_mode, reviewer_id, review_note, reviewed_at, created_at, updated_at)
		VALUES (:terminal_id, :terminal_name, :kind, :name, :source, :payload, :reason,
		        :state, :approve_mode, :reviewer_id, :review_note, :reviewed_at, :created_at, :updated_at)`
	res, err := s.db.NamedExec(query, a)
	if err != nil {
		return fmt.Errorf("failed to create extension approval: %w", err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return fmt.Errorf("failed to read extension approval id: %w", err)
	}
	a.ID = id
	return nil
}

// GetByID 单查（含载荷原文，管理端详情展示用）。
func (s *ExtensionApprovalStore) GetByID(id int64) (*model.ExtensionApproval, error) {
	var a model.ExtensionApproval
	if err := s.db.Get(&a, "SELECT "+approvalColumns+" FROM extension_approvals WHERE id = ?", id); err != nil {
		return nil, fmt.Errorf("failed to get extension approval %d: %w", id, err)
	}
	return &a, nil
}

// List 管理端分页列表（默认按申请时间倒序）。
func (s *ExtensionApprovalStore) List(f ApprovalFilter) ([]model.ExtensionApproval, int64, error) {
	where := []string{"1=1"}
	args := []any{}
	if f.State != "" {
		where = append(where, "state = ?")
		args = append(args, f.State)
	}
	if f.Kind != "" {
		where = append(where, "kind = ?")
		args = append(args, f.Kind)
	}
	if f.TerminalID > 0 {
		where = append(where, "terminal_id = ?")
		args = append(args, f.TerminalID)
	}
	if kw := strings.TrimSpace(f.Keyword); kw != "" {
		where = append(where, "(terminal_name LIKE ? OR name LIKE ?)")
		args = append(args, "%"+kw+"%", "%"+kw+"%")
	}
	cond := "WHERE " + strings.Join(where, " AND ")

	var total int64
	if err := s.db.Get(&total, "SELECT COUNT(*) FROM extension_approvals "+cond, args...); err != nil {
		return nil, 0, fmt.Errorf("failed to count extension approvals: %w", err)
	}
	if f.Page < 1 {
		f.Page = 1
	}
	if f.PageSize < 1 || f.PageSize > 100 {
		f.PageSize = 20
	}
	args = append(args, f.PageSize, (f.Page-1)*f.PageSize)

	items := []model.ExtensionApproval{}
	if err := s.db.Select(&items,
		"SELECT "+approvalColumns+" FROM extension_approvals "+cond+
			" ORDER BY id DESC LIMIT ? OFFSET ?", args...); err != nil {
		return nil, 0, fmt.Errorf("failed to list extension approvals: %w", err)
	}
	return items, total, nil
}

// ListByTerminal 返回某终端的最近审批单（倒序，limit 内），供客户端轮询对账。
func (s *ExtensionApprovalStore) ListByTerminal(terminalID int64, limit int) ([]model.ExtensionApproval, error) {
	if limit < 1 || limit > 500 {
		limit = 200
	}
	items := []model.ExtensionApproval{}
	if err := s.db.Select(&items,
		"SELECT "+approvalColumns+" FROM extension_approvals WHERE terminal_id = ? ORDER BY id DESC LIMIT ?",
		terminalID, limit); err != nil {
		return nil, fmt.Errorf("failed to list terminal extension approvals: %w", err)
	}
	return items, nil
}

// Review 人工/自动审批：仅 pending 可流转（并发下后到者不影响、返回 false）。
// state ∈ approved | rejected；reviewerID 为 nil 表示自动决策（无人工作审），mode 记录实际审批方式。
func (s *ExtensionApprovalStore) Review(id int64, reviewerID *int64, state, mode, note string) (bool, error) {
	now := time.Now()
	res, err := s.db.Exec(
		`UPDATE extension_approvals
		 SET state = ?, approve_mode = ?, reviewer_id = ?, review_note = ?, reviewed_at = ?, updated_at = ?
		 WHERE id = ? AND state = 'pending'`,
		state, mode, reviewerID, note, now, now, id)
	if err != nil {
		return false, fmt.Errorf("failed to review extension approval %d: %w", id, err)
	}
	n, err := res.RowsAffected()
	if err != nil {
		return false, fmt.Errorf("failed to read review result for approval %d: %w", id, err)
	}
	return n > 0, nil
}

// Stats 管理端审批汇总（仪表盘/审批页头部）。
type ApprovalStats struct {
	Pending       int64 `db:"pending" json:"pending"`               // 待审批
	TodayCreated  int64 `db:"today_created" json:"today_created"`   // 今日新增申请
	TodayApproved int64 `db:"today_approved" json:"today_approved"` // 今日通过
	TodayRejected int64 `db:"today_rejected" json:"today_rejected"` // 今日驳回
}

// Stats 计算汇总（今日口径与仪表盘一致：本地零点截断）。
func (s *ExtensionApprovalStore) Stats() (*ApprovalStats, error) {
	today := BeijingDayStart(time.Now())
	st := &ApprovalStats{}
	if err := s.db.Get(&st.Pending, "SELECT COUNT(*) FROM extension_approvals WHERE state = 'pending'"); err != nil {
		return nil, fmt.Errorf("failed to count pending approvals: %w", err)
	}
	if err := s.db.Get(&st.TodayCreated,
		"SELECT COUNT(*) FROM extension_approvals WHERE created_at >= ?", today); err != nil {
		return nil, fmt.Errorf("failed to count today approvals: %w", err)
	}
	if err := s.db.Get(&st.TodayApproved,
		"SELECT COUNT(*) FROM extension_approvals WHERE state = 'approved' AND reviewed_at >= ?", today); err != nil {
		return nil, fmt.Errorf("failed to count today approved approvals: %w", err)
	}
	if err := s.db.Get(&st.TodayRejected,
		"SELECT COUNT(*) FROM extension_approvals WHERE state = 'rejected' AND reviewed_at >= ?", today); err != nil {
		return nil, fmt.Errorf("failed to count today rejected approvals: %w", err)
	}
	return st, nil
}
