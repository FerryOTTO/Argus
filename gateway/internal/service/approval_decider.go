package service

import (
	"context"
	"time"
)

// ApprovalRequest 为提交给自动审批决策器的申请快照（服务端已校验字段）。
type ApprovalRequest struct {
	TerminalID   int64
	TerminalName string
	Kind         string // model.ApprovalKindSkill | ApprovalKindMCP
	Name         string
	Source       string
	Payload      string // 申请明细 JSON 原文
	Reason       string
	RequestedAt  time.Time
}

// ApprovalDecision 为自动决策结果；Note 落入审批单 review_note 供审计留存。
type ApprovalDecision struct {
	Approved bool
	Note     string
}

// ApprovalDecider 为 skill/MCP 安装审批的自动决策器接口（v1 预留，初期仅人工审批）。
//
// 启用方式（两步，均在代码层完成）：
//  1. 实现本接口（如按终端白名单/包来源/风险名单决策，或对接外部风控服务）；
//  2. 组装时把实现注入审批/遥测 handler，并把系统设置 extension_approval_mode
//     切到 auto（store.SettingApprovalMode）。
//
// 模式为 auto 但未注入任何决策器时：新申请保持 pending 并记警告日志（兜底人工），
// 避免"静默自动拒绝/放行"造成安全或可用性事故。
type ApprovalDecider interface {
	// Name 返回策略名（展示与日志用）。
	Name() string
	// Decide 同步决策；返回 error 表示本次无法决策（申请保持 pending，等待人工）。
	Decide(ctx context.Context, req ApprovalRequest) (ApprovalDecision, error)
}
