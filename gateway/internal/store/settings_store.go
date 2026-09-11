package store

import (
	"database/sql"
	"fmt"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
)

// Settings keys（与前端系统设置页/注册签发逻辑共享的约定键名）
const (
	SettingEnterpriseName = "enterprise_name" // 企业名称（注册响应/登录页展示）
	SettingSystemBaseURL  = "system_base_url" // 系统根地址（组合生成 LLM base_url 下发）
	SettingOpenModels     = "open_models"     // 开放模型白名单，JSON 数组；空=全部模型

	// 扩展治理（skill/MCP 安装审批 + Skill 分发，见 model/extension.go）
	SettingApprovalMode         = "extension_approval_mode"          // 审批方式: manual（人工）| auto（自动决策器，预留）；缺省 manual
	SettingDefaultSkillPackages = "extension_default_skill_packages" // 新终端自动分发设置，JSON（model.DefaultSkillPackages）
)

// SettingsStore handles the system settings key/value table.
type SettingsStore struct {
	db *sqlx.DB
}

// NewSettingsStore creates a new SettingsStore
func NewSettingsStore(db *sqlx.DB) *SettingsStore {
	return &SettingsStore{db: db}
}

// Get reads a single setting (found=false when the key was never set)
func (s *SettingsStore) Get(key string) (string, bool, error) {
	var value string
	err := s.db.Get(&value, "SELECT value FROM settings WHERE key = ?", key)
	if err == sql.ErrNoRows {
		return "", false, nil
	}
	if err != nil {
		return "", false, fmt.Errorf("failed to get setting %q: %w", key, err)
	}
	return value, true, nil
}

// GetAll returns every configured key/value pair
func (s *SettingsStore) GetAll() (map[string]string, error) {
	type row struct {
		Key   string `db:"key"`
		Value string `db:"value"`
	}
	var rows []row
	if err := s.db.Select(&rows, "SELECT key, value FROM settings"); err != nil {
		return nil, fmt.Errorf("failed to list settings: %w", err)
	}
	out := make(map[string]string, len(rows))
	for _, r := range rows {
		out[r.Key] = r.Value
	}
	return out, nil
}

// Set upserts a single setting
func (s *SettingsStore) Set(key, value string) error {
	query := `
		INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
		ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
	`
	if _, err := ExecWithRetry(s.db, query, key, value); err != nil {
		return fmt.Errorf("failed to set setting %q: %w", key, err)
	}
	return nil
}

// ApprovalMode 返回扩展安装审批方式（manual | auto），未配置时缺省 manual（人工）。
// auto 为自动决策器预留：当前无内置策略，未注册决策器时申请保持 pending 待人工处理。
func (s *SettingsStore) ApprovalMode() (string, error) {
	v, _, err := s.Get(SettingApprovalMode)
	if err != nil {
		return "", err
	}
	if v != model.ApprovalModeAuto {
		return model.ApprovalModeManual, nil
	}
	return model.ApprovalModeAuto, nil
}
