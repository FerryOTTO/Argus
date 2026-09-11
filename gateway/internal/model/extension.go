package model

import "time"

// 安装审批类型
const (
	ApprovalKindSkill = "skill" // 安装新 skill
	ApprovalKindMCP   = "mcp"   // 接入新 MCP 服务
)

// 审批状态机
const (
	ApprovalStatePending  = "pending"  // 待审批
	ApprovalStateApproved = "approved" // 放行：客户端可执行安装
	ApprovalStateRejected = "rejected" // 驳回：客户端不得安装
)

// 审批方式
const (
	ApprovalModeManual = "manual" // 人工审批（当前唯一开放方式）
	ApprovalModeAuto   = "auto"   // 自动决策器（接口已预留，见 service.ApprovalDecider）
)

// Skill 安装回执状态
const (
	SkillApplyOK     = "ok"     // 安装成功
	SkillApplyFailed = "failed" // 安装失败（服务端保留待重试标记）
)

// ExtensionApproval 为终端侧"安装新 skill / 接入新 MCP"的审批单。
// 终端经遥测上报创建（state=pending），管理员（或预留的自动决策器）审批后
// 置 approved/rejected，客户端轮询自己的审批单取得结果。
type ExtensionApproval struct {
	ID           int64  `db:"id" json:"id"`
	TerminalID   int64  `db:"terminal_id" json:"terminal_id"`
	TerminalName string `db:"terminal_name" json:"terminal_name"`
	Kind         string `db:"kind" json:"kind"`
	Name         string `db:"name" json:"name"`
	Source       string `db:"source" json:"source"`
	// Payload 为申请明细 JSON 原文（skill: 内容摘要/来源标识；mcp: server 定义），展示端自行解析
	Payload     string     `db:"payload" json:"payload"`
	Reason      string     `db:"reason" json:"reason"`
	State       string     `db:"state" json:"state"`
	ApproveMode string     `db:"approve_mode" json:"approve_mode"`
	ReviewerID  *int64     `db:"reviewer_id" json:"reviewer_id,omitempty"`
	ReviewNote  string     `db:"review_note" json:"review_note"`
	ReviewedAt  *time.Time `db:"reviewed_at" json:"reviewed_at,omitempty"`
	CreatedAt   time.Time  `db:"created_at" json:"created_at"`
	UpdatedAt   time.Time  `db:"updated_at" json:"updated_at"`
}

// SkillPackage 为 Skill 分发包：zip 原样存储，分发时整体下传（不透明内容，客户端解压安装）。
// ZipData 不出现在 JSON（列表/详情仅给摘要与大小）。
type SkillPackage struct {
	ID          int64     `db:"id" json:"id"`
	Name        string    `db:"name" json:"name"`
	Description string    `db:"description" json:"description"`
	Version     int64     `db:"version" json:"version"`
	ZipName     string    `db:"zip_name" json:"zip_name"`
	ZipSize     int64     `db:"zip_size" json:"zip_size"`
	ZipData     []byte    `db:"zip_data" json:"-"`
	Preview     string    `db:"preview" json:"preview"`
	CreatedBy   *int64    `db:"created_by" json:"created_by,omitempty"`
	CreatedAt   time.Time `db:"created_at" json:"created_at"`
	UpdatedAt   time.Time `db:"updated_at" json:"updated_at"`
}

// SkillPackageItem 为列表行：附当前分配的终端数与最新安装回执概要。
type SkillPackageItem struct {
	SkillPackage
	AssignedCount int64 `db:"assigned_count" json:"assigned_count"`
}

// SkillApplyment 为终端对某包最新版本的安装回执（每终端每包一条）。
type SkillApplyment struct {
	PackageID      int64     `db:"package_id" json:"package_id"`
	TerminalID     int64     `db:"terminal_id" json:"terminal_id"`
	PackageVersion int64     `db:"package_version" json:"package_version"`
	Status         string    `db:"status" json:"status"`
	Message        string    `db:"message" json:"message"`
	AppliedAt      time.Time `db:"applied_at" json:"applied_at"`
}

// DefaultSkillPackages 为"新终端自动分发"设置（settings 键，JSON 存储）。
type DefaultSkillPackages struct {
	Enabled    bool    `json:"enabled"`
	PackageIDs []int64 `json:"package_ids"`
}
