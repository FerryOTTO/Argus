package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/store"
)

// AdminSettingsHandler 管理系统设置（企业名称 / 系统根地址 / 开放模型白名单）。
// 这些设置驱动注册响应的企业信息与 LLM base_url 组合，以及新签发 LLM key 的模型范围。
type AdminSettingsHandler struct {
	settingsStore *store.SettingsStore
}

// NewAdminSettingsHandler creates a new AdminSettingsHandler
func NewAdminSettingsHandler(settingsStore *store.SettingsStore) *AdminSettingsHandler {
	return &AdminSettingsHandler{settingsStore: settingsStore}
}

// settingsPayload 与前端「系统设置」页一一对应。
// open_models 空数组 = 全模型开放（注册签发 ["*"]）。
type settingsPayload struct {
	EnterpriseName string   `json:"enterprise_name"`
	SystemBaseURL  string   `json:"system_base_url"`
	OpenModels     []string `json:"open_models"`
}

// GetSettings handles GET /api/admin/settings
func (h *AdminSettingsHandler) GetSettings(c *gin.Context) {
	payload := settingsPayload{OpenModels: []string{}}

	if v, found, err := h.settingsStore.Get(store.SettingEnterpriseName); err != nil {
		slog.Error("failed to read enterprise name setting", "error", err)
		h.internalError(c)
		return
	} else if found {
		payload.EnterpriseName = v
	}

	if v, found, err := h.settingsStore.Get(store.SettingSystemBaseURL); err != nil {
		slog.Error("failed to read system base url setting", "error", err)
		h.internalError(c)
		return
	} else if found {
		payload.SystemBaseURL = v
	}

	if raw, found, err := h.settingsStore.Get(store.SettingOpenModels); err != nil {
		slog.Error("failed to read open models setting", "error", err)
		h.internalError(c)
		return
	} else if found && raw != "" {
		var models []string
		if err := json.Unmarshal([]byte(raw), &models); err == nil && models != nil {
			payload.OpenModels = models
		}
	}

	c.JSON(http.StatusOK, gin.H{"data": payload})
}

// UpdateSettings handles PUT /api/admin/settings（三个设置全量覆盖）
func (h *AdminSettingsHandler) UpdateSettings(c *gin.Context) {
	var req settingsPayload
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	// 系统根地址须为合法 http(s) URL（允许留空，留空时注册响应 base_url 为空串）
	root := strings.TrimSpace(req.SystemBaseURL)
	if root != "" && !strings.HasPrefix(root, "http://") && !strings.HasPrefix(root, "https://") {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "system_base_url must start with http:// or https://", "type": "invalid_request_error"},
		})
		return
	}

	openModels := req.OpenModels
	if openModels == nil {
		openModels = []string{}
	}
	modelsJSON, err := json.Marshal(openModels)
	if err != nil {
		slog.Error("failed to encode open models", "error", err)
		h.internalError(c)
		return
	}

	values := map[string]string{
		store.SettingEnterpriseName: strings.TrimSpace(req.EnterpriseName),
		store.SettingSystemBaseURL:  root,
		store.SettingOpenModels:     string(modelsJSON),
	}
	for key, value := range values {
		if err := h.settingsStore.Set(key, value); err != nil {
			slog.Error("failed to save setting", "key", key, "error", err)
			h.internalError(c)
			return
		}
	}

	c.JSON(http.StatusOK, gin.H{"message": "settings updated"})
}

func (h *AdminSettingsHandler) internalError(c *gin.Context) {
	c.JSON(http.StatusInternalServerError, gin.H{
		"error": gin.H{"message": "internal error", "type": "internal_error"},
	})
}
