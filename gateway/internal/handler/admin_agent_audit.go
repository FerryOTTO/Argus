package handler

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/store"
)

// AdminAgentAuditHandler 处理"审计日志 · 终端审计"板块的查询端点（Argus 上报事件）。
type AdminAgentAuditHandler struct {
	eventStore *store.AgentAuditEventStore
}

// NewAdminAgentAuditHandler creates a new AdminAgentAuditHandler
func NewAdminAgentAuditHandler(eventStore *store.AgentAuditEventStore) *AdminAgentAuditHandler {
	return &AdminAgentAuditHandler{eventStore: eventStore}
}

// ListAgentAuditEvents handles GET /api/admin/audit-events
func (h *AdminAgentAuditHandler) ListAgentAuditEvents(c *gin.Context) {
	filter := h.parseFilter(c)

	events, total, err := h.eventStore.Query(filter)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to query agent audit events", "type": "internal_error"},
		})
		return
	}

	page := filter.Page
	if page < 1 {
		page = 1
	}
	pageSize := filter.PageSize
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}

	c.JSON(http.StatusOK, gin.H{
		"data":      events,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	})
}

// AgentAuditStats handles GET /api/admin/audit-events/stats
func (h *AdminAgentAuditHandler) AgentAuditStats(c *gin.Context) {
	stats, err := h.eventStore.Stats()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to get agent audit stats", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, stats)
}

// TerminalAuditStats handles GET /api/admin/audit-events/terminal-stats
//（每台终端的审计聚合，供"以终端为单位"的审计视图；在线状态口径同终端管理）
func (h *AdminAgentAuditHandler) TerminalAuditStats(c *gin.Context) {
	stats, err := h.eventStore.TerminalStats()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to get terminal audit stats", "type": "internal_error"},
		})
		return
	}
	for i := range stats {
		t := &stats[i]
		t.Online = t.Status == "active" && t.LastSeenAt != nil && time.Since(*t.LastSeenAt) <= terminalHeartbeatTimeout
	}
	c.JSON(http.StatusOK, gin.H{"data": stats})
}

// ExportAgentAuditEvents handles GET /api/admin/audit-events/export（CSV，含当前筛选条件）
func (h *AdminAgentAuditHandler) ExportAgentAuditEvents(c *gin.Context) {
	filter := h.parseFilter(c)
	filter.Page = 1
	filter.PageSize = 10000

	events, _, err := h.eventStore.Query(filter)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to export agent audit events", "type": "internal_error"},
		})
		return
	}

	var sb strings.Builder
	sb.WriteString("event_time,terminal_name,stage,source_module,action,risk_score,user_id,session_id,trace_id,event_id,reason\n")
	for _, ev := range events {
		fmt.Fprintf(&sb, "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n",
			csvCell(ev.EventTime), csvCell(ev.TerminalName), csvCell(ev.Stage), csvCell(ev.SourceModule),
			csvCell(ev.Action), strconv.FormatFloat(ev.RiskScore, 'f', -1, 64),
			csvCell(ev.UserID), csvCell(ev.SessionID), csvCell(ev.TraceID), csvCell(ev.EventID),
			csvCell(ev.Reason),
		)
	}

	filename := fmt.Sprintf("agent_audit_events_%s.csv", time.Now().Format("20060102_150405"))
	c.Header("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	c.Data(http.StatusOK, "text/csv", []byte(sb.String()))
}

// csvCell 将单元格内容转义为 CSV 引号字段
func csvCell(s string) string {
	return `"` + strings.ReplaceAll(s, `"`, `""`) + `"`
}

// parseFilter 解析"终端审计"列表的筛选参数
func (h *AdminAgentAuditHandler) parseFilter(c *gin.Context) store.AgentAuditFilter {
	filter := store.AgentAuditFilter{}

	if v := c.Query("terminal_id"); v != "" {
		if id, err := strconv.ParseInt(v, 10, 64); err == nil {
			filter.TerminalID = &id
		}
	}
	if v := c.Query("stage"); v != "" {
		filter.Stage = v
	}
	if v := c.Query("action"); v != "" {
		filter.Action = v
	}
	if v := c.Query("source_module"); v != "" {
		filter.SourceModule = v
	}
	if v := c.Query("risk_min"); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil && f >= 0 && f <= 1 {
			filter.RiskMin = &f
		}
	}
	if v := strings.TrimSpace(c.Query("q")); v != "" {
		filter.Q = v
	}
	if v := c.Query("start_time"); v != "" {
		if s, ok := normalizeEventTimeQuery(v); ok {
			filter.StartTime = s
		}
	}
	if v := c.Query("end_time"); v != "" {
		if s, ok := normalizeEventTimeQuery(v); ok {
			filter.EndTime = s
		}
	}
	if v := c.Query("page"); v != "" {
		if p, err := strconv.Atoi(v); err == nil {
			filter.Page = p
		}
	}
	if v := c.Query("page_size"); v != "" {
		if ps, err := strconv.Atoi(v); err == nil {
			filter.PageSize = ps
		}
	}

	return filter
}

// normalizeEventTimeQuery 将管理端传入的时间筛选归一化为 UTC RFC3339 秒级定宽文本。
// 接受 RFC3339；无时区输入按服务器本地时区解释（控制台日期组件即输出该形态）。
func normalizeEventTimeQuery(raw string) (string, bool) {
	s := strings.TrimSpace(raw)
	if s == "" {
		return "", false
	}
	for _, layout := range []string{time.RFC3339Nano, time.RFC3339} {
		if t, err := time.Parse(layout, s); err == nil {
			return t.UTC().Format(model.AuditEventTimeLayout), true
		}
	}
	for _, layout := range []string{"2006-01-02T15:04:05", "2006-01-02 15:04:05"} {
		if t, err := time.ParseInLocation(layout, s, time.Local); err == nil {
			return t.UTC().Format(model.AuditEventTimeLayout), true
		}
	}
	return "", false
}
