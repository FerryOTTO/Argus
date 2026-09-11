package handler

import (
	"log/slog"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/auth"
)

// AdminSSOHandler handles OAuth provider CRUD operations
type AdminSSOHandler struct {
	oauth2Store *auth.OAuth2ConfigStore
}

// NewAdminSSOHandler creates a new AdminSSOHandler
func NewAdminSSOHandler(oauth2Store *auth.OAuth2ConfigStore) *AdminSSOHandler {
	return &AdminSSOHandler{oauth2Store: oauth2Store}
}

type createSSOProviderRequest struct {
	Name         string `json:"name" binding:"required"`
	ProviderType string `json:"provider_type" binding:"required"`
	ClientID     string `json:"client_id" binding:"required"`
	ClientSecret string `json:"client_secret" binding:"required"`
	AuthURL      string `json:"auth_url" binding:"required"`
	TokenURL     string `json:"token_url" binding:"required"`
	UserInfoURL  string `json:"userinfo_url" binding:"required"`
	Scopes       string `json:"scopes"`
	AutoCreate   bool   `json:"auto_create_user"`
	DefaultRole  string `json:"default_role"`
}

type updateSSOProviderRequest struct {
	Name         string `json:"name"`
	ProviderType string `json:"provider_type"`
	ClientID     string `json:"client_id"`
	ClientSecret string `json:"client_secret"`
	AuthURL      string `json:"auth_url"`
	TokenURL     string `json:"token_url"`
	UserInfoURL  string `json:"userinfo_url"`
	Scopes       string `json:"scopes"`
	AutoCreate   *bool  `json:"auto_create_user"`
	DefaultRole  string `json:"default_role"`
}

type toggleSSOProviderRequest struct {
	IsActive bool `json:"is_active"`
}

// ListProviders handles GET /api/admin/oauth-providers
func (h *AdminSSOHandler) ListProviders(c *gin.Context) {
	providers, err := h.oauth2Store.List()
	if err != nil {
		slog.Error("failed to list oauth providers", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to list oauth providers", "type": "internal_error"},
		})
		return
	}

	if providers == nil {
		providers = []auth.OAuth2Config{}
	}

	c.JSON(http.StatusOK, providers)
}

// CreateProvider handles POST /api/admin/oauth-providers
func (h *AdminSSOHandler) CreateProvider(c *gin.Context) {
	var req createSSOProviderRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	scopes := req.Scopes
	if scopes == "" {
		scopes = "openid profile email"
	}

	defaultRole := req.DefaultRole
	if defaultRole == "" {
		defaultRole = "user"
	}

	cfg := &auth.OAuth2Config{
		Name:         req.Name,
		ProviderType: req.ProviderType,
		ClientID:     req.ClientID,
		ClientSecret: req.ClientSecret,
		AuthURL:      req.AuthURL,
		TokenURL:     req.TokenURL,
		UserInfoURL:  req.UserInfoURL,
		Scopes:       scopes,
		AutoCreate:   req.AutoCreate,
		DefaultRole:  defaultRole,
		IsActive:     true,
	}

	if err := h.oauth2Store.Create(cfg); err != nil {
		slog.Error("failed to create oauth provider", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to create oauth provider", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusCreated, cfg)
}

// UpdateProvider handles PUT /api/admin/oauth-providers/:id
func (h *AdminSSOHandler) UpdateProvider(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid provider id", "type": "invalid_request_error"},
		})
		return
	}

	existing, err := h.oauth2Store.Get(id)
	if err != nil {
		slog.Error("failed to get oauth provider", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to find oauth provider", "type": "internal_error"},
		})
		return
	}
	if existing == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "oauth provider not found", "type": "not_found_error"},
		})
		return
	}

	var req updateSSOProviderRequest
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
	if req.ProviderType != "" {
		existing.ProviderType = req.ProviderType
	}
	if req.ClientID != "" {
		existing.ClientID = req.ClientID
	}
	if req.ClientSecret != "" {
		existing.ClientSecret = req.ClientSecret
	}
	if req.AuthURL != "" {
		existing.AuthURL = req.AuthURL
	}
	if req.TokenURL != "" {
		existing.TokenURL = req.TokenURL
	}
	if req.UserInfoURL != "" {
		existing.UserInfoURL = req.UserInfoURL
	}
	if req.Scopes != "" {
		existing.Scopes = req.Scopes
	}
	if req.AutoCreate != nil {
		existing.AutoCreate = *req.AutoCreate
	}
	if req.DefaultRole != "" {
		existing.DefaultRole = req.DefaultRole
	}

	if err := h.oauth2Store.Update(existing); err != nil {
		slog.Error("failed to update oauth provider", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to update oauth provider", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, existing)
}

// DeleteProvider handles DELETE /api/admin/oauth-providers/:id
func (h *AdminSSOHandler) DeleteProvider(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid provider id", "type": "invalid_request_error"},
		})
		return
	}

	if err := h.oauth2Store.Delete(id); err != nil {
		slog.Error("failed to delete oauth provider", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to delete oauth provider", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "oauth provider deleted"})
}

// ToggleProvider handles PUT /api/admin/oauth-providers/:id/toggle
func (h *AdminSSOHandler) ToggleProvider(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid provider id", "type": "invalid_request_error"},
		})
		return
	}

	var req toggleSSOProviderRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	if err := h.oauth2Store.Toggle(id, req.IsActive); err != nil {
		slog.Error("failed to toggle oauth provider", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to toggle oauth provider", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "oauth provider toggled", "is_active": req.IsActive})
}
