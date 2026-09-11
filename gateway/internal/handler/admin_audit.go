package handler

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/store"
)

// AdminAuditHandler handles admin audit log endpoints
type AdminAuditHandler struct {
	auditStore *store.AuditStore
}

// NewAdminAuditHandler creates a new AdminAuditHandler
func NewAdminAuditHandler(auditStore *store.AuditStore) *AdminAuditHandler {
	return &AdminAuditHandler{auditStore: auditStore}
}

// GetAuditLogs handles GET /api/admin/audit-logs
func (h *AdminAuditHandler) GetAuditLogs(c *gin.Context) {
	filter := h.parseFilter(c)

	logs, total, err := h.auditStore.Query(filter)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{
				"message": "failed to query audit logs",
				"type":    "internal_error",
			},
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
		"data":      logs,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	})
}

// ExportAuditLogs handles GET /api/admin/audit-logs/export
func (h *AdminAuditHandler) ExportAuditLogs(c *gin.Context) {
	filter := h.parseFilter(c)
	// Override page size to get all results (up to a reasonable limit)
	filter.PageSize = 10000
	filter.Page = 1

	logs, _, err := h.auditStore.Query(filter)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{
				"message": "failed to export audit logs",
				"type":    "internal_error",
			},
		})
		return
	}

	// Build CSV
	var sb strings.Builder
	sb.WriteString("timestamp,user_id,api_key_id,action,model,path,status,prompt_tokens,completion_tokens,latency_ms,ip,user_agent\n")

	for _, log := range logs {
		apiKeyID := ""
		if log.APIKeyID != nil {
			apiKeyID = strconv.FormatInt(*log.APIKeyID, 10)
		}
		modelID := ""
		if log.ModelID != nil {
			modelID = *log.ModelID
		}
		clientIP := ""
		if log.ClientIP != nil {
			clientIP = *log.ClientIP
		}
		userAgent := ""
		if log.UserAgent != nil {
			userAgent = strings.ReplaceAll(*log.UserAgent, ",", " ")
		}

		sb.WriteString(fmt.Sprintf("%s,%d,%s,%s,%s,%s,%d,%d,%d,%d,%s,%s\n",
			log.CreatedAt.Format(time.RFC3339),
			log.UserID,
			apiKeyID,
			log.Action,
			modelID,
			log.RequestPath,
			log.StatusCode,
			log.PromptTokens,
			log.CompletionTokens,
			log.LatencyMs,
			clientIP,
			userAgent,
		))
	}

	filename := fmt.Sprintf("audit_logs_%s.csv", time.Now().Format("20060102_150405"))
	c.Header("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	c.Data(http.StatusOK, "text/csv", []byte(sb.String()))
}

// parseFilter extracts audit filter parameters from the request
func (h *AdminAuditHandler) parseFilter(c *gin.Context) store.AuditFilter {
	filter := store.AuditFilter{}

	if v := c.Query("user_id"); v != "" {
		if id, err := strconv.ParseInt(v, 10, 64); err == nil {
			filter.UserID = &id
		}
	}
	if v := c.Query("api_key_id"); v != "" {
		if id, err := strconv.ParseInt(v, 10, 64); err == nil {
			filter.APIKeyID = &id
		}
	}
	if v := c.Query("action"); v != "" {
		filter.Action = v
	}
	if v := c.Query("model_id"); v != "" {
		filter.ModelID = v
	}
	if v := c.Query("start_time"); v != "" {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			filter.StartTime = &t
		}
	}
	if v := c.Query("end_time"); v != "" {
		if t, err := time.Parse(time.RFC3339, v); err == nil {
			filter.EndTime = &t
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
