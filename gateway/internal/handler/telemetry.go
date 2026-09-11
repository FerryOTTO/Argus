package handler

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/crypto"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/service"
	"github.com/llmgate/llmgate/internal/store"
)

// TelemetryHandler handles client-facing telemetry endpoints under /telemetry/v1.
// 对外契约见仓库根 REMOTE.md（交付客户端工程师）与 CLIENT.md（扩展治理适配）。
type TelemetryHandler struct {
	terminalStore   *store.TerminalStore
	settingsStore   *store.SettingsStore
	apiKeyService   *service.APIKeyService
	auditEventStore *store.AgentAuditEventStore

	// 扩展治理（skill/MCP 安装审批 + Skill 分发），可为 nil（未启用时对应端点 404）
	approvalStore *store.ExtensionApprovalStore
	skillStore    *store.SkillPackageStore
	decider       service.ApprovalDecider // 自动审批决策器；nil = 无自动策略（见 service.ApprovalDecider）
}

// NewTelemetryHandler creates a new TelemetryHandler
func NewTelemetryHandler(terminalStore *store.TerminalStore, settingsStore *store.SettingsStore, apiKeyService *service.APIKeyService, auditEventStore *store.AgentAuditEventStore, approvalStore *store.ExtensionApprovalStore, skillStore *store.SkillPackageStore, decider service.ApprovalDecider) *TelemetryHandler {
	return &TelemetryHandler{
		terminalStore:   terminalStore,
		settingsStore:   settingsStore,
		apiKeyService:   apiKeyService,
		auditEventStore: auditEventStore,
		approvalStore:   approvalStore,
		skillStore:      skillStore,
		decider:         decider,
	}
}

// Live access rules reported by terminals (in-memory cache, no DB migration).
// Terminal posts its current users.txt/resources.txt text in POST /telemetry/v1/report;
// admin GetConfig returns them as live_config so the editor can prefill rows.
type reportedAccessRules struct {
	Users     string
	Resources string
	UpdatedAt time.Time
}

var (
	reportedRulesMu sync.RWMutex
	reportedRules   = map[int64]reportedAccessRules{}
)

// Full live config snapshot reported by terminals (in-memory cache, no DB migration).
// Terminal posts modules/io_guard_policy/retrieval/access/integration dicts in
// POST /telemetry/v1/report as live_config (api_key already stripped client-side);
// admin GetConfig merges them into live_config so the editor prefills every group.
type reportedLiveFull struct {
	Users     string
	Resources string
	Live      json.RawMessage
	UpdatedAt time.Time
}

const maxLiveConfigBytes = 256 * 1024

var (
	reportedLiveMu sync.RWMutex
	reportedLive   = map[int64]reportedLiveFull{}
)

func storeReportedLiveFull(id int64, users, resources string, live json.RawMessage) {
	if len(live) > maxLiveConfigBytes {
		live = live[:maxLiveConfigBytes]
	}
	if len(users) > 128*1024 {
		users = users[:128*1024]
	}
	if len(resources) > 128*1024 {
		resources = resources[:128*1024]
	}
	reportedLiveMu.Lock()
	reportedLive[id] = reportedLiveFull{Users: users, Resources: resources, Live: append(json.RawMessage(nil), live...), UpdatedAt: time.Now()}
	reportedLiveMu.Unlock()
}

func loadReportedLiveFull(id int64) (reportedLiveFull, bool) {
	reportedLiveMu.RLock()
	r, ok := reportedLive[id]
	reportedLiveMu.RUnlock()
	return r, ok
}

func storeReportedRules(id int64, users, resources string) {
	if len(users) > 128*1024 {
		users = users[:128*1024]
	}
	if len(resources) > 128*1024 {
		resources = resources[:128*1024]
	}
	reportedRulesMu.Lock()
	reportedRules[id] = reportedAccessRules{Users: users, Resources: resources, UpdatedAt: time.Now()}
	reportedRulesMu.Unlock()
}

func loadReportedRules(id int64) (reportedAccessRules, bool) {
	reportedRulesMu.RLock()
	r, ok := reportedRules[id]
	reportedRulesMu.RUnlock()
	return r, ok
}

// buildLiveConfigPkg assembles the editor prefill package for single-user editing:
// live_config carries only the bound terminal user's own level
// (access_user.username/level) plus the full resources.txt text; the whole
// users.txt is never sent down. Level parsing matches the terminal/frontend:
// skip blank lines and lines starting with '#', split columns by '|', strip
// inline comments, and normalize level aliases (digits 1-4 / letters a-d,
// case-insensitive) to canonical names.
func buildLiveConfigPkg(username, users, resources string, live json.RawMessage) string {
	if strings.TrimSpace(username) == "" && strings.TrimSpace(users) == "" && strings.TrimSpace(resources) == "" && len(live) == 0 {
		return ""
	}
	obj := map[string]any{
		"schema_version": 1,
	}
	if strings.TrimSpace(username) != "" {
		name := strings.TrimSpace(username)
		au := map[string]any{"username": name}
		if lv := parseLiveUserLevel(users, name); lv != "" {
			au["level"] = lv
		}
		// users.txt 已下线：终端 users 上报为空，从 live.access.bound_user.level（无则 default_user_level）兜底
		if _, ok := au["level"]; !ok && len(live) > 0 {
			var lm map[string]any
			if err := json.Unmarshal(live, &lm); err == nil {
				if acc, ok := lm["access"].(map[string]any); ok && acc != nil {
					if b, ok := acc["bound_user"].(map[string]any); ok && b != nil {
						if bl, ok := b["level"].(string); ok && strings.TrimSpace(bl) != "" {
							au["level"] = strings.TrimSpace(bl)
						}
					}
					if _, ok := au["level"]; !ok {
						if dl, ok := acc["default_user_level"].(string); ok && strings.TrimSpace(dl) != "" {
							au["level"] = strings.TrimSpace(dl)
						}
					}
				}
			}
		}
		obj["access_user"] = au
	}
	if strings.TrimSpace(resources) != "" {
		obj["access_rules"] = map[string]any{"resources": resources}
	}
	if len(obj) <= 1 {
		return ""
	}
	raw, err := json.MarshalIndent(obj, "", "  ")
	if err != nil {
		return ""
	}
	return string(raw)
}

var liveLevelAliases = map[string]string{
	"1": "public", "2": "internal", "3": "secret", "4": "top_secret",
	"a": "public", "b": "internal", "c": "secret", "d": "top_secret",
	"public": "public", "internal": "internal", "secret": "secret",
	"top_secret": "top_secret", "topsecret": "top_secret",
}

// parseLiveUserLevel finds the bound user's own row in users.txt and returns
// its normalized default level; "" when the user has no row.
func parseLiveUserLevel(usersText, username string) string {
	for _, raw := range strings.Split(usersText, "\n") {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if i := liveInlineCommentPos(line); i >= 0 {
			line = strings.TrimSpace(line[:i])
		}
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		segs := strings.Split(line, "|")
		if len(segs) < 2 {
			continue
		}
		if strings.TrimSpace(segs[0]) != username {
			continue
		}
		s := strings.TrimSpace(strings.ToLower(segs[1]))
		if v, ok := liveLevelAliases[s]; ok {
			return v
		}
		return strings.TrimSpace(segs[1])
	}
	return ""
}

// buildFullLiveConfigPkg merges the terminal-reported live snapshot into the editor
// prefill package: access_user (bound user only) + access_rules.resources plus every
// other group the terminal reports (modules/io_guard_policy/retrieval/access/
// integration). Defense in depth: drop any tool_guard secret keys even though the
// terminal already strips api_key before upload.
func buildFullLiveConfigPkg(username, users, resources string, live json.RawMessage) string {
	obj := map[string]any{
		"schema_version": 1,
	}
	if strings.TrimSpace(username) != "" {
		name := strings.TrimSpace(username)
		au := map[string]any{"username": name}
		if lv := parseLiveUserLevel(users, name); lv != "" {
			au["level"] = lv
		}
		// users.txt 已下线：终端 users 上报为空，从 live.access.bound_user.level（无则 default_user_level）兜底
		if _, ok := au["level"]; !ok && len(live) > 0 {
			var lm map[string]any
			if err := json.Unmarshal(live, &lm); err == nil {
				if acc, ok := lm["access"].(map[string]any); ok && acc != nil {
					if b, ok := acc["bound_user"].(map[string]any); ok && b != nil {
						if bl, ok := b["level"].(string); ok && strings.TrimSpace(bl) != "" {
							au["level"] = strings.TrimSpace(bl)
						}
					}
					if _, ok := au["level"]; !ok {
						if dl, ok := acc["default_user_level"].(string); ok && strings.TrimSpace(dl) != "" {
							au["level"] = strings.TrimSpace(dl)
						}
					}
				}
			}
		}
		obj["access_user"] = au
	}
	if strings.TrimSpace(resources) != "" {
		obj["access_rules"] = map[string]any{"resources": resources}
	}
	if len(live) > 0 && len(live) <= maxLiveConfigBytes {
		var m map[string]any
		if err := json.Unmarshal(live, &m); err == nil {
			for _, k := range []string{"modules", "io_guard_policy", "retrieval", "access", "integration"} {
				if v, ok := m[k]; ok && v != nil {
					obj[k] = v
				}
			}
			if mods, ok := obj["modules"].(map[string]any); ok {
				if tg, ok := mods["tool_guard"].(map[string]any); ok {
					for _, sk := range []string{"api_key", "apikey", "secret", "token"} {
						delete(tg, sk)
					}
				}
			}
		}
	}
	if len(obj) <= 1 {
		return ""
	}
	raw, err := json.MarshalIndent(obj, "", "  ")
	if err != nil {
		return ""
	}
	return string(raw)
}

// liveInlineCommentPos locates an inline comment start, consistent with the
// frontend rulesText.ts (/\s+#.*$/): '#' only counts when the previous char
// is whitespace, so '#' inside a path is never stripped.
func liveInlineCommentPos(s string) int {
	for i := 0; i < len(s); i++ {
		if s[i] == '#' && i > 0 && (s[i-1] == ' ' || s[i-1] == '\t') {
			return i - 1
		}
	}
	return -1
}

// terminalID extracts the authenticated terminal id set by middleware.TelemetryAuth
func terminalID(c *gin.Context) int64 {
	return c.GetInt64("terminal_id")
}

// ────────────────────────── 注册（无遥测令牌，凭注册码）──────────────────────────

type telemetryRegisterRequest struct {
	RegistrationCode string `json:"registration_code" binding:"required"`
	Hostname         string `json:"hostname"`
	OSInfo           string `json:"os_info"`
	AgentType        string `json:"agent_type"`
	AgentVersion     string `json:"agent_version"`
	ArgusVersion string `json:"argus_version"`
}

// Register handles POST /telemetry/v1/register.
// 校验一次性注册码，签发遥测令牌（明文仅本次返回，库中仅存哈希）。
func (h *TelemetryHandler) Register(c *gin.Context) {
	var req telemetryRegisterRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	terminal, err := h.terminalStore.GetByRegistrationCodeHash(crypto.HashSecret(strings.TrimSpace(req.RegistrationCode)))
	if err != nil {
		slog.Error("failed to look up registration code", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if terminal == nil {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{"message": "invalid registration code", "type": "authentication_error", "code": "invalid_registration_code"},
		})
		return
	}

	// 预防误绑：注册码唯一对应终端，请求声明类型须与库一致（空视为不声明）
	if req.AgentType != "" && !strings.EqualFold(terminal.AgentType, req.AgentType) {
		c.JSON(http.StatusConflict, gin.H{
			"error": gin.H{"message": "agent_type mismatch with terminal registration", "type": "invalid_request_error"},
		})
		return
	}

	token, err := crypto.GenerateSecret()
	if err != nil {
		slog.Error("failed to generate telemetry token", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}

	if err := h.terminalStore.Activate(
		terminal.ID,
		crypto.HashSecret(token),
		strings.TrimSpace(req.Hostname),
		strings.TrimSpace(req.OSInfo),
		strings.TrimSpace(req.AgentVersion),
		strings.TrimSpace(req.ArgusVersion),
	); err != nil {
		slog.Error("failed to activate terminal", "error", err, "terminal_id", terminal.ID)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}

	// 平台 LLM 凭据下发：注册成功即签发绑定终端的 LLM API key，
	// 与企业名/base_url 随响应一次提供给客户端（明文仅本次返回）。
	llm, err := h.issueLLMCredential(terminal)
	if err != nil {
		slog.Error("failed to issue llm credential", "error", err, "terminal_id", terminal.ID)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}

	// 新终端自动分发：注册成功即把“默认 skill 包”分配给该终端（幂等）；
	// 分配后终端凭心跳/响应中的 skills_pending 拉取分发包（见 CLIENT.md）。
	skillsPending := false
	if h.skillStore != nil {
		if d, derr := h.skillStore.DefaultPackages(); derr == nil && d.Enabled {
			if aerr := h.skillStore.AssignToTerminals(terminal.ID, d.PackageIDs); aerr != nil {
				slog.Error("failed to auto assign default skill packages", "error", aerr, "terminal_id", terminal.ID)
			}
		}
		if n, perr := h.skillStore.PendingCount(terminal.ID); perr != nil {
			slog.Error("failed to count pending skill packages", "error", perr, "terminal_id", terminal.ID)
		} else {
			skillsPending = n > 0
		}
	}

	slog.Info("terminal registered", "terminal_id", terminal.ID, "name", terminal.Name, "agent_type", terminal.AgentType)
	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"terminal_id":    terminal.ID,
			"terminal_name":  terminal.Name,
			"agent_type":     terminal.AgentType,
			"token":          token,
			"hint":           "token and llm credentials are shown only once; store them in the client config",
			"llm":            llm,
			"skills_pending": skillsPending,
		},
	})
}

// issueLLMCredential 为注册终端签发平台 LLM API key 并建立终端关联。
// key 归属注册时刻终端的绑定用户（可为无主）；permissions 取系统设置「开放模型」
// 白名单，未配置或空列表时签全模型（["*"]）。base_url 由「系统根地址」组合 /v1 生成。
func (h *TelemetryHandler) issueLLMCredential(terminal *model.AgentTerminal) (gin.H, error) {
	// 重复注册场景（未吊销即重走注册码）：先停用旧 key，再签发新 key
	if terminal.LLMAPIKeyID != nil {
		if err := h.apiKeyService.DeactivateKey(*terminal.LLMAPIKeyID); err != nil {
			return nil, fmt.Errorf("failed to deactivate previous llm api key: %w", err)
		}
	}

	// 企业名称 / 系统根地址（均可能未配置，未配置时相应字段为空串）
	enterpriseName := ""
	if v, found, err := h.settingsStore.Get(store.SettingEnterpriseName); err != nil {
		return nil, fmt.Errorf("failed to read enterprise name setting: %w", err)
	} else if found {
		enterpriseName = v
	}

	baseURL := ""
	if root, found, err := h.settingsStore.Get(store.SettingSystemBaseURL); err != nil {
		return nil, fmt.Errorf("failed to read system base url setting: %w", err)
	} else if found && strings.TrimSpace(root) != "" {
		baseURL = strings.TrimRight(strings.TrimSpace(root), "/")
		if !strings.HasSuffix(baseURL, "/v1") {
			baseURL += "/v1"
		}
	}

	// 开放模型白名单：未设置 / 空列表 / 非法 JSON → 全模型
	perms := []string{"*"}
	if raw, found, err := h.settingsStore.Get(store.SettingOpenModels); err != nil {
		return nil, fmt.Errorf("failed to read open models setting: %w", err)
	} else if found && raw != "" {
		var models []string
		if err := json.Unmarshal([]byte(raw), &models); err == nil && len(models) > 0 {
			perms = models
		}
	}

	// 归属：key 所有者 = 终端当前绑定用户（可空 → 无主 key，见 api_keys.user_id）
	rawKey, key, err := h.apiKeyService.GenerateKey(
		terminal.BoundUserID,
		&terminal.ID,
		"终端 LLM 凭据 - "+terminal.Name,
		perms,
		nil,
	)
	if err != nil {
		return nil, fmt.Errorf("failed to generate llm api key: %w", err)
	}

	if err := h.terminalStore.LinkLLMKey(terminal.ID, key.ID); err != nil {
		return nil, fmt.Errorf("failed to link llm api key to terminal: %w", err)
	}

	return gin.H{
		"api_key_id":      key.ID,
		"api_key":         rawKey,
		"base_url":        baseURL,
		"enterprise_name": enterpriseName,
	}, nil
}

// ────────────────────────── 鉴权后的遥测端点 ──────────────────────────

type telemetryHeartbeatRequest struct {
	Hostname         string `json:"hostname"`
	OSInfo           string `json:"os_info"`
	AgentType        string `json:"agent_type"`
	AgentVersion     string `json:"agent_version"`
	ArgusVersion string `json:"argus_version"`
}

// Heartbeat handles POST /telemetry/v1/heartbeat.
// 客户端周期性上报运行状态；响应带 config_pending 供客户端决定拉取配置。
func (h *TelemetryHandler) Heartbeat(c *gin.Context) {
	var req telemetryHeartbeatRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	id := terminalID(c)
	if err := h.terminalStore.TouchHeartbeat(
		id,
		strings.TrimSpace(req.Hostname),
		strings.TrimSpace(req.OSInfo),
		strings.TrimSpace(req.AgentVersion),
		strings.TrimSpace(req.ArgusVersion),
	); err != nil {
		slog.Error("failed to record heartbeat", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}

	terminal, err := h.terminalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to reload terminal after heartbeat", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}

	// 扩展治理：待同步 skill 包数 > 0 时置位，提示客户端拉取分发包（见 CLIENT.md）
	skillsPending := false
	if h.skillStore != nil {
		if n, perr := h.skillStore.PendingCount(id); perr != nil {
			slog.Error("failed to count pending skill packages", "error", perr, "terminal_id", id)
		} else {
			skillsPending = n > 0
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"status":         "ok",
			"server_time":    time.Now().UTC().Format(time.RFC3339),
			"config_pending": configPending(terminal.ConfigVersion, terminal.ConfigAppliedVersion),
			"config_version": terminal.ConfigVersion,
			"skills_pending": skillsPending,
		},
	})
}

// GetConfig handles GET /telemetry/v1/config.
// 客户端拉取集控下发的 Argus 配置（幂等；config 为空串表示无下发配置）。
func (h *TelemetryHandler) GetConfig(c *gin.Context) {
	id := terminalID(c)
	terminal, err := h.terminalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to load terminal config", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"terminal_id":            terminal.ID,
			"config_version":         terminal.ConfigVersion,
			"config":                 terminal.DesiredConfig,
			"config_updated_at":      isoTime(terminal.ConfigUpdatedAt),
			"config_pending":         configPending(terminal.ConfigVersion, terminal.ConfigAppliedVersion),
			"config_applied_version": terminal.ConfigAppliedVersion,
		},
	})
}

type telemetryConfigAppliedRequest struct {
	ConfigVersion int64 `json:"config_version" binding:"required"`
}

// ConfirmConfigApplied handles POST /telemetry/v1/config/applied.
// 客户端应用某版本配置成功后的回执，用于管理端展示"已应用状态"。
// 服务端仅接受 <= 当前 config_version 的回执：回执超前（> 当前版本）说明客户端
// 状态混乱（如曾拉取到后被管理员清除下发），直接拒绝以防 applied 越权跳过 pending。
func (h *TelemetryHandler) ConfirmConfigApplied(c *gin.Context) {
	var req telemetryConfigAppliedRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "config_version is required", "type": "invalid_request_error"},
		})
		return
	}

	id := terminalID(c)
	terminal, err := h.terminalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to load terminal before config ack", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}
	if req.ConfigVersion > terminal.ConfigVersion {
		c.JSON(http.StatusConflict, gin.H{
			"error": gin.H{"message": "config_version is ahead of server version; re-pull /telemetry/v1/config", "type": "invalid_request_error", "code": "config_version_ahead"},
		})
		return
	}

	if err := h.terminalStore.ConfirmConfigApplied(id, req.ConfigVersion); err != nil {
		slog.Error("failed to confirm config applied", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"status":         "ok",
			"config_version": req.ConfigVersion,
		},
	})
}

// telemetryAlertSample 是窗口内一条安全预警的审计样本（当前仅记日志，计数以 delta 为准）。
type telemetryAlertSample struct {
	At        string  `json:"at"`
	Stage     string  `json:"stage"`
	Module    string  `json:"module"`
	Action    string  `json:"action"`
	RiskScore float64 `json:"risk_score"`
	Reason    string  `json:"reason"`
	TraceID   string  `json:"trace_id"`
}

type telemetryReportRequest struct {
	WindowStartedAt     string                 `json:"window_started_at"`
	TokenUsageDelta     int64                  `json:"token_usage_delta"`
	SecurityAlertsDelta int64                  `json:"security_alerts_delta"`
	AlertSamples        []telemetryAlertSample `json:"alert_samples"`
	AccessRules         *telemetryAccessRules  `json:"access_rules"`
	LiveConfig          json.RawMessage        `json:"live_config"`
}

type telemetryAccessRules struct {
	Users     string `json:"users"`
	Resources string `json:"resources"`
}

// Report handles POST /telemetry/v1/report.
// 客户端周期上报自上次成功上报以来的增量；服务端仅在该请求成功后才应答 200，
// 客户端以 200 为准清空本地窗口（保证不重不漏，见 REMOTE.md 上报规则）。
func (h *TelemetryHandler) Report(c *gin.Context) {
	var req telemetryReportRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "invalid request body: " + err.Error(), "type": "invalid_request_error"},
		})
		return
	}

	if req.TokenUsageDelta < 0 || req.SecurityAlertsDelta < 0 {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "deltas must be non-negative", "type": "invalid_request_error"},
		})
		return
	}

	id := terminalID(c)
	if req.AccessRules != nil && (req.AccessRules.Users != "" || req.AccessRules.Resources != "") {
		storeReportedRules(id, req.AccessRules.Users, req.AccessRules.Resources)
	}
	if len(req.LiveConfig) > 0 {
		users, resources := "", ""
		if req.AccessRules != nil {
			users, resources = req.AccessRules.Users, req.AccessRules.Resources
		}
		storeReportedLiveFull(id, users, resources, req.LiveConfig)
		if users == "" && resources == "" {
			if r, ok := loadReportedRules(id); ok {
				storeReportedLiveFull(id, r.Users, r.Resources, req.LiveConfig)
			}
		} else {
			storeReportedRules(id, users, resources)
		}
	}
	if req.TokenUsageDelta > 0 || req.SecurityAlertsDelta > 0 {
		if err := h.terminalStore.ApplyReportDelta(id, req.TokenUsageDelta, req.SecurityAlertsDelta); err != nil {
			slog.Error("failed to apply terminal report", "error", err, "terminal_id", id)
			c.JSON(http.StatusInternalServerError, gin.H{
				"error": gin.H{"message": "internal error", "type": "internal_error"},
			})
			return
		}
	}

	for _, sample := range req.AlertSamples {
		slog.Warn("terminal security alert",
			"terminal_id", id,
			"at", sample.At, "stage", sample.Stage, "module", sample.Module,
			"action", sample.Action, "risk_score", sample.RiskScore,
			"reason", sample.Reason, "trace_id", sample.TraceID,
		)
	}

	terminal, err := h.terminalStore.GetByID(id)
	if err != nil {
		slog.Error("failed to reload terminal after report", "error", err, "terminal_id", id)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "internal error", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"status":            "ok",
			"token_usage_total": terminal.TokenUsageTotal,
			"alert_count_total": terminal.AlertCountTotal,
		},
	})
}

// configPending 判断是否存在客户端尚未应用的新配置
func configPending(configVersion, appliedVersion int64) bool {
	return configVersion > appliedVersion
}

// isoTime 将可选时间转为 RFC3339 字符串（nil → 空串）
func isoTime(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.UTC().Format(time.RFC3339)
}
