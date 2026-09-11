package handler

import (
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/store"
)

// AdminProviderHandler handles provider and model CRUD operations
type AdminProviderHandler struct {
	store *store.ProviderStore
	// OnChange reloads the proxy routing table after provider/model mutations.
	// Set by router wiring; nil-safe so unit tests without a router still pass.
	OnChange func()
}

func (h *AdminProviderHandler) notifyChanged() {
	if h.OnChange != nil {
		h.OnChange()
	}
}

// NewAdminProviderHandler creates a new AdminProviderHandler
func NewAdminProviderHandler(store *store.ProviderStore) *AdminProviderHandler {
	return &AdminProviderHandler{store: store}
}

// maskAPIKey returns a masked version of the API key for admin display
func maskAPIKey(key string) string {
	if len(key) <= 8 {
		return "****"
	}
	return key[:4] + "****" + key[len(key)-4:]
}

// providerResponse is the admin-facing provider response with masked API key
type providerResponse struct {
	ID           int64     `json:"id"`
	Name         string    `json:"name"`
	DisplayName  string    `json:"display_name"`
	ProviderType string    `json:"provider_type"`
	APIBaseURL   string    `json:"api_base_url"`
	APIKey       string    `json:"api_key_masked"`
	IsActive     bool      `json:"is_active"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}

func toProviderResponse(p model.Provider) providerResponse {
	return providerResponse{
		ID:           p.ID,
		Name:         p.Name,
		DisplayName:  p.DisplayName,
		ProviderType: p.ProviderType,
		APIBaseURL:   p.APIBaseURL,
		APIKey:       maskAPIKey(p.APIKey),
		IsActive:     p.IsActive,
		CreatedAt:    p.CreatedAt,
		UpdatedAt:    p.UpdatedAt,
	}
}

type createProviderRequest struct {
	Name         string `json:"name" binding:"required"`
	DisplayName  string `json:"display_name" binding:"required"`
	ProviderType string `json:"provider_type" binding:"required"`
	APIBaseURL   string `json:"api_base_url" binding:"required"`
	APIKey       string `json:"api_key" binding:"required"`
}

type updateProviderRequest struct {
	Name         string `json:"name"`
	DisplayName  string `json:"display_name"`
	ProviderType string `json:"provider_type"`
	APIBaseURL   string `json:"api_base_url"`
	APIKey       string `json:"api_key"`
}

type createModelRequest struct {
	ProviderID  int64  `json:"provider_id" binding:"required"`
	ModelID     string `json:"model_id" binding:"required"`
	DisplayName string `json:"display_name"`
}

// ListProviders handles GET /api/admin/providers
func (h *AdminProviderHandler) ListProviders(c *gin.Context) {
	providers, err := h.store.ListProviders()
	if err != nil {
		slog.Error("failed to list providers", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to list providers", "type": "internal_error"},
		})
		return
	}

	// Attach models to each provider
	type providerWithModels struct {
		providerResponse
		Models []model.Model `json:"models"`
	}

	result := make([]providerWithModels, 0, len(providers))
	for _, p := range providers {
		models, err := h.store.ListModelsByProvider(p.ID)
		if err != nil {
			slog.Warn("failed to list models for provider", "provider", p.Name, "error", err)
			models = []model.Model{}
		}
		result = append(result, providerWithModels{
			providerResponse: toProviderResponse(p),
			Models:           models,
		})
	}

	c.JSON(http.StatusOK, result)
}

// CreateProvider handles POST /api/admin/providers
func (h *AdminProviderHandler) CreateProvider(c *gin.Context) {
	var req createProviderRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	provider := &model.Provider{
		Name:         req.Name,
		DisplayName:  req.DisplayName,
		ProviderType: req.ProviderType,
		APIBaseURL:   req.APIBaseURL,
		APIKey:       req.APIKey,
		IsActive:     true,
	}

	if err := h.store.CreateProvider(provider); err != nil {
		slog.Error("failed to create provider", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to create provider", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusCreated, toProviderResponse(*provider))
	h.notifyChanged()
}

// UpdateProvider handles PUT /api/admin/providers/:id
func (h *AdminProviderHandler) UpdateProvider(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid provider id", "type": "invalid_request_error"},
		})
		return
	}

	existing, err := h.store.GetProvider(id)
	if err != nil {
		slog.Error("failed to get provider", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to find provider", "type": "internal_error"},
		})
		return
	}
	if existing == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "provider not found", "type": "not_found_error"},
		})
		return
	}

	var req updateProviderRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	// Apply non-empty fields
	if req.Name != "" {
		existing.Name = req.Name
	}
	if req.DisplayName != "" {
		existing.DisplayName = req.DisplayName
	}
	if req.ProviderType != "" {
		existing.ProviderType = req.ProviderType
	}
	if req.APIBaseURL != "" {
		existing.APIBaseURL = req.APIBaseURL
	}
	if req.APIKey != "" {
		existing.APIKey = req.APIKey
	}

	if err := h.store.UpdateProvider(existing); err != nil {
		slog.Error("failed to update provider", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to update provider", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, toProviderResponse(*existing))
	h.notifyChanged()
}

// DeleteProvider handles DELETE /api/admin/providers/:id (soft delete)
func (h *AdminProviderHandler) DeleteProvider(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid provider id", "type": "invalid_request_error"},
		})
		return
	}

	if err := h.store.DeleteProvider(id); err != nil {
		slog.Error("failed to delete provider", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to delete provider", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "provider deleted"})
	h.notifyChanged()
}

// CreateModel handles POST /api/admin/models
func (h *AdminProviderHandler) CreateModel(c *gin.Context) {
	var req createModelRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	// Verify provider exists
	provider, err := h.store.GetProvider(req.ProviderID)
	if err != nil {
		slog.Error("failed to get provider for model", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to verify provider", "type": "internal_error"},
		})
		return
	}
	if provider == nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "provider not found", "type": "not_found_error"},
		})
		return
	}

	displayName := req.DisplayName
	if displayName == "" {
		displayName = req.ModelID
	}

	m := &model.Model{
		ProviderID:  req.ProviderID,
		ModelID:     req.ModelID,
		DisplayName: displayName,
		IsActive:    true,
	}

	if err := h.store.CreateModel(m); err != nil {
		if errors.Is(err, store.ErrModelExists) {
			c.JSON(http.StatusConflict, gin.H{
				"error": gin.H{"message": "model already exists", "type": "invalid_request_error"},
			})
			return
		}
		slog.Error("failed to create model", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to create model", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusCreated, m)
	h.notifyChanged()
}

// upstreamModelItem 是上游 OpenAI 兼容 /models 接口返回的单个模型。
type upstreamModelItem struct {
	ID string `json:"id"`
}

// ListUpstreamModels handles GET /api/admin/providers/:id/upstream-models
// 用供应商自身配置（API 地址 + Key）实时请求上游 OpenAI 兼容 /models 接口，
// 返回上游可用模型 id 列表，供管理端勾选入库（不落库、不代理计费）。
func (h *AdminProviderHandler) ListUpstreamModels(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid provider id", "type": "invalid_request_error"},
		})
		return
	}

	provider, err := h.store.GetProvider(id)
	if err != nil {
		slog.Error("failed to get provider for upstream models", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to find provider", "type": "internal_error"},
		})
		return
	}
	if provider == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "provider not found", "type": "not_found_error"},
		})
		return
	}

	endpoint := strings.TrimRight(strings.TrimSpace(provider.APIBaseURL), "/") + "/models"
	req, err := http.NewRequest(http.MethodGet, endpoint, nil)
	if err != nil {
		slog.Error("failed to build upstream models request", "error", err, "provider", provider.Name)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to build upstream request", "type": "internal_error"},
		})
		return
	}
	req.Header.Set("Authorization", "Bearer "+provider.APIKey)
	req.Header.Set("Accept", "application/json")

	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		slog.Warn("upstream models request failed", "provider", provider.Name, "endpoint", endpoint, "error", err)
		c.JSON(http.StatusBadGateway, gin.H{
			"error": gin.H{"message": "upstream request failed: " + err.Error(), "type": "upstream_error"},
		})
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		slog.Warn("upstream models returned non-200", "provider", provider.Name, "status", resp.StatusCode, "body", string(body))
		c.JSON(http.StatusBadGateway, gin.H{
			"error": gin.H{"message": "upstream returned status " + resp.Status + ": " + string(body), "type": "upstream_error"},
		})
		return
	}

	var payload struct {
		Data []upstreamModelItem `json:"data"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&payload); err != nil {
		slog.Warn("failed to decode upstream models", "provider", provider.Name, "error", err)
		c.JSON(http.StatusBadGateway, gin.H{
			"error": gin.H{"message": "failed to parse upstream models response", "type": "upstream_error"},
		})
		return
	}

	seen := make(map[string]bool, len(payload.Data))
	ids := make([]string, 0, len(payload.Data))
	for _, m := range payload.Data {
		mid := strings.TrimSpace(m.ID)
		if mid == "" || seen[mid] {
			continue
		}
		seen[mid] = true
		ids = append(ids, mid)
	}

	c.JSON(http.StatusOK, ids)
}

// DeleteModel handles DELETE /api/admin/models/:id (soft delete)
func (h *AdminProviderHandler) DeleteModel(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid model id", "type": "invalid_request_error"},
		})
		return
	}

	if err := h.store.DeleteModel(id); err != nil {
		slog.Error("failed to delete model", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to delete model", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "model deleted"})
	h.notifyChanged()
}
