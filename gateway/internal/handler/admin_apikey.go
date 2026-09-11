package handler

import (
	"errors"
	"log/slog"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/service"
	"github.com/llmgate/llmgate/internal/store"
)

// AdminAPIKeyHandler handles admin API key management
type AdminAPIKeyHandler struct {
	apiKeyService *service.APIKeyService
	terminalStore *store.TerminalStore
}

// NewAdminAPIKeyHandler creates a new AdminAPIKeyHandler
func NewAdminAPIKeyHandler(apiKeyService *service.APIKeyService, terminalStore *store.TerminalStore) *AdminAPIKeyHandler {
	return &AdminAPIKeyHandler{
		apiKeyService: apiKeyService,
		terminalStore: terminalStore,
	}
}

// ListAPIKeys handles GET /api/admin/api-keys - list all keys
func (h *AdminAPIKeyHandler) ListAPIKeys(c *gin.Context) {
	keys, err := h.apiKeyService.ListAllKeys()
	if err != nil {
		slog.Error("failed to list api keys", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to list api keys", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"data": keys,
	})
}

// apiKeyCreateRequest carries fields for an admin-created (manual) key.
// user_id is optional; when omitted the key is unowned. Empty permissions
// => all models. Manual keys are not linked to any terminal.
type apiKeyCreateRequest struct {
	Name        string   `json:"name" binding:"required"`
	Permissions []string `json:"permissions"`
	UserID      *int64   `json:"user_id"`
}

// CreateAPIKey handles POST /api/admin/api-keys - manually create a key.
// The raw key plaintext is returned exactly once in this response.
func (h *AdminAPIKeyHandler) CreateAPIKey(c *gin.Context) {
	var req apiKeyCreateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "name is required", "type": "invalid_request_error"},
		})
		return
	}
	name := strings.TrimSpace(req.Name)
	if name == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "name is required", "type": "invalid_request_error"},
		})
		return
	}

	rawKey, key, err := h.apiKeyService.CreateManualKey(name, req.UserID, req.Permissions)
	if err != nil {
		if errors.Is(err, service.ErrUserNotFound) || errors.Is(err, service.ErrUserInactive) {
			c.JSON(http.StatusBadRequest, gin.H{
				"error": gin.H{"message": err.Error(), "type": "invalid_request_error"},
			})
			return
		}
		slog.Error("failed to create api key", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to create api key", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"data": gin.H{
			"id":          key.ID,
			"name":        key.Name,
			"api_key":     rawKey,
			"key_prefix":  key.KeyPrefix,
			"user_id":     key.UserID,
			"permissions": key.Permissions,
		},
		"hint": "api key is shown only once; store it in the client config",
	})
}

// apiKeyUpdateRequest carries editable metadata of a key. It is a full
// update of name + model whitelist (empty permissions => all models).
type apiKeyUpdateRequest struct {
	Name        string   `json:"name" binding:"required"`
	Permissions []string `json:"permissions"`
}

// UpdateAPIKey handles PUT /api/admin/api-keys/:id - edit name / model whitelist
func (h *AdminAPIKeyHandler) UpdateAPIKey(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid api key id", "type": "invalid_request_error"},
		})
		return
	}

	var req apiKeyUpdateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "name is required", "type": "invalid_request_error"},
		})
		return
	}

	if err := h.apiKeyService.UpdateKey(id, req.Name, req.Permissions); err != nil {
		if errors.Is(err, store.ErrAPIKeyNotFound) {
			c.JSON(http.StatusNotFound, gin.H{
				"error": gin.H{"message": "api key not found", "type": "not_found_error"},
			})
			return
		}
		slog.Error("failed to update api key", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to update api key", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "api key updated"})
}

// DeleteAPIKey handles DELETE /api/admin/api-keys/:id - permanently remove a
// key row (deactivated or active). The key is unlinked from any issuing
// terminal first, otherwise the FK on agent_terminals.llm_api_key_id would
// reject the delete; the terminal then needs a fresh register to get a new key.
func (h *AdminAPIKeyHandler) DeleteAPIKey(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid api key id", "type": "invalid_request_error"},
		})
		return
	}

	if h.terminalStore != nil {
		if err := h.terminalStore.ClearLLMKeyByKeyID(id); err != nil {
			slog.Warn("failed to unlink terminal llm key", "key_id", id, "error", err)
		}
	}

	if err := h.apiKeyService.DeleteKey(id); err != nil {
		if errors.Is(err, store.ErrAPIKeyNotFound) {
			c.JSON(http.StatusNotFound, gin.H{
				"error": gin.H{"message": "api key not found", "type": "not_found_error"},
			})
			return
		}
		slog.Error("failed to delete api key", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to delete api key", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "api key deleted"})
}

// DeactivateAPIKey handles POST /api/admin/api-keys/:id/deactivate - soft
// disable a key (kept in history, can be deleted later)
func (h *AdminAPIKeyHandler) DeactivateAPIKey(c *gin.Context) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid api key id", "type": "invalid_request_error"},
		})
		return
	}

	if err := h.apiKeyService.DeactivateKey(id); err != nil {
		if errors.Is(err, store.ErrAPIKeyNotFound) {
			c.JSON(http.StatusNotFound, gin.H{
				"error": gin.H{"message": "api key not found", "type": "not_found_error"},
			})
			return
		}
		slog.Error("failed to deactivate api key", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to deactivate api key", "type": "internal_error"},
		})
		return
	}

	// 若该 key 正被某终端引用为当前 LLM key，解除关联（key 停用后不可再使用）
	if h.terminalStore != nil {
		if err := h.terminalStore.ClearLLMKeyByKeyID(id); err != nil {
			slog.Warn("failed to unlink terminal llm key", "key_id", id, "error", err)
		}
	}

	c.JSON(http.StatusOK, gin.H{"message": "api key deactivated"})
}
