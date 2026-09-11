package handler

import (
	"log/slog"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/auth"
	"github.com/llmgate/llmgate/internal/store"
)

// AdminPasswordHandler handles the signed-in admin's own password change.
// 普通用户自助端点已随 /api/user 移除；改密入口收敛到管理端（admin-only）。
type AdminPasswordHandler struct {
	userStore *store.UserStore
}

// NewAdminPasswordHandler creates a new AdminPasswordHandler
func NewAdminPasswordHandler(userStore *store.UserStore) *AdminPasswordHandler {
	return &AdminPasswordHandler{userStore: userStore}
}

type adminChangePasswordRequest struct {
	CurrentPassword string `json:"current_password" binding:"required"`
	NewPassword     string `json:"new_password" binding:"required,min=6"`
}

// ChangePassword handles PUT /api/admin/change-password
func (h *AdminPasswordHandler) ChangePassword(c *gin.Context) {
	var req adminChangePasswordRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{
				"message": "current_password and new_password (min 6 chars) are required",
				"type":    "invalid_request_error",
			},
		})
		return
	}

	// Get admin ID from JWT context
	userID, exists := c.Get("user_id")
	if !exists {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{"message": "unauthorized", "type": "authentication_error"},
		})
		return
	}

	user, err := h.userStore.GetByID(userID.(int64))
	if err != nil || user == nil {
		slog.Error("failed to get user for password change", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to find user", "type": "internal_error"},
		})
		return
	}

	// Verify current password
	if err := auth.ComparePassword(user.PasswordHash, req.CurrentPassword); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{
				"message": "current password is incorrect",
				"type":    "invalid_request_error",
				"code":    "invalid_current_password",
			},
		})
		return
	}

	// Hash new password
	newHash, err := auth.HashPassword(req.NewPassword)
	if err != nil {
		slog.Error("failed to hash new password", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to process password", "type": "internal_error"},
		})
		return
	}

	// Update password and clear must_change_password flag
	if err := h.userStore.UpdatePassword(user.ID, newHash); err != nil {
		slog.Error("failed to update password", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to update password", "type": "internal_error"},
		})
		return
	}
	if err := h.userStore.SetMustChangePassword(user.ID, false); err != nil {
		slog.Warn("failed to clear must_change_password flag", "error", err)
	}

	c.JSON(http.StatusOK, gin.H{"message": "password changed successfully"})
}
