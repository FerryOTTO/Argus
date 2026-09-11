package handler

import (
	"log/slog"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/auth"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/store"
)

// AdminUserHandler handles user CRUD operations
type AdminUserHandler struct {
	store *store.UserStore
}

// NewAdminUserHandler creates a new AdminUserHandler
func NewAdminUserHandler(store *store.UserStore) *AdminUserHandler {
	return &AdminUserHandler{store: store}
}

type createUserRequest struct {
	Username      string `json:"username" binding:"required"`
	Password      string `json:"password" binding:"required"`
	Email         string `json:"email"`
	Role          string `json:"role" binding:"required"`
	SecurityLevel string `json:"security_level"`
	Specials      string `json:"specials"`
}

type updateUserRequest struct {
	Email         *string `json:"email"`
	Role          string  `json:"role"`
	IsActive      *bool   `json:"is_active"`
	SecurityLevel *string `json:"security_level"`
	Specials      *string `json:"specials"`
}

type resetPasswordRequest struct {
	Password string `json:"password" binding:"required"`
}

// ListUsers handles GET /api/admin/users?page=1&page_size=20
func (h *AdminUserHandler) ListUsers(c *gin.Context) {
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	pageSize, _ := strconv.Atoi(c.DefaultQuery("page_size", "20"))

	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}

	users, total, err := h.store.List(page, pageSize)
	if err != nil {
		slog.Error("failed to list users", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to list users", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"data":      users,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	})
}

// CreateUser handles POST /api/admin/users
func (h *AdminUserHandler) CreateUser(c *gin.Context) {
	var req createUserRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	// Validate role
	if req.Role != "admin" && req.Role != "user" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "role must be 'admin' or 'user'", "type": "invalid_request_error"},
		})
		return
	}

	// Check if username already exists
	existing, err := h.store.GetByUsername(req.Username)
	if err != nil {
		slog.Error("failed to check existing user", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if existing != nil {
		c.JSON(http.StatusConflict, gin.H{
			"error": gin.H{"message": "username already exists", "type": "invalid_request_error"},
		})
		return
	}

	hash, err := auth.HashPassword(req.Password)
	if err != nil {
		slog.Error("failed to hash password", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to create user", "type": "internal_error"},
		})
		return
	}

	var email *string
	if req.Email != "" {
		email = &req.Email
	}

	user := &model.User{
		Username:     req.Username,
		PasswordHash: hash,
		Email:        email,
		Role:         req.Role,
		IsActive:     true,
	}

	// security_level 默认 internal；非法值回落 internal，与 access_control 对齐
	user.SecurityLevel = normalizeSecurityLevel(req.SecurityLevel, "internal")
	user.Specials = strings.TrimSpace(req.Specials)

	if err := h.store.Create(user); err != nil {
		slog.Error("failed to create user", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to create user", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusCreated, user)
}

// UpdateUser handles PUT /api/admin/users/:id
func (h *AdminUserHandler) UpdateUser(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid user id", "type": "invalid_request_error"},
		})
		return
	}

	existing, err := h.store.GetByID(id)
	if err != nil {
		slog.Error("failed to get user", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to find user", "type": "internal_error"},
		})
		return
	}
	if existing == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "user not found", "type": "not_found_error"},
		})
		return
	}

	var req updateUserRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	if req.Role != "" {
		if req.Role != "admin" && req.Role != "user" {
			c.JSON(http.StatusBadRequest, gin.H{
				"error": gin.H{"message": "role must be 'admin' or 'user'", "type": "invalid_request_error"},
			})
			return
		}
		existing.Role = req.Role
	}
	if req.Email != nil {
		existing.Email = req.Email
	}
	if req.IsActive != nil {
		existing.IsActive = *req.IsActive
	}
	if req.SecurityLevel != nil {
		existing.SecurityLevel = normalizeSecurityLevel(*req.SecurityLevel, existing.SecurityLevel)
	}
	if req.Specials != nil {
		existing.Specials = strings.TrimSpace(*req.Specials)
	}

	if err := h.store.Update(existing); err != nil {
		slog.Error("failed to update user", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to update user", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, existing)
}

// normalizeSecurityLevel 把输入收敛到 public/internal/secret/top_secret，非法回落 fallback
func normalizeSecurityLevel(raw, fallback string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "public", "1", "a":
		return "public"
	case "internal", "2", "b", "":
		if strings.TrimSpace(raw) == "" {
			return fallback
		}
		return "internal"
	case "secret", "3", "c":
		return "secret"
	case "top_secret", "topsecret", "4", "d":
		return "top_secret"
	default:
		return fallback
	}
}

// DeleteUser handles DELETE /api/admin/users/:id (soft delete)
func (h *AdminUserHandler) DeleteUser(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid user id", "type": "invalid_request_error"},
		})
		return
	}

	if err := h.store.Delete(id); err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "user not found") {
			c.JSON(http.StatusNotFound, gin.H{
				"error": gin.H{"message": "user not found", "type": "not_found_error"},
			})
			return
		}
		slog.Error("failed to delete user", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to delete user", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "user deleted"})
}

// ResetPassword handles PUT /api/admin/users/:id/password
func (h *AdminUserHandler) ResetPassword(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid user id", "type": "invalid_request_error"},
		})
		return
	}

	var req resetPasswordRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "password is required", "type": "invalid_request_error"},
		})
		return
	}

	hash, err := auth.HashPassword(req.Password)
	if err != nil {
		slog.Error("failed to hash password", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to reset password", "type": "internal_error"},
		})
		return
	}

	if err := h.store.UpdatePassword(id, hash); err != nil {
		slog.Error("failed to update password", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to reset password", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "password updated"})
}
