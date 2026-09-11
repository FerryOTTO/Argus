package handler

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/store"
)

// ConversationHandler handles admin conversation log endpoints
type ConversationHandler struct {
	convStore *store.ConversationStore
}

// NewConversationHandler creates a new ConversationHandler
func NewConversationHandler(convStore *store.ConversationStore) *ConversationHandler {
	return &ConversationHandler{convStore: convStore}
}

// ListConversations handles GET /api/admin/conversations
func (h *ConversationHandler) ListConversations(c *gin.Context) {
	filter := h.parseFilter(c)

	logs, total, err := h.convStore.Query(filter)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{
				"message": "failed to query conversation logs",
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

// GetConversationDetail handles GET /api/admin/conversations/:id
func (h *ConversationHandler) GetConversationDetail(c *gin.Context) {
	idStr := c.Param("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{
				"message": "invalid conversation id",
				"type":    "bad_request",
			},
		})
		return
	}

	log, err := h.convStore.GetDetail(id)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{
				"message": "failed to get conversation detail",
				"type":    "internal_error",
			},
		})
		return
	}

	c.JSON(http.StatusOK, log)
}

// parseFilter extracts conversation filter parameters from the request
func (h *ConversationHandler) parseFilter(c *gin.Context) store.ConversationFilter {
	filter := store.ConversationFilter{}

	if v := c.Query("user_id"); v != "" {
		if id, err := strconv.ParseInt(v, 10, 64); err == nil {
			filter.UserID = id
		}
	}
	if v := c.Query("model_id"); v != "" {
		filter.ModelID = v
	}
	if v := c.Query("start_time"); v != "" {
		filter.StartTime = v
	}
	if v := c.Query("end_time"); v != "" {
		filter.EndTime = v
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
