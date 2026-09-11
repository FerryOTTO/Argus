package handler

import (
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/service"
	"github.com/llmgate/llmgate/internal/store"
)

// AdminExtensionHandler 管理"扩展治理"两个板块：
//   - skill/MCP 安装审批（extension_approvals）；
//   - Skill 分发（skill_packages + 终端分配 + 新终端默认包）。
type AdminExtensionHandler struct {
	approvalStore *store.ExtensionApprovalStore
	skillStore    *store.SkillPackageStore
	terminalStore *store.TerminalStore
}

// NewAdminExtensionHandler creates a new AdminExtensionHandler
func NewAdminExtensionHandler(approvalStore *store.ExtensionApprovalStore, skillStore *store.SkillPackageStore, terminalStore *store.TerminalStore) *AdminExtensionHandler {
	return &AdminExtensionHandler{
		approvalStore: approvalStore,
		skillStore:    skillStore,
		terminalStore: terminalStore,
	}
}

// ────────────────────────── 安装审批 ──────────────────────────

// ListApprovals handles GET /api/admin/extensions/approvals
func (h *AdminExtensionHandler) ListApprovals(c *gin.Context) {
	f := store.ApprovalFilter{
		State:    c.Query("state"),
		Kind:     c.Query("kind"),
		Keyword:  c.Query("keyword"),
		Page:     atoiDefault(c.Query("page"), 1),
		PageSize: atoiDefault(c.Query("page_size"), 20),
	}
	if v, err := strconv.ParseInt(c.Query("terminal_id"), 10, 64); err == nil {
		f.TerminalID = v
	}

	items, total, err := h.approvalStore.List(f)
	if err != nil {
		slog.Error("failed to list extension approvals", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to list approvals", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"data":      items,
		"total":     total,
		"page":      f.Page,
		"page_size": f.PageSize,
	})
}

// ApprovalStats handles GET /api/admin/extensions/approvals/stats
func (h *AdminExtensionHandler) ApprovalStats(c *gin.Context) {
	stats, err := h.approvalStore.Stats()
	if err != nil {
		slog.Error("failed to get approval stats", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to get approval stats", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": stats})
}

type reviewApprovalRequest struct {
	Note string `json:"note"`
}

// ApproveApproval handles POST /api/admin/extensions/approvals/:id/approve
func (h *AdminExtensionHandler) ApproveApproval(c *gin.Context) {
	h.reviewApproval(c, model.ApprovalStateApproved, false)
}

// RejectApproval handles POST /api/admin/extensions/approvals/:id/reject
// 驳回必须附理由（服务端强校验，理由随单留存供终端查看）。
func (h *AdminExtensionHandler) RejectApproval(c *gin.Context) {
	h.reviewApproval(c, model.ApprovalStateRejected, true)
}

// reviewApproval 人工审批公共路径：仅 pending 可流转。
func (h *AdminExtensionHandler) reviewApproval(c *gin.Context, wantState string, noteRequired bool) {
	id, ok := h.parseApprovalID(c)
	if !ok {
		return
	}
	var req reviewApprovalRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}
	req.Note = strings.TrimSpace(req.Note)
	if noteRequired && req.Note == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "驳回必须填写理由", "type": "invalid_request_error"},
		})
		return
	}

	reviewerID := currentUserID(c)
	updated, err := h.approvalStore.Review(id, &reviewerID, wantState, model.ApprovalModeManual, req.Note)
	if err != nil {
		slog.Error("failed to review approval", "error", err, "approval_id", id, "state", wantState)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to review approval", "type": "internal_error"},
		})
		return
	}
	if !updated {
		c.JSON(http.StatusConflict, gin.H{
			"error": gin.H{"message": "该申请已被审批，不能重复操作", "type": "conflict_error", "code": "already_reviewed"},
		})
		return
	}

	approval, err := h.approvalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to reload approval after review", "error", err, "approval_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": approval})
}

// ────────────────────────── Skill 分发 ──────────────────────────

// ListSkillPackages handles GET /api/admin/extensions/skill-packages
func (h *AdminExtensionHandler) ListSkillPackages(c *gin.Context) {
	items, total, err := h.skillStore.List(
		atoiDefault(c.Query("page"), 1),
		atoiDefault(c.Query("page_size"), 20),
		c.Query("keyword"),
	)
	if err != nil {
		slog.Error("failed to list skill packages", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to list skill packages", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"data":      items,
		"total":     total,
		"page":      atoiDefault(c.Query("page"), 1),
		"page_size": atoiDefault(c.Query("page_size"), 20),
	})
}

// UploadSkillPackage handles POST /api/admin/extensions/skill-packages (multipart).
// 表单字段：file（.zip，必填）、description（可选覆盖说明）。
// 同名 skill 再次上传 = 覆盖内容并 version+1（分配保留，终端按版本差重拉）。
func (h *AdminExtensionHandler) UploadSkillPackage(c *gin.Context) {
	fh, err := c.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "请上传 skill 压缩包（file 字段）", "type": "invalid_request_error"},
		})
		return
	}
	if fh.Size > service.SkillZipMaxBytes {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "压缩包超过大小上限", "type": "invalid_request_error"},
		})
		return
	}

	src, err := fh.Open()
	if err != nil {
		slog.Error("failed to open uploaded skill zip", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	defer src.Close()
	data, err := io.ReadAll(io.LimitReader(src, service.SkillZipMaxBytes+1))
	if err != nil {
		slog.Error("failed to read uploaded skill zip", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}

	meta, err := service.ParseSkillZip(fh.Filename, data)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "压缩包校验失败：" + err.Error(), "type": "invalid_request_error", "code": "invalid_skill_zip"},
		})
		return
	}

	creator := currentUserID(c)
	pkg := &model.SkillPackage{
		Name:        meta.Name,
		Description: strings.TrimSpace(c.PostForm("description")),
		ZipName:     meta.ZipName,
		ZipSize:     meta.ZipSize,
		ZipData:     data,
		Preview:     meta.Preview,
		CreatedBy:   &creator,
	}
	if pkg.Description == "" {
		pkg.Description = meta.Description // 兜底用 frontmatter description
	}
	isNew, err := h.skillStore.SaveContent(pkg)
	if err != nil {
		slog.Error("failed to save skill package", "error", err, "name", pkg.Name)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to save skill package", "type": "internal_error"},
		})
		return
	}
	slog.Info("skill package saved",
		"is_new", isNew, "id", pkg.ID, "name", pkg.Name, "version", pkg.Version, "by", creator)
	c.JSON(http.StatusOK, gin.H{"data": pkg, "is_new": isNew})
}

// UpdateSkillPackage handles PUT /api/admin/extensions/skill-packages/:id（仅描述）
func (h *AdminExtensionHandler) UpdateSkillPackage(c *gin.Context) {
	id, ok := parseIDParam(c)
	if !ok {
		return
	}
	var req struct {
		Description string `json:"description"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}
	if err := h.skillStore.UpdateDescription(id, strings.TrimSpace(req.Description)); err != nil {
		slog.Error("failed to update skill package description", "error", err, "package_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to update skill package", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "skill package updated"})
}

// DeleteSkillPackage handles DELETE /api/admin/extensions/skill-packages/:id
func (h *AdminExtensionHandler) DeleteSkillPackage(c *gin.Context) {
	id, ok := parseIDParam(c)
	if !ok {
		return
	}
	if _, err := h.skillStore.GetByID(id); err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "skill package not found", "type": "not_found_error"},
		})
		return
	}
	if err := h.skillStore.Delete(id); err != nil {
		slog.Error("failed to delete skill package", "error", err, "package_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to delete skill package", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "skill package deleted"})
}

// ListSkillPackageAssignments handles GET /api/admin/extensions/skill-packages/:id/assignments
func (h *AdminExtensionHandler) ListSkillPackageAssignments(c *gin.Context) {
	id, ok := parseIDParam(c)
	if !ok {
		return
	}
	if _, err := h.skillStore.GetByID(id); err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "skill package not found", "type": "not_found_error"},
		})
		return
	}
	ids, err := h.skillStore.ListAssignedTerminalIDs(id)
	if err != nil {
		slog.Error("failed to list skill package assignments", "error", err, "package_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"terminal_ids": ids}})
}

// ReplaceSkillPackageAssignments handles PUT /api/admin/extensions/skill-packages/:id/assignments
// 语义：全量覆盖（body.terminal_ids 即目标集合；空数组 = 解除全部分发）。
func (h *AdminExtensionHandler) ReplaceSkillPackageAssignments(c *gin.Context) {
	id, ok := parseIDParam(c)
	if !ok {
		return
	}
	if _, err := h.skillStore.GetByID(id); err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "skill package not found", "type": "not_found_error"},
		})
		return
	}
	var req struct {
		TerminalIDs []int64 `json:"terminal_ids"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	// 终端存在性校验（含去重），报出全部非法 id 便于前端修正
	seen := map[int64]bool{}
	var unknown []int64
	for _, tid := range req.TerminalIDs {
		if tid <= 0 || seen[tid] {
			continue
		}
		seen[tid] = true
		t, err := h.terminalStore.GetByID(tid)
		if err != nil || t == nil {
			unknown = append(unknown, tid)
		}
	}
	if len(unknown) > 0 {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "unknown terminal ids: " + joinInts(unknown), "type": "invalid_request_error"},
		})
		return
	}
	ids := make([]int64, 0, len(seen))
	for tid := range seen {
		ids = append(ids, tid)
	}

	if err := h.skillStore.ReplaceAssignments(id, ids); err != nil {
		slog.Error("failed to replace skill package assignments", "error", err, "package_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to save assignments", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "assignments updated", "data": gin.H{"terminal_ids": ids}})
}

// TerminalOptions handles GET /api/admin/extensions/terminal-options
// 全量终端轻量列表，供分发多选与默认包配置使用。
func (h *AdminExtensionHandler) TerminalOptions(c *gin.Context) {
	opts, err := h.terminalStore.ListOptions()
	if err != nil {
		slog.Error("failed to list terminal options", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": opts})
}

// GetDefaultSkillPackages handles GET /api/admin/extensions/default-skill-packages
func (h *AdminExtensionHandler) GetDefaultSkillPackages(c *gin.Context) {
	d, err := h.skillStore.DefaultPackages()
	if err != nil {
		slog.Error("failed to get default skill packages", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": d})
}

// SetDefaultSkillPackages handles PUT /api/admin/extensions/default-skill-packages
// 启用后，新注册成功的终端自动获得这些包的分配（见 /telemetry/v1/register）。
func (h *AdminExtensionHandler) SetDefaultSkillPackages(c *gin.Context) {
	var d model.DefaultSkillPackages
	if err := c.ShouldBindJSON(&d); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}
	var unknown []int64
	seen := map[int64]bool{}
	for _, pid := range d.PackageIDs {
		if pid <= 0 || seen[pid] {
			continue
		}
		seen[pid] = true
		if _, err := h.skillStore.GetByID(pid); err != nil {
			unknown = append(unknown, pid)
		}
	}
	if len(unknown) > 0 {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "unknown skill package ids: " + joinInts(unknown), "type": "invalid_request_error"},
		})
		return
	}
	ids := make([]int64, 0, len(seen))
	for pid := range seen {
		ids = append(ids, pid)
	}
	d.PackageIDs = ids
	if err := h.skillStore.SetDefaultPackages(&d); err != nil {
		slog.Error("failed to save default skill packages", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": d})
}

// ────────────────────────── helpers ──────────────────────────

// parseIDParam 解析并校验通用 :id 路径参数（错误文本不带资源类型，供扩展治理类接口复用）
func parseIDParam(c *gin.Context) (int64, bool) {
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || id <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid id", "type": "invalid_request_error"},
		})
		return 0, false
	}
	return id, true
}

// parseApprovalID 解析并校验 :id 路径参数
func (h *AdminExtensionHandler) parseApprovalID(c *gin.Context) (int64, bool) {
	return parseIDParam(c)
}

// currentUserID 读取认证中间件写入的当前管理员 id（类型 int64）。
func currentUserID(c *gin.Context) int64 {
	if v, ok := c.Get("user_id"); ok {
		if id, ok := v.(int64); ok {
			return id
		}
	}
	return 0
}

// atoiDefault 带默认值的整型 query 解析
func atoiDefault(v string, def int) int {
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}

// joinInts 输出 "[1,2,3]" 便于前端解析
func joinInts(ids []int64) string {
	parts := make([]string, 0, len(ids))
	for _, id := range ids {
		parts = append(parts, strconv.FormatInt(id, 10))
	}
	return "[" + strings.Join(parts, ", ") + "]"
}
