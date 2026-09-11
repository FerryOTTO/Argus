package store

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
)

// SkillPackageStore 负责 Skill 分发包、终端分配与安装回执（skill_packages /
// skill_package_assignments / skill_package_applyments）及"新终端自动分发"设置。
type SkillPackageStore struct {
	db       *sqlx.DB
	settings *SettingsStore
}

// NewSkillPackageStore creates a new SkillPackageStore
func NewSkillPackageStore(db *sqlx.DB, settings *SettingsStore) *SkillPackageStore {
	return &SkillPackageStore{db: db, settings: settings}
}

const skillPackageColumns = `
	id, name, description, version, zip_name, zip_size, zip_data, preview,
	created_by, created_at, updated_at`

// SaveContent 新增或覆盖包内容：同名已存在则 version+1 并整体替换 zip/描述/摘要
// （分配关系保留，终端靠版本差感知重拉）；返回 isNew 与落库后的版本号。
func (s *SkillPackageStore) SaveContent(pkg *model.SkillPackage) (bool, error) {
	DBWriteMu.Lock()
	defer DBWriteMu.Unlock()

	var existing struct {
		ID      int64
		Version int64
	}
	err := s.db.Get(&existing, "SELECT id, version FROM skill_packages WHERE name = ?", pkg.Name)
	if err == nil {
		// 同名覆盖：版本 +1，zip/描述/摘要整体替换（created_at 保留首建时间）
		pkg.ID = existing.ID
		pkg.Version = existing.Version + 1
		_, err = s.db.Exec(`UPDATE skill_packages
			SET version = ?, description = ?, zip_name = ?, zip_size = ?, zip_data = ?,
			    preview = ?, updated_at = ?
			WHERE id = ?`,
			pkg.Version, pkg.Description, pkg.ZipName, pkg.ZipSize, pkg.ZipData,
			pkg.Preview, time.Now(), pkg.ID)
		if err != nil {
			return false, fmt.Errorf("failed to update skill package %q: %w", pkg.Name, err)
		}
		return false, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return false, fmt.Errorf("failed to check skill package %q: %w", pkg.Name, err)
	}

	// 新包：version 从 1 起
	now := time.Now()
	pkg.Version = 1
	pkg.CreatedAt = now
	pkg.UpdatedAt = now
	res, err := s.db.NamedExec(`INSERT INTO skill_packages
		(name, description, version, zip_name, zip_size, zip_data, preview, created_by, created_at, updated_at)
		VALUES (:name, :description, :version, :zip_name, :zip_size, :zip_data, :preview,
		        :created_by, :created_at, :updated_at)`, pkg)
	if err != nil {
		return false, fmt.Errorf("failed to insert skill package %q: %w", pkg.Name, err)
	}
	id, err := res.LastInsertId()
	if err != nil {
		return false, fmt.Errorf("failed to read skill package id: %w", err)
	}
	pkg.ID = id
	return true, nil
}

// GetByID 完整读取单个包（含 zip 原数据，供终端拉取/详情）。
func (s *SkillPackageStore) GetByID(id int64) (*model.SkillPackage, error) {
	var p model.SkillPackage
	if err := s.db.Get(&p, "SELECT "+skillPackageColumns+" FROM skill_packages WHERE id = ?", id); err != nil {
		return nil, fmt.Errorf("failed to get skill package %d: %w", id, err)
	}
	return &p, nil
}

// List 分页列表：附当前分配终端数（不含 zip 明细）。
func (s *SkillPackageStore) List(page, pageSize int, keyword string) ([]model.SkillPackageItem, int64, error) {
	cond := "1=1"
	args := []any{}
	if kw := strings.TrimSpace(keyword); kw != "" {
		cond = "p.name LIKE ?"
		args = append(args, "%"+kw+"%")
	}
	var total int64
	if err := s.db.Get(&total, "SELECT COUNT(*) FROM skill_packages p WHERE "+cond, args...); err != nil {
		return nil, 0, fmt.Errorf("failed to count skill packages: %w", err)
	}
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	args = append(args, pageSize, (page-1)*pageSize)

	items := []model.SkillPackageItem{}
	// 列表列不含 zip_data：分别列出需要的列（避免大 BLOB 传输）
	err := s.db.Select(&items, `SELECT p.id, p.name, p.description, p.version, p.zip_name, p.zip_size,
		p.preview, p.created_by, p.created_at, p.updated_at,
		(SELECT COUNT(*) FROM skill_package_assignments a WHERE a.package_id = p.id) AS assigned_count
		FROM skill_packages p WHERE `+cond+` ORDER BY p.id DESC LIMIT ? OFFSET ?`, args...)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to list skill packages: %w", err)
	}
	return items, total, nil
}

// UpdateDescription 更新包描述（展示文案，不触发版本变化）。
func (s *SkillPackageStore) UpdateDescription(id int64, description string) error {
	DBWriteMu.Lock()
	defer DBWriteMu.Unlock()
	if _, err := s.db.Exec(
		"UPDATE skill_packages SET description = ?, updated_at = ? WHERE id = ?",
		description, time.Now(), id); err != nil {
		return fmt.Errorf("failed to update skill package %d: %w", id, err)
	}
	return nil
}

// Delete 删除包（分配与回执由外键级联清理）。
func (s *SkillPackageStore) Delete(id int64) error {
	DBWriteMu.Lock()
	defer DBWriteMu.Unlock()
	if _, err := s.db.Exec("DELETE FROM skill_packages WHERE id = ?", id); err != nil {
		return fmt.Errorf("failed to delete skill package %d: %w", id, err)
	}
	return nil
}

// ListAssignedTerminalIDs 返回当前分配该包的终端 id 集合。
func (s *SkillPackageStore) ListAssignedTerminalIDs(packageID int64) ([]int64, error) {
	ids := []int64{}
	if err := s.db.Select(&ids,
		"SELECT terminal_id FROM skill_package_assignments WHERE package_id = ? ORDER BY terminal_id", packageID); err != nil {
		return nil, fmt.Errorf("failed to list skill package assignments: %w", err)
	}
	return ids, nil
}

// IsAssigned 判断某包是否已分配给某终端（遥测回执前校验用）。
func (s *SkillPackageStore) IsAssigned(packageID, terminalID int64) (bool, error) {
	var n int64
	if err := s.db.Get(&n,
		"SELECT COUNT(*) FROM skill_package_assignments WHERE package_id = ? AND terminal_id = ?",
		packageID, terminalID); err != nil {
		return false, fmt.Errorf("failed to check skill package assignment: %w", err)
	}
	return n > 0, nil
}

// ReplaceAssignments 全量覆盖某包的分配集合（管理员保存即生效；空集合 = 解除全部分发）。
func (s *SkillPackageStore) ReplaceAssignments(packageID int64, terminalIDs []int64) error {
	DBWriteMu.Lock()
	defer DBWriteMu.Unlock()

	tx, err := s.db.Beginx()
	if err != nil {
		return fmt.Errorf("failed to begin assignment replace: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if _, err := tx.Exec("DELETE FROM skill_package_assignments WHERE package_id = ?", packageID); err != nil {
		return fmt.Errorf("failed to clear assignments: %w", err)
	}
	now := time.Now()
	for _, tid := range terminalIDs {
		if _, err := tx.Exec(
			"INSERT INTO skill_package_assignments (package_id, terminal_id, created_at) VALUES (?, ?, ?)",
			packageID, tid, now); err != nil {
			return fmt.Errorf("failed to insert assignment (terminal %d): %w", tid, err)
		}
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("failed to commit assignment replace: %w", err)
	}
	return nil
}

// AssignToTerminals 为指定终端批量分配多个包（新终端注册时自动分发；幂等，已有分配跳过）。
func (s *SkillPackageStore) AssignToTerminals(terminalID int64, packageIDs []int64) error {
	if len(packageIDs) == 0 {
		return nil
	}
	DBWriteMu.Lock()
	defer DBWriteMu.Unlock()

	now := time.Now()
	for _, pid := range packageIDs {
		if _, err := s.db.Exec(
			`INSERT OR IGNORE INTO skill_package_assignments (package_id, terminal_id, created_at) VALUES (?, ?, ?)`,
			pid, terminalID, now); err != nil {
			return fmt.Errorf("failed to auto assign skill package %d: %w", pid, err)
		}
	}
	return nil
}

// PackagesForTerminal 返回分配给某终端的全部包（zip 原样，客户端解压安装）。
func (s *SkillPackageStore) PackagesForTerminal(terminalID int64) ([]model.SkillPackage, error) {
	items := []model.SkillPackage{}
	if err := s.db.Select(&items, `SELECT p.id, p.name, p.description, p.version, p.zip_name, p.zip_size,
		p.zip_data, p.preview, p.created_by, p.created_at, p.updated_at
		FROM skill_packages p
		JOIN skill_package_assignments a ON a.package_id = p.id
		WHERE a.terminal_id = ? ORDER BY p.name`, terminalID); err != nil {
		return nil, fmt.Errorf("failed to list packages for terminal: %w", err)
	}
	return items, nil
}

// ApplymentsForTerminal 返回某终端全部安装回执（供分发拉取合并 applied_version）。
func (s *SkillPackageStore) ApplymentsForTerminal(terminalID int64) ([]model.SkillApplyment, error) {
	items := []model.SkillApplyment{}
	if err := s.db.Select(&items,
		"SELECT package_id, terminal_id, package_version, status, message, applied_at FROM skill_package_applyments WHERE terminal_id = ?",
		terminalID); err != nil {
		return nil, fmt.Errorf("failed to list applyments for terminal: %w", err)
	}
	return items, nil
}

// ConfirmApply 落/更新安装回执（同一终端同一包仅保留最新一条）。
func (s *SkillPackageStore) ConfirmApply(ap *model.SkillApplyment) error {
	DBWriteMu.Lock()
	defer DBWriteMu.Unlock()
	ap.AppliedAt = time.Now()
	if _, err := s.db.Exec(`INSERT INTO skill_package_applyments
		(package_id, terminal_id, package_version, status, message, applied_at) VALUES (?, ?, ?, ?, ?, ?)
		ON CONFLICT(package_id, terminal_id) DO UPDATE SET
			package_version = excluded.package_version, status = excluded.status,
			message = excluded.message, applied_at = excluded.applied_at`,
		ap.PackageID, ap.TerminalID, ap.PackageVersion, ap.Status, ap.Message, ap.AppliedAt); err != nil {
		return fmt.Errorf("failed to confirm skill applyment: %w", err)
	}
	return nil
}

// PendingCount 统计终端尚待同步的包数（未回执 / 版本落后 / 上次安装失败需重试），
// 供心跳响应的 skills_pending 标志使用。
func (s *SkillPackageStore) PendingCount(terminalID int64) (int64, error) {
	var n int64
	err := s.db.Get(&n, `SELECT COUNT(*)
		FROM skill_package_assignments a
		JOIN skill_packages p ON p.id = a.package_id
		LEFT JOIN skill_package_applyments ap ON ap.package_id = a.package_id AND ap.terminal_id = a.terminal_id
		WHERE a.terminal_id = ?
		  AND (ap.package_id IS NULL OR ap.package_version < p.version OR ap.status = 'failed')`, terminalID)
	if err != nil {
		return 0, fmt.Errorf("failed to count pending skill packages: %w", err)
	}
	return n, nil
}

// DefaultPackages 读取"新终端自动分发"设置（未配置 = 关闭）。
func (s *SkillPackageStore) DefaultPackages() (*model.DefaultSkillPackages, error) {
	d := &model.DefaultSkillPackages{Enabled: false, PackageIDs: []int64{}}
	raw, found, err := s.settings.Get(SettingDefaultSkillPackages)
	if err != nil {
		return nil, err
	}
	if !found || strings.TrimSpace(raw) == "" {
		return d, nil
	}
	if err := json.Unmarshal([]byte(raw), d); err != nil {
		return nil, fmt.Errorf("failed to parse default skill packages setting: %w", err)
	}
	if d.PackageIDs == nil {
		d.PackageIDs = []int64{}
	}
	return d, nil
}

// SetDefaultPackages 保存"新终端自动分发"设置（调用方负责校验包存在）。
func (s *SkillPackageStore) SetDefaultPackages(d *model.DefaultSkillPackages) error {
	if d.PackageIDs == nil {
		d.PackageIDs = []int64{}
	}
	raw, err := json.Marshal(d)
	if err != nil {
		return fmt.Errorf("failed to encode default skill packages: %w", err)
	}
	return s.settings.Set(SettingDefaultSkillPackages, string(raw))
}
