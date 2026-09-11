package handler

import (
	"errors"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/crypto"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/service"
	"github.com/llmgate/llmgate/internal/store"
)

// 心跳超过该时长未收到视为离线（展示层动态判定，不落库）
const terminalHeartbeatTimeout = 120 * time.Second

// 集控下发的配置内容上限（1MB），防止误存超大文本
const maxTerminalConfigBytes = 1 << 20

// AdminTerminalHandler handles admin-side agent terminal management.
type AdminTerminalHandler struct {
	terminalStore *store.TerminalStore
	apiKeyService *service.APIKeyService
	agentAuditStore *store.AgentAuditEventStore
}

// NewAdminTerminalHandler creates a new AdminTerminalHandler
func NewAdminTerminalHandler(terminalStore *store.TerminalStore, apiKeyService *service.APIKeyService, agentAuditStore *store.AgentAuditEventStore) *AdminTerminalHandler {
	return &AdminTerminalHandler{
		terminalStore: terminalStore,
		apiKeyService: apiKeyService,
		agentAuditStore: agentAuditStore,
	}
}

// supportedAgentTypes 当前支持的 Agent 类型白名单；扩展新类型时在此追加
// （DB agent_type 无约束，展示层按此表渲染）。
var supportedAgentTypes = map[string]bool{
	"openclaw": true,
}

// ────────────────────────── 管理端 CRUD ──────────────────────────

// ListTerminals handles GET /api/admin/terminals?agent_type=&keyword=&page=&page_size=
func (h *AdminTerminalHandler) ListTerminals(c *gin.Context) {
	page, _ := strconv.Atoi(c.DefaultQuery("page", "1"))
	pageSize, _ := strconv.Atoi(c.DefaultQuery("page_size", "20"))
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}

	terminals, total, err := h.terminalStore.List(page, pageSize, c.Query("agent_type"), strings.TrimSpace(c.Query("keyword")))
	if err != nil {
		slog.Error("failed to list terminals", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to list terminals", "type": "internal_error"},
		})
		return
	}

	for i := range terminals {
		decorateTerminal(&terminals[i])
	}

	c.JSON(http.StatusOK, gin.H{
		"data":      terminals,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	})
}

type createTerminalRequest struct {
	Name        string `json:"name" binding:"required"`
	AgentType   string `json:"agent_type"`
	BoundUserID *int64 `json:"bound_user_id"`
	Description string `json:"description"`
}

// CreateTerminal handles POST /api/admin/terminals
// 创建后立即签发一次性注册码（明文仅本次返回），客户端凭码走 /telemetry/v1/register。
func (h *AdminTerminalHandler) CreateTerminal(c *gin.Context) {
	var req createTerminalRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
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

	agentType := strings.TrimSpace(req.AgentType)
	if agentType == "" {
		agentType = "openclaw"
	}
	if !supportedAgentTypes[agentType] {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "agent_type must be one of: openclaw", "type": "invalid_request_error"},
		})
		return
	}

	existing, err := h.terminalStore.GetByName(name)
	if err != nil {
		slog.Error("failed to check existing terminal", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if existing != nil {
		c.JSON(http.StatusConflict, gin.H{
			"error": gin.H{"message": "terminal name already exists", "type": "invalid_request_error"},
		})
		return
	}

	terminal := &model.AgentTerminal{
		Name:        name,
		AgentType:   agentType,
		BoundUserID: req.BoundUserID,
		Description: req.Description,
		Status:      "pending",
	}
	if err := h.terminalStore.Create(terminal); err != nil {
		slog.Error("failed to create terminal", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to create terminal", "type": "internal_error"},
		})
		return
	}

	code, err := h.issueRegistrationCode(terminal.ID)
	if err != nil {
		slog.Error("failed to issue registration code", "error", err, "terminal_id", terminal.ID)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "terminal created but failed to issue registration code", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusCreated, gin.H{
		"data": gin.H{
			"terminal":          terminal,
			"registration_code": code,
			"hint":              "registration code is shown only once; hand it to the client-side engineer",
		},
	})
}

type updateTerminalRequest struct {
	Name        string  `json:"name"`
	BoundUserID *int64  `json:"bound_user_id"` // null 表示解绑
	Description *string `json:"description"`
}

// UpdateTerminal handles PUT /api/admin/terminals/:id
func (h *AdminTerminalHandler) UpdateTerminal(c *gin.Context) {
	id, ok := h.parseID(c)
	if !ok {
		return
	}

	terminal, err := h.terminalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to get terminal", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if terminal == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "terminal not found", "type": "not_found_error"},
		})
		return
	}

	var req updateTerminalRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	name := strings.TrimSpace(req.Name)
	if name == "" {
		name = terminal.Name
	}
	if name != terminal.Name {
		existing, err := h.terminalStore.GetByName(name)
		if err != nil {
			slog.Error("failed to check existing terminal name", "error", err)
			c.JSON(http.StatusInternalServerError, gin.H{
				"error": gin.H{"message": "internal error", "type": "internal_error"},
			})
			return
		}
		if existing != nil && existing.ID != terminal.ID {
			c.JSON(http.StatusConflict, gin.H{
				"error": gin.H{"message": "terminal name already exists", "type": "invalid_request_error"},
			})
			return
		}
	}

	description := terminal.Description
	if req.Description != nil {
		description = *req.Description
	}

	if err := h.terminalStore.UpdateBasic(id, name, req.BoundUserID, description); err != nil {
		slog.Error("failed to update terminal", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to update terminal", "type": "internal_error"},
		})
		return
	}

	// LLM key 所有者同步：终端绑定用户变更时，其名下已签发 LLM key 跟随改绑。
	// 幂等（重复提交执行相同 update），失败可重试收敛。
	if terminal.LLMAPIKeyID != nil {
		if err := h.apiKeyService.UpdateKeyOwner(*terminal.LLMAPIKeyID, req.BoundUserID); err != nil {
			slog.Error("failed to sync llm api key owner", "error", err, "terminal_id", id, "key_id", *terminal.LLMAPIKeyID)
			c.JSON(http.StatusInternalServerError, gin.H{
				"error": gin.H{"message": "failed to sync api key owner; please retry", "type": "internal_error"},
			})
			return
		}
	}

	updated, err := h.terminalStore.GetByID(id)
	if err != nil || updated == nil {
		slog.Error("failed to reload terminal after update", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to update terminal", "type": "internal_error"},
		})
		return
	}
	decorateTerminal(updated)
	c.JSON(http.StatusOK, updated)
}

// DeleteTerminal handles DELETE /api/admin/terminals/:id
// 级联删除：该终端的审计事件（agent_audit_events）与其 LLM key（硬删除；
// 对话/用量记录由 key 删除流程自动解绑保留，网关审计按保留期清理）；
// 扩展审批与 skill 分发数据由外键 ON DELETE CASCADE 自动清理。
func (h *AdminTerminalHandler) DeleteTerminal(c *gin.Context) {
	id, ok := h.parseID(c)
	if !ok {
		return
	}

	terminal, err := h.terminalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to get terminal", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if terminal == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "terminal not found", "type": "not_found_error"},
		})
		return
	}

	// 1) 先删该终端的审计事件（幂等，失败则中断，重试可自愈）
	if h.agentAuditStore != nil {
		if _, err := h.agentAuditStore.DeleteByTerminal(id); err != nil {
			slog.Error("failed to delete terminal audit events", "error", err, "terminal_id", id)
			c.JSON(http.StatusInternalServerError, gin.H{
				"error": gin.H{"message": "failed to delete terminal audit events", "type": "internal_error"},
			})
			return
		}
	}

	// 2) 解绑并硬删除其 LLM key（幂等：key 不存在视为已删，重试可自愈）
	if terminal.LLMAPIKeyID != nil {
		keyID := *terminal.LLMAPIKeyID
		if err := h.terminalStore.ClearLLMKey(id); err != nil {
			slog.Error("failed to unlink terminal llm key", "error", err, "terminal_id", id, "key_id", keyID)
			c.JSON(http.StatusInternalServerError, gin.H{
				"error": gin.H{"message": "failed to unlink llm api key", "type": "internal_error"},
			})
			return
		}
		if err := h.apiKeyService.DeleteKey(keyID); err != nil {
			if !errors.Is(err, store.ErrAPIKeyNotFound) {
				slog.Error("failed to delete terminal llm key", "error", err, "terminal_id", id, "key_id", keyID)
				c.JSON(http.StatusInternalServerError, gin.H{
					"error": gin.H{"message": "failed to delete llm api key", "type": "internal_error"},
				})
				return
			}
			slog.Warn("terminal llm key already gone", "terminal_id", id, "key_id", keyID)
		}
	}

	// 3) 最后删除终端行（扩展审批/skill 分发由外键自动级联）
	if err := h.terminalStore.Delete(id); err != nil {
		slog.Error("failed to delete terminal", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to delete terminal", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "terminal deleted"})
}
// RegenerateCode handles POST /api/admin/terminals/:id/regenerate-code.
// 重新签发注册码（旧码立即失效）；不吊销当前遥测令牌。
func (h *AdminTerminalHandler) RegenerateCode(c *gin.Context) {
	id, ok := h.parseID(c)
	if !ok {
		return
	}

	terminal, err := h.terminalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to get terminal", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if terminal == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "terminal not found", "type": "not_found_error"},
		})
		return
	}

	code, err := h.issueRegistrationCode(id)
	if err != nil {
		slog.Error("failed to issue registration code", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to regenerate registration code", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"registration_code": code,
			"hint":              "registration code is shown only once; the old code is invalidated",
		},
	})
}

// Revoke handles POST /api/admin/terminals/:id/revoke.
// 吊销遥测令牌并清除注册码，终端回到 pending；重新接入需先重新生成注册码。
// 同时停用终端当前 LLM key 并解除关联（防止被吊销终端继续使用平台 LLM）。
func (h *AdminTerminalHandler) Revoke(c *gin.Context) {
	id, ok := h.parseID(c)
	if !ok {
		return
	}

	terminal, err := h.terminalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to get terminal", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if terminal == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "terminal not found", "type": "not_found_error"},
		})
		return
	}

	// 先停用 LLM key 并解除终端关联（幂等，失败可整体重试）
	if terminal.LLMAPIKeyID != nil {
		if err := h.apiKeyService.DeactivateKey(*terminal.LLMAPIKeyID); err != nil {
			slog.Error("failed to deactivate terminal llm key", "error", err, "terminal_id", id, "key_id", *terminal.LLMAPIKeyID)
			c.JSON(http.StatusInternalServerError, gin.H{
				"error": gin.H{"message": "failed to deactivate llm api key", "type": "internal_error"},
			})
			return
		}
		if err := h.terminalStore.ClearLLMKey(id); err != nil {
			slog.Error("failed to clear terminal llm key link", "error", err, "terminal_id", id)
			c.JSON(http.StatusInternalServerError, gin.H{
				"error": gin.H{"message": "failed to revoke terminal", "type": "internal_error"},
			})
			return
		}
	}

	if err := h.terminalStore.Revoke(id); err != nil {
		slog.Error("failed to revoke terminal", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to revoke terminal", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "terminal revoked"})
}

// ────────────────────────── 集控配置读写 ──────────────────────────

// GetConfig handles GET /api/admin/terminals/:id/config
func (h *AdminTerminalHandler) GetConfig(c *gin.Context) {
	id, ok := h.parseID(c)
	if !ok {
		return
	}

	terminal, err := h.terminalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to get terminal", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if terminal == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "terminal not found", "type": "not_found_error"},
		})
		return
	}

	livePkg := ""
	liveAt := ""
	boundName := ""
	if terminal.BoundUsername != nil {
		boundName = *terminal.BoundUsername
	}
	if r, ok := loadReportedLiveFull(id); ok {
		livePkg = buildFullLiveConfigPkg(boundName, r.Users, r.Resources, r.Live)
		if !r.UpdatedAt.IsZero() {
			liveAt = r.UpdatedAt.UTC().Format("2006-01-02T15:04:05Z")
		}
	}
	if livePkg == "" {
		if r, ok := loadReportedRules(id); ok {
			if lr, ok := loadReportedLiveFull(id); ok {
				livePkg = buildLiveConfigPkg(boundName, r.Users, r.Resources, lr.Live)
			} else {
				livePkg = buildLiveConfigPkg(boundName, r.Users, r.Resources, nil)
			}
			if !r.UpdatedAt.IsZero() {
				liveAt = r.UpdatedAt.UTC().Format("2006-01-02T15:04:05Z")
			}
		}
	}
	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"config":                 terminal.DesiredConfig,
			"config_version":         terminal.ConfigVersion,
			"config_updated_at":      isoTime(terminal.ConfigUpdatedAt),
			"config_applied_version": terminal.ConfigAppliedVersion,
			"config_applied_at":      isoTime(terminal.ConfigAppliedAt),
			"config_pending":         configPending(terminal.ConfigVersion, terminal.ConfigAppliedVersion),
			"live_config":            livePkg,
			"live_updated_at":        liveAt,
			"has_live":               livePkg != "",
		},
	})
}

type updateTerminalConfigRequest struct {
	Config string `json:"config"` // 空串表示清除下发，终端回退本地配置
}

// UpdateConfig handles PUT /api/admin/terminals/:id/config
// 保存后 config_version +1，客户端下次心跳将感知 pending 并拉取。
func (h *AdminTerminalHandler) UpdateConfig(c *gin.Context) {
	id, ok := h.parseID(c)
	if !ok {
		return
	}

	terminal, err := h.terminalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to get terminal", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if terminal == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "terminal not found", "type": "not_found_error"},
		})
		return
	}

	var req updateTerminalConfigRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}
	if len(req.Config) > maxTerminalConfigBytes {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "config too large (max 1MB)", "type": "invalid_request_error"},
		})
		return
	}

	if err := h.terminalStore.UpdateDesiredConfig(id, req.Config); err != nil {
		slog.Error("failed to update terminal config", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to update terminal config", "type": "internal_error"},
		})
		return
	}

	updated, err := h.terminalStore.GetByID(id)
	if err != nil || updated == nil {
		slog.Error("failed to reload terminal config", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to update terminal config", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"config_version":    updated.ConfigVersion,
			"config_updated_at": isoTime(updated.ConfigUpdatedAt),
			"message":           "config saved; client picks it up on next heartbeat",
		},
	})
}

// ────────────────────────── helpers ──────────────────────────

// parseID 解析 :id 路径参数，失败时已写出 400 响应并返回 false
func (h *AdminTerminalHandler) parseID(c *gin.Context) (int64, bool) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid terminal id", "type": "invalid_request_error"},
		})
		return 0, false
	}
	return id, true
}

// issueRegistrationCode 生成并持久化一枚新的注册码（仅存哈希），返回明文
func (h *AdminTerminalHandler) issueRegistrationCode(id int64) (string, error) {
	code, err := crypto.GenerateSecret()
	if err != nil {
		return "", err
	}
	if err := h.terminalStore.UpdateRegistrationCode(id, crypto.HashSecret(code)); err != nil {
		return "", err
	}
	return code, nil
}

// decorateTerminal 填充展示层派生字段：在线状态（active 且最近心跳未超时）
func decorateTerminal(t *model.AgentTerminal) {
	t.Online = t.Status == "active" && t.LastSeenAt != nil && time.Since(*t.LastSeenAt) <= terminalHeartbeatTimeout
}
