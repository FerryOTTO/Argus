package handler

import (
	"encoding/base64"
	"encoding/json"
	"log/slog"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/service"
)

// 扩展治理遥测契约（详见 CLIENT.md）：
//   - POST /telemetry/v1/extensions/requests  —— 上报 skill/MCP 安装申请（等待审批）
//   - GET  /telemetry/v1/extensions/requests  —— 轮询自己的审批单（含结果）
//   - GET  /telemetry/v1/skills               —— 拉取分配给本终端的 skill 包
//   - POST /telemetry/v1/skills/applied       —— 安装结果回执

const (
	maxApprovalNameLen   = 128      // 申请名长度上限
	maxApprovalSourceLen = 256      // 来源说明长度上限
	maxApprovalPayload   = 64 << 10 // 申请明细 JSON ≤ 64KB
	maxApprovalReasonLen = 2000     // 申请理由长度上限
	maxSkillApplyMsgLen  = 1024     // 安装回执消息长度上限
)

// SubmitExtensionRequest handles POST /telemetry/v1/extensions/requests
// 客户端在"安装新 skill / 接入新 MCP"前上报申请；审批方式由系统设置决定：
// manual（默认）→ 待管理员审批；auto（预留）→ 调自动决策器（未注册决策器则保持 pending）。
func (h *TelemetryHandler) SubmitExtensionRequest(c *gin.Context) {
	if h.approvalStore == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "extension governance not enabled", "type": "not_found_error"},
		})
		return
	}
	var req struct {
		Kind    string          `json:"kind" binding:"required"`
		Name    string          `json:"name" binding:"required"`
		Source  string          `json:"source"`
		Payload json.RawMessage `json:"payload"`
		Reason  string          `json:"reason"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}
	req.Kind = strings.TrimSpace(req.Kind)
	req.Name = strings.TrimSpace(req.Name)
	if req.Kind != model.ApprovalKindSkill && req.Kind != model.ApprovalKindMCP {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "kind 仅支持 skill 或 mcp", "type": "invalid_request_error"},
		})
		return
	}
	if req.Name == "" || len(req.Name) > maxApprovalNameLen {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "name 不能为空且不超过 128 字符", "type": "invalid_request_error"},
		})
		return
	}
	if len(req.Source) > maxApprovalSourceLen {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "source 不超过 256 字符", "type": "invalid_request_error"},
		})
		return
	}
	if len(req.Reason) > maxApprovalReasonLen {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "reason 不超过 2000 字符", "type": "invalid_request_error"},
		})
		return
	}
	payload := "{}"
	if len(req.Payload) > 0 {
		if len(req.Payload) > maxApprovalPayload {
			c.JSON(http.StatusBadRequest, gin.H{
				"error": gin.H{"message": "payload 序列化后不超过 64KB", "type": "invalid_request_error"},
			})
			return
		}
		var probe map[string]any
		if err := json.Unmarshal(req.Payload, &probe); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{
				"error": gin.H{"message": "payload 必须是 JSON 对象", "type": "invalid_request_error"},
			})
			return
		}
		payload = string(req.Payload)
	}

	id := terminalID(c)
	name := c.GetString("terminal_name")
	mode := model.ApprovalModeManual
	if h.settingsStore != nil {
		if m, err := h.settingsStore.ApprovalMode(); err != nil {
			slog.Warn("failed to read approval mode, fallback manual", "error", err, "terminal_id", id)
		} else {
			mode = m
		}
	}

	a := &model.ExtensionApproval{
		TerminalID:   id,
		TerminalName: name,
		Kind:         req.Kind,
		Name:         req.Name,
		Source:       req.Source,
		Payload:      payload,
		Reason:       req.Reason,
		State:        model.ApprovalStatePending,
		ApproveMode:  mode,
	}
	if err := h.approvalStore.Create(a); err != nil {
		slog.Error("failed to create extension approval", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}

	// 自动审批（预留）：auto 模式且已注册决策器 → 立即决策；未注册决策器 → 保持 pending 兜底人工
	if mode == model.ApprovalModeAuto {
		if h.decider == nil {
			slog.Warn("approval mode is auto but no decider registered; request kept pending for manual review",
				"approval_id", a.ID, "terminal_id", id)
		} else {
			decision, derr := h.decider.Decide(c.Request.Context(), service.ApprovalRequest{
				TerminalID:   a.TerminalID,
				TerminalName: a.TerminalName,
				Kind:         a.Kind,
				Name:         a.Name,
				Source:       a.Source,
				Payload:      a.Payload,
				Reason:       a.Reason,
				RequestedAt:  a.CreatedAt,
			})
			if derr != nil {
				slog.Warn("auto approval decider failed; request kept pending",
					"error", derr, "decider", h.decider.Name(), "approval_id", a.ID)
			} else {
				wantState := model.ApprovalStateRejected
				if decision.Approved {
					wantState = model.ApprovalStateApproved
				}
				if updated, uerr := h.approvalStore.Review(a.ID, nil, wantState, model.ApprovalModeAuto, decision.Note); uerr != nil {
					slog.Error("failed to apply auto approval decision", "error", uerr, "approval_id", a.ID)
				} else if updated {
					a.State = wantState
					a.ApproveMode = model.ApprovalModeAuto
					a.ReviewNote = decision.Note
					slog.Info("auto approval decided",
						"decider", h.decider.Name(), "approval_id", a.ID, "state", wantState)
				}
			}
		}
	}

	slog.Info("extension approval submitted", "approval_id", a.ID, "terminal_id", id, "kind", a.Kind, "name", a.Name, "state", a.State)
	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"request_id":   a.ID,
			"state":        a.State,
			"approve_mode": a.ApproveMode,
		},
	})
}

// ListExtensionRequests handles GET /telemetry/v1/extensions/requests
// 返回本终端最近的审批单（默认 200 条内），客户端以 (request_id, state) 对账推进。
// 建议轮询节奏：提交申请后每 30s 一次直至非 pending。
func (h *TelemetryHandler) ListExtensionRequests(c *gin.Context) {
	if h.approvalStore == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "extension governance not enabled", "type": "not_found_error"},
		})
		return
	}
	id := terminalID(c)
	items, err := h.approvalStore.ListByTerminal(id, atoiDefault(c.Query("limit"), 200))
	if err != nil {
		slog.Error("failed to list extension approvals for terminal", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"requests": items}})
}

// ListAssignedSkills handles GET /telemetry/v1/skills
// 返回分配给本终端的全部 skill 包（zip base64 + 版本 + 上次回执），客户端解压安装后回执。
func (h *TelemetryHandler) ListAssignedSkills(c *gin.Context) {
	if h.skillStore == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "extension governance not enabled", "type": "not_found_error"},
		})
		return
	}
	id := terminalID(c)

	packages, err := h.skillStore.PackagesForTerminal(id)
	if err != nil {
		slog.Error("failed to list skill packages for terminal", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	applyments, err := h.skillStore.ApplymentsForTerminal(id)
	if err != nil {
		slog.Error("failed to list applyments for terminal", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	applyMap := make(map[int64]model.SkillApplyment, len(applyments))
	for _, ap := range applyments {
		applyMap[ap.PackageID] = ap
	}

	type skillItem struct {
		PackageID      int64   `json:"package_id"`
		Name           string  `json:"name"`
		Description    string  `json:"description"`
		Version        int64   `json:"version"`
		ZipName        string  `json:"zip_name"`
		ZipSize        int64   `json:"zip_size"`
		ZipBase64      string  `json:"zip_base64"`
		UpdatedAt      string  `json:"updated_at"`
		AppliedVersion *int64  `json:"applied_version"`
		AppliedStatus  string  `json:"applied_status"`
		AppliedAt      *string `json:"applied_at"`
	}
	items := make([]skillItem, 0, len(packages))
	pending := int64(0)
	for _, p := range packages {
		it := skillItem{
			PackageID:   p.ID,
			Name:        p.Name,
			Description: p.Description,
			Version:     p.Version,
			ZipName:     p.ZipName,
			ZipSize:     p.ZipSize,
			ZipBase64:   base64.StdEncoding.EncodeToString(p.ZipData),
			UpdatedAt:   isoTime(&p.UpdatedAt),
		}
		if ap, ok := applyMap[p.ID]; ok {
			it.AppliedVersion = &ap.PackageVersion
			it.AppliedStatus = ap.Status
			appliedAt := isoTime(&ap.AppliedAt)
			it.AppliedAt = &appliedAt
			if ap.PackageVersion < p.Version || ap.Status == model.SkillApplyFailed {
				pending++
			}
		} else {
			pending++
		}
		items = append(items, it)
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"skills": items, "pending_count": pending}})
}

// ConfirmSkillApplied handles POST /telemetry/v1/skills/applied
// 客户端解压安装某包某版本后的回执；失败回执（ok=false）保留为待同步，
// 客户端可按节奏重试（服务端以"回执版本 ≥ 包当前版本且 ok"为已同步口径）。
func (h *TelemetryHandler) ConfirmSkillApplied(c *gin.Context) {
	if h.skillStore == nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "extension governance not enabled", "type": "not_found_error"},
		})
		return
	}
	var req struct {
		PackageID int64  `json:"package_id" binding:"required"`
		Version   int64  `json:"version" binding:"required"`
		OK        bool   `json:"ok"`
		Message   string `json:"message"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}
	id := terminalID(c)
	if req.PackageID <= 0 || req.Version <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "package_id 与 version 必须为正整数", "type": "invalid_request_error"},
		})
		return
	}
	assigned, err := h.skillStore.IsAssigned(req.PackageID, id)
	if err != nil {
		slog.Error("failed to check skill assignment", "error", err, "terminal_id", id, "package_id", req.PackageID)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if !assigned {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "该 skill 包未分配给本终端", "type": "invalid_request_error"},
		})
		return
	}
	status := model.SkillApplyOK
	if !req.OK {
		status = model.SkillApplyFailed
	}
	ap := &model.SkillApplyment{
		PackageID:      req.PackageID,
		TerminalID:     id,
		PackageVersion: req.Version,
		Status:         status,
		Message:        truncateStr(req.Message, maxSkillApplyMsgLen),
	}
	if err := h.skillStore.ConfirmApply(ap); err != nil {
		slog.Error("failed to confirm skill applyment", "error", err, "terminal_id", id, "package_id", req.PackageID)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"status": "ok"}})
}

// truncateStr 截断超长字符串（按字符数，不会切断多字节字符）。
func truncateStr(s string, max int) string {
	runes := []rune(s)
	if len(runes) <= max {
		return s
	}
	return string(runes[:max])
}
