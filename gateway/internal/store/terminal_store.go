package store

import (
	"database/sql"
	"fmt"
	"strings"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
)

// TerminalStore handles agent terminal database operations.
// 凭据（注册码/遥测令牌）只存 SHA-256 哈希，明文仅由 handler 生成时返回一次。
type TerminalStore struct {
	db *sqlx.DB
}

// NewTerminalStore creates a new TerminalStore
func NewTerminalStore(db *sqlx.DB) *TerminalStore {
	return &TerminalStore{db: db}
}

// terminalColumns 为列表/单查复用列清单（JOIN users 带出绑定用户名）。
const terminalColumns = `
	SELECT t.id, t.name, t.agent_type, t.bound_user_id, u.username AS bound_username,
	       t.description, t.status, t.hostname, t.os_info, t.agent_version,
	       t.argus_version, t.last_seen_at, t.token_usage_total, t.alert_count_total,
	       t.desired_config, t.config_version, t.config_updated_at,
	       t.config_applied_version, t.config_applied_at,
	       t.registration_code_hash, t.telemetry_token_hash, t.llm_api_key_id,
	       t.created_at, t.updated_at
	FROM agent_terminals t
	LEFT JOIN users u ON u.id = t.bound_user_id`

// List returns a paginated list of terminals, optionally filtered by agent type
// or keyword (matches name / hostname), ordered by creation time descending.
func (s *TerminalStore) List(page, pageSize int, agentType, keyword string) ([]model.AgentTerminal, int, error) {
	var conditions []string
	var args []interface{}

	if agentType != "" {
		conditions = append(conditions, "t.agent_type = ?")
		args = append(args, agentType)
	}
	if keyword != "" {
		conditions = append(conditions, "(t.name LIKE ? OR t.hostname LIKE ?)")
		kw := "%" + keyword + "%"
		args = append(args, kw, kw)
	}

	where := ""
	if len(conditions) > 0 {
		where = " WHERE " + strings.Join(conditions, " AND ")
	}

	var total int
	if err := s.db.Get(&total, "SELECT COUNT(*) FROM agent_terminals t"+where, args...); err != nil {
		return nil, 0, fmt.Errorf("failed to count terminals: %w", err)
	}

	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	offset := (page - 1) * pageSize

	var terminals []model.AgentTerminal
	query := terminalColumns + where + " ORDER BY t.id DESC LIMIT ? OFFSET ?"
	queryArgs := append(args, pageSize, offset)
	if err := s.db.Select(&terminals, query, queryArgs...); err != nil {
		return nil, 0, fmt.Errorf("failed to list terminals: %w", err)
	}
	return terminals, total, nil
}

// GetByID retrieves a terminal by ID (nil when not found)
func (s *TerminalStore) GetByID(id int64) (*model.AgentTerminal, error) {
	var t model.AgentTerminal
	query := terminalColumns + " WHERE t.id = ?"
	if err := s.db.Get(&t, query, id); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get terminal by id: %w", err)
	}
	return &t, nil
}

// GetByName retrieves a terminal by display name (nil when not found)
func (s *TerminalStore) GetByName(name string) (*model.AgentTerminal, error) {
	var t model.AgentTerminal
	query := terminalColumns + " WHERE t.name = ?"
	if err := s.db.Get(&t, query, name); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get terminal by name: %w", err)
	}
	return &t, nil
}

// Create inserts a new pending terminal and returns it with the auto-generated ID
func (s *TerminalStore) Create(t *model.AgentTerminal) error {
	now := time.Now()
	t.CreatedAt = now
	t.UpdatedAt = now

	query := `
		INSERT INTO agent_terminals (name, agent_type, bound_user_id, description, status, created_at, updated_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)
	`
	result, err := ExecWithRetry(s.db, query, t.Name, t.AgentType, t.BoundUserID, t.Description, t.Status, now, now)
	if err != nil {
		return fmt.Errorf("failed to create terminal: %w", err)
	}
	id, err := result.LastInsertId()
	if err != nil {
		return fmt.Errorf("failed to get last insert id: %w", err)
	}
	t.ID = id
	return nil
}

// UpdateBasic updates editable admin fields (name / bound user / description)
func (s *TerminalStore) UpdateBasic(id int64, name string, boundUserID *int64, description string) error {
	query := `UPDATE agent_terminals SET name = ?, bound_user_id = ?, description = ?, updated_at = ? WHERE id = ?`
	if _, err := ExecWithRetry(s.db, query, name, boundUserID, description, time.Now(), id); err != nil {
		return fmt.Errorf("failed to update terminal: %w", err)
	}
	return nil
}

// Delete removes a terminal and its credentials/config
func (s *TerminalStore) Delete(id int64) error {
	if _, err := ExecWithRetry(s.db, `DELETE FROM agent_terminals WHERE id = ?`, id); err != nil {
		return fmt.Errorf("failed to delete terminal: %w", err)
	}
	return nil
}

// LinkLLMKey records the platform-issued LLM API key currently in use by a terminal
func (s *TerminalStore) LinkLLMKey(id, keyID int64) error {
	query := `UPDATE agent_terminals SET llm_api_key_id = ?, updated_at = ? WHERE id = ?`
	if _, err := ExecWithRetry(s.db, query, keyID, time.Now(), id); err != nil {
		return fmt.Errorf("failed to link llm api key: %w", err)
	}
	return nil
}

// ClearLLMKey unlinks the terminal's LLM API key (used on revoke)
func (s *TerminalStore) ClearLLMKey(id int64) error {
	query := `UPDATE agent_terminals SET llm_api_key_id = NULL, updated_at = ? WHERE id = ?`
	if _, err := ExecWithRetry(s.db, query, time.Now(), id); err != nil {
		return fmt.Errorf("failed to clear llm api key: %w", err)
	}
	return nil
}

// ClearLLMKeyByKeyID unlinks any terminal referencing the given key
// (used when an admin deactivates a key from the key-management view)
func (s *TerminalStore) ClearLLMKeyByKeyID(keyID int64) error {
	query := `UPDATE agent_terminals SET llm_api_key_id = NULL, updated_at = ? WHERE llm_api_key_id = ?`
	if _, err := ExecWithRetry(s.db, query, time.Now(), keyID); err != nil {
		return fmt.Errorf("failed to clear llm api key by key id: %w", err)
	}
	return nil
}

// UpdateRegistrationCode stores the SHA-256 hash of a new registration code
func (s *TerminalStore) UpdateRegistrationCode(id int64, codeHash string) error {
	query := `UPDATE agent_terminals SET registration_code_hash = ?, updated_at = ? WHERE id = ?`
	if _, err := ExecWithRetry(s.db, query, codeHash, time.Now(), id); err != nil {
		return fmt.Errorf("failed to update registration code: %w", err)
	}
	return nil
}

// GetByRegistrationCodeHash finds a terminal by its registration code hash
func (s *TerminalStore) GetByRegistrationCodeHash(hash string) (*model.AgentTerminal, error) {
	var t model.AgentTerminal
	query := terminalColumns + " WHERE t.registration_code_hash = ?"
	if err := s.db.Get(&t, query, hash); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get terminal by registration code: %w", err)
	}
	return &t, nil
}

// Activate binds a fresh telemetry token hash and records the registration
// (hostname/versions come from the client), setting status to active.
func (s *TerminalStore) Activate(id int64, tokenHash, hostname, osInfo, agentVersion, argusVersion string) error {
	now := time.Now()
	query := `
		UPDATE agent_terminals
		SET status = 'active', registration_code_hash = '', telemetry_token_hash = ?, hostname = ?, os_info = ?,
		    agent_version = ?, argus_version = ?, last_seen_at = ?, updated_at = ?
		WHERE id = ?
	`
	if _, err := ExecWithRetry(s.db, query, tokenHash, hostname, osInfo, agentVersion, argusVersion, now, now, id); err != nil {
		return fmt.Errorf("failed to activate terminal: %w", err)
	}
	return nil
}

// FindActiveByTokenHash finds an active terminal by its telemetry token hash
func (s *TerminalStore) FindActiveByTokenHash(hash string) (*model.AgentTerminal, error) {
	var t model.AgentTerminal
	query := terminalColumns + " WHERE t.telemetry_token_hash = ? AND t.status = 'active'"
	if err := s.db.Get(&t, query, hash); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get terminal by token: %w", err)
	}
	return &t, nil
}

// Revoke clears both credentials and puts the terminal back to pending.
// A terminal can only rejoin after the admin regenerates a registration code.
func (s *TerminalStore) Revoke(id int64) error {
	query := `
		UPDATE agent_terminals
		SET status = 'pending', registration_code_hash = '', telemetry_token_hash = '', updated_at = ?
		WHERE id = ?
	`
	if _, err := ExecWithRetry(s.db, query, time.Now(), id); err != nil {
		return fmt.Errorf("failed to revoke terminal: %w", err)
	}
	return nil
}

// TouchHeartbeat refreshes runtime metadata and last_seen_at on heartbeat.
// It never overwrites hostname/versions with empty strings (partial payloads).
func (s *TerminalStore) TouchHeartbeat(id int64, hostname, osInfo, agentVersion, argusVersion string) error {
	var sets []string
	var args []interface{}

	if hostname != "" {
		sets = append(sets, "hostname = ?")
		args = append(args, hostname)
	}
	if osInfo != "" {
		sets = append(sets, "os_info = ?")
		args = append(args, osInfo)
	}
	if agentVersion != "" {
		sets = append(sets, "agent_version = ?")
		args = append(args, agentVersion)
	}
	if argusVersion != "" {
		sets = append(sets, "argus_version = ?")
		args = append(args, argusVersion)
	}
	now := time.Now()
	sets = append(sets, "last_seen_at = ?", "updated_at = ?")
	args = append(args, now, now, id)

	query := "UPDATE agent_terminals SET " + strings.Join(sets, ", ") + " WHERE id = ?"
	if _, err := ExecWithRetry(s.db, query, args...); err != nil {
		return fmt.Errorf("failed to touch terminal heartbeat: %w", err)
	}
	return nil
}

// ApplyReportDelta accumulates usage/alert deltas reported by the client
func (s *TerminalStore) ApplyReportDelta(id int64, tokenUsageDelta, alertDelta int64) error {
	query := `
		UPDATE agent_terminals
		SET token_usage_total = token_usage_total + ?,
		    alert_count_total = alert_count_total + ?,
		    updated_at = ?
		WHERE id = ?
	`
	if _, err := ExecWithRetry(s.db, query, tokenUsageDelta, alertDelta, time.Now(), id); err != nil {
		return fmt.Errorf("failed to apply terminal report: %w", err)
	}
	return nil
}

// UpdateDesiredConfig stores the admin-authored argus config and bumps
// the config version. An empty config clears the pending config.
func (s *TerminalStore) UpdateDesiredConfig(id int64, config string) error {
	query := `
		UPDATE agent_terminals
		SET desired_config = ?, config_version = config_version + 1,
		    config_updated_at = ?, updated_at = ?
		WHERE id = ?
	`
	now := time.Now()
	if _, err := ExecWithRetry(s.db, query, config, now, now, id); err != nil {
		return fmt.Errorf("failed to update terminal config: %w", err)
	}
	return nil
}

// ConfirmConfigApplied records that the client applied config_version
func (s *TerminalStore) ConfirmConfigApplied(id int64, version int64) error {
	now := time.Now()
	query := `
		UPDATE agent_terminals
		SET config_applied_version = ?, config_applied_at = ?, updated_at = ?
		WHERE id = ?
	`
	if _, err := ExecWithRetry(s.db, query, version, now, now, id); err != nil {
		return fmt.Errorf("failed to confirm terminal config applied: %w", err)
	}
	return nil
}

// TerminalSummary 是全量终端的概览聚合（仪表盘）：数量口径与终端管理一致——
// active 且最近心跳在窗口内为在线；active 但心跳超时为离线；其余为待接入。
type TerminalSummary struct {
	Total      int64 `json:"total" db:"total"`
	Online     int64 `json:"online" db:"online"`
	Offline    int64 `json:"offline" db:"offline"`
	Pending    int64 `json:"pending" db:"pending"`
	TokenTotal int64 `json:"token_total" db:"token_total"`
	AlertTotal int64 `json:"alert_total" db:"alert_total"`
}

// Summary aggregates terminal counts and cumulative usage/alert totals.
func (s *TerminalStore) Summary(onlineWindow time.Duration) (*TerminalSummary, error) {
	cutoff := time.Now().Add(-onlineWindow)
	var sum TerminalSummary
	query := `
		SELECT COUNT(*) AS total,
		       COALESCE(SUM(CASE WHEN status = 'active' AND last_seen_at >= ? THEN 1 ELSE 0 END), 0) AS online,
		       COALESCE(SUM(CASE WHEN status = 'active' AND (last_seen_at IS NULL OR last_seen_at < ?) THEN 1 ELSE 0 END), 0) AS offline,
		       COALESCE(SUM(CASE WHEN status != 'active' THEN 1 ELSE 0 END), 0) AS pending,
		       COALESCE(SUM(token_usage_total), 0) AS token_total,
		       COALESCE(SUM(alert_count_total), 0) AS alert_total
		FROM agent_terminals
	`
	if err := s.db.Get(&sum, query, cutoff, cutoff); err != nil {
		return nil, fmt.Errorf("failed to aggregate terminal summary: %w", err)
	}
	return &sum, nil
}

// ListOptions 返回全部终端的轻量选项（id/名称/状态/hostname），按名称升序，
// 供 Skill 分发等全量多选场景使用（不分页）。
func (s *TerminalStore) ListOptions() ([]model.TerminalOption, error) {
	opts := []model.TerminalOption{}
	if err := s.db.Select(&opts,
		"SELECT id, name, agent_type, status, hostname FROM agent_terminals ORDER BY name"); err != nil {
		return nil, fmt.Errorf("failed to list terminal options: %w", err)
	}
	return opts, nil
}
