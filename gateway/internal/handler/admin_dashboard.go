package handler

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/store"
)

// AdminDashboardHandler 聚合三类统计供"仪表盘"首屏使用：
//   - 网关流量侧（audit_logs 代理请求/token）
//   - 终端态势侧（agent_terminals 数量与累计用量/预警）
//   - 安全事件侧（agent_audit_events 审计事件/拦截/高危）
type AdminDashboardHandler struct {
	auditStore      *store.AuditStore
	terminalStore   *store.TerminalStore
	agentEventStore *store.AgentAuditEventStore
}

// NewAdminDashboardHandler creates a new AdminDashboardHandler
func NewAdminDashboardHandler(auditStore *store.AuditStore, terminalStore *store.TerminalStore, agentEventStore *store.AgentAuditEventStore) *AdminDashboardHandler {
	return &AdminDashboardHandler{
		auditStore:      auditStore,
		terminalStore:   terminalStore,
		agentEventStore: agentEventStore,
	}
}

// dashboardOverview 为聚合响应：沿用网关侧既有字段（total_users 等），
// 新增终端态势（terminal_*）与安全事件（event_*/alerts_*/high_risk_*）。
type dashboardOverview struct {
	store.DashboardStats // total_requests / total_users / total_api_keys / total_providers / requests_today / tokens_today / tokens_total

	TerminalTotal       int64 `json:"terminal_total"`
	TerminalOnline      int64 `json:"terminal_online"`
	TerminalOffline     int64 `json:"terminal_offline"`
	TerminalPending     int64 `json:"terminal_pending"`
	TerminalTokenTotal  int64 `json:"terminal_token_total"`
	TerminalAlertTotal  int64 `json:"terminal_alert_total"`
	EventTotal          int64 `json:"event_total"`
	EventToday          int64 `json:"event_today"`
	AlertsToday         int64 `json:"alerts_today"`    // 今日 action != allow
	HighRiskToday       int64 `json:"high_risk_today"` // 今日 risk_score >= 0.7
}

// GetDashboard handles GET /api/admin/dashboard
func (h *AdminDashboardHandler) GetDashboard(c *gin.Context) {
	out := &dashboardOverview{}

	if h.auditStore != nil {
		stats, err := h.auditStore.GetDashboardStats()
		if err != nil {
			h.internalError(c, err)
			return
		}
		out.DashboardStats = *stats
	}

	if h.terminalStore != nil {
		sum, err := h.terminalStore.Summary(terminalHeartbeatTimeout)
		if err != nil {
			h.internalError(c, err)
			return
		}
		out.TerminalTotal = sum.Total
		out.TerminalOnline = sum.Online
		out.TerminalOffline = sum.Offline
		out.TerminalPending = sum.Pending
		out.TerminalTokenTotal = sum.TokenTotal
		out.TerminalAlertTotal = sum.AlertTotal
	}

	if h.agentEventStore != nil {
		stats, err := h.agentEventStore.Stats()
		if err != nil {
			h.internalError(c, err)
			return
		}
		out.EventTotal = stats.TotalEvents
		out.EventToday = stats.TodayEvents
		out.AlertsToday = stats.AlertsToday
		out.HighRiskToday = stats.HighRiskToday
	}

	c.JSON(http.StatusOK, out)
}

// internalError writes a uniform 500 JSON error response.
func (h *AdminDashboardHandler) internalError(c *gin.Context, err error) {
	c.JSON(http.StatusInternalServerError, gin.H{
		"error": gin.H{"message": "failed to get dashboard stats: " + err.Error(), "type": "internal_error"},
	})
}
