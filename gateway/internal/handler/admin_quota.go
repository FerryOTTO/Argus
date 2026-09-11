package handler

import (
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/store"
)

// AdminQuotaHandler handles admin quota management
type AdminQuotaHandler struct {
	quotaStore *store.QuotaStore
}

// NewAdminQuotaHandler creates a new AdminQuotaHandler
func NewAdminQuotaHandler(quotaStore *store.QuotaStore) *AdminQuotaHandler {
	return &AdminQuotaHandler{quotaStore: quotaStore}
}

type createQuotaRequest struct {
	UserID     int64   `json:"user_id" binding:"required"`
	ModelID    string  `json:"model_id"`
	QuotaType  string  `json:"quota_type" binding:"required"`
	LimitValue float64 `json:"limit_value" binding:"required"`
}

// ListQuotas handles GET /api/admin/quotas?user_id=X
func (h *AdminQuotaHandler) ListQuotas(c *gin.Context) {
	userIDStr := c.Query("user_id")
	if userIDStr == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "user_id is required", "type": "invalid_request_error"},
		})
		return
	}

	userID, err := strconv.ParseInt(userIDStr, 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid user_id", "type": "invalid_request_error"},
		})
		return
	}

	quotas, err := h.quotaStore.GetByUserID(userID)
	if err != nil {
		slog.Error("failed to list quotas", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to list quotas", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"data": quotas,
	})
}

// CreateQuota handles POST /api/admin/quotas
func (h *AdminQuotaHandler) CreateQuota(c *gin.Context) {
	var req createQuotaRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	// Validate quota_type
	validTypes := map[string]bool{"rpm": true, "rpd": true, "tpm": true, "tpd": true}
	if !validTypes[req.QuotaType] {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "quota_type must be one of: rpm, rpd, tpm, tpd", "type": "invalid_request_error"},
		})
		return
	}

	modelID := req.ModelID
	if modelID == "" {
		modelID = "*"
	}

	quota := &model.Quota{
		UserID:     req.UserID,
		ModelID:    modelID,
		QuotaType:  req.QuotaType,
		LimitValue: req.LimitValue,
		IsActive:   true,
	}

	if err := h.quotaStore.Create(quota); err != nil {
		slog.Error("failed to create quota", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to create quota", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusCreated, quota)
}

// DeleteQuota handles DELETE /api/admin/quotas/:id
func (h *AdminQuotaHandler) DeleteQuota(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid quota id", "type": "invalid_request_error"},
		})
		return
	}

	if err := h.quotaStore.Delete(id); err != nil {
		slog.Error("failed to delete quota", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to delete quota", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "quota deleted"})
}

// GetUsage handles GET /api/admin/usage?user_id=X&since=2024-01-01
func (h *AdminQuotaHandler) GetUsage(c *gin.Context) {
	userIDStr := c.Query("user_id")
	if userIDStr == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "user_id is required", "type": "invalid_request_error"},
		})
		return
	}

	userID, err := strconv.ParseInt(userIDStr, 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid user_id", "type": "invalid_request_error"},
		})
		return
	}

	sinceStr := c.DefaultQuery("since", time.Now().AddDate(0, -1, 0).Format("2006-01-02"))
	since, err := time.Parse("2006-01-02", sinceStr)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid since date format, use YYYY-MM-DD", "type": "invalid_request_error"},
		})
		return
	}

	records, err := h.quotaStore.GetUsageByUserID(userID, since)
	if err != nil {
		slog.Error("failed to get usage", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to get usage", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"data": records,
	})
}
