package handler

import (
	"github.com/gin-gonic/gin"
	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/auth"
	"github.com/llmgate/llmgate/internal/config"
	"github.com/llmgate/llmgate/internal/middleware"
	"github.com/llmgate/llmgate/internal/proxy"
	"github.com/llmgate/llmgate/internal/service"
	"github.com/llmgate/llmgate/internal/store"
)

// SetupRouter creates and configures the Gin engine with all routes
func SetupRouter(
	cfg *config.Config,
	db *sqlx.DB,
	userStore *store.UserStore,
	providerStore *store.ProviderStore,
	apiKeyService *service.APIKeyService,
	quotaService *service.QuotaService,
	quotaStore *store.QuotaStore,
	proxyHandler *proxy.ProxyHandler,
	auditStore *store.AuditStore,
	convStore *store.ConversationStore,
	terminalStore *store.TerminalStore,
	settingsStore *store.SettingsStore,
	registry *auth.Registry,
	oauth2Store *auth.OAuth2ConfigStore,
	agentAuditEventStore *store.AgentAuditEventStore,
	onModelChange func(),
	extensionApprovalStore *store.ExtensionApprovalStore,
	skillPackageStore *store.SkillPackageStore,
	decider service.ApprovalDecider,
) *gin.Engine {
	r := gin.Default()

	// Security headers middleware (applied globally)
	r.Use(middleware.SecurityHeaders())

	// CORS middleware
	r.Use(corsMiddleware(cfg))

	// Audit logging middleware for /v1/* and /api/* routes
	if auditStore != nil {
		r.Use(func(c *gin.Context) {
			// Only apply audit to /v1/ and /api/ paths
			if len(c.Request.URL.Path) >= 4 &&
				(c.Request.URL.Path[:4] == "/v1/" || (len(c.Request.URL.Path) >= 5 && c.Request.URL.Path[:5] == "/api/")) {
				middleware.AuditLog(auditStore)(c)
			} else {
				c.Next()
			}
		})
	}

	// Health check
	r.GET("/health", healthHandler)

	// Auth routes (public)
	authH := NewAuthHandler(cfg, userStore, registry, oauth2Store, settingsStore)
	authGroup := r.Group("/api/auth")
	{
		authGroup.POST("/login", authH.Login)
		authGroup.POST("/refresh", authH.Refresh)
		authGroup.GET("/info", authH.GetEnterpriseInfo)
		authGroup.GET("/sso-providers", authH.GetSSOProviders)
		authGroup.GET("/sso/:provider", authH.SSOInitiate)
		authGroup.GET("/sso/:provider/callback", authH.SSOCallback)
	}

	// OpenAI-compatible API routes (JWT or API Key auth)
	v1 := r.Group("/v1")
	v1.Use(middleware.GlobalRateLimit(120))
	v1.Use(middleware.UnifiedAuth(cfg.Server.JWTSecret, apiKeyService))
	v1.Use(middleware.QuotaCheck(quotaService))
	{
		v1.GET("/models", proxyHandler.HandleListModels)
		v1.POST("/chat/completions", proxyHandler.HandleChatCompletions)
		v1.POST("/completions", proxyHandler.HandleCompletions)
	}

	// Admin routes (JWT + admin role required)
	admin := r.Group("/api/admin")
	admin.Use(middleware.AuthRequired(cfg.Server.JWTSecret))
	admin.Use(middleware.AdminRequired())
	{
		providerH := NewAdminProviderHandler(providerStore)
		providerH.OnChange = onModelChange
		admin.GET("/providers", providerH.ListProviders)
		admin.GET("/providers/:id/upstream-models", providerH.ListUpstreamModels)
		admin.POST("/providers", providerH.CreateProvider)
		admin.PUT("/providers/:id", providerH.UpdateProvider)
		admin.DELETE("/providers/:id", providerH.DeleteProvider)
		admin.POST("/models", providerH.CreateModel)
		admin.DELETE("/models/:id", providerH.DeleteModel)

		userH := NewAdminUserHandler(userStore)
		admin.GET("/users", userH.ListUsers)
		admin.POST("/users", userH.CreateUser)
		admin.PUT("/users/:id", userH.UpdateUser)
		admin.DELETE("/users/:id", userH.DeleteUser)
		admin.PUT("/users/:id/password", userH.ResetPassword)

		apiKeyH := NewAdminAPIKeyHandler(apiKeyService, terminalStore)
		admin.GET("/api-keys", apiKeyH.ListAPIKeys)
		admin.POST("/api-keys", apiKeyH.CreateAPIKey)
		admin.PUT("/api-keys/:id", apiKeyH.UpdateAPIKey)
		admin.POST("/api-keys/:id/deactivate", apiKeyH.DeactivateAPIKey)
		admin.DELETE("/api-keys/:id", apiKeyH.DeleteAPIKey)

		// 系统设置与可选模型列表（设置驱动注册下发的 base_url/开放模型）
		settingsH := NewAdminSettingsHandler(settingsStore)
		admin.GET("/settings", settingsH.GetSettings)
		admin.PUT("/settings", settingsH.UpdateSettings)
		admin.GET("/models", proxyHandler.HandleListModels)

		// 当前登录管理员的改密（含首次登录强制改密）
		passwordH := NewAdminPasswordHandler(userStore)
		admin.PUT("/change-password", passwordH.ChangePassword)

		quotaH := NewAdminQuotaHandler(quotaStore)
		admin.GET("/quotas", quotaH.ListQuotas)
		admin.POST("/quotas", quotaH.CreateQuota)
		admin.DELETE("/quotas/:id", quotaH.DeleteQuota)
		admin.GET("/usage", quotaH.GetUsage)

		// Audit routes + Dashboard overview（网关流量 + 终端态势 + 安全事件聚合）
		if auditStore != nil {
			auditH := NewAdminAuditHandler(auditStore)
			admin.GET("/audit-logs", auditH.GetAuditLogs)
			admin.GET("/audit-logs/export", auditH.ExportAuditLogs)

			dashH := NewAdminDashboardHandler(auditStore, terminalStore, agentAuditEventStore)
			admin.GET("/dashboard", dashH.GetDashboard)
		}

		// 终端审计事件 routes（Clawguard 客户端上报，审计日志 · 终端审计板块）
		if agentAuditEventStore != nil {
			agentAuditH := NewAdminAgentAuditHandler(agentAuditEventStore)
			admin.GET("/audit-events", agentAuditH.ListAgentAuditEvents)
			admin.GET("/audit-events/stats", agentAuditH.AgentAuditStats)
			admin.GET("/audit-events/terminal-stats", agentAuditH.TerminalAuditStats)
			admin.GET("/audit-events/export", agentAuditH.ExportAgentAuditEvents)
		}

		// Conversation routes
		if convStore != nil {
			convH := NewConversationHandler(convStore)
			admin.GET("/conversations", convH.ListConversations)
			admin.GET("/conversations/:id", convH.GetConversationDetail)
		}

		// Agent terminal routes (遥测/集控端管理)
		if terminalStore != nil {
			termH := NewAdminTerminalHandler(terminalStore, apiKeyService, agentAuditEventStore)
			admin.GET("/terminals", termH.ListTerminals)
			admin.POST("/terminals", termH.CreateTerminal)
			admin.PUT("/terminals/:id", termH.UpdateTerminal)
			admin.DELETE("/terminals/:id", termH.DeleteTerminal)
			admin.POST("/terminals/:id/regenerate-code", termH.RegenerateCode)
			admin.POST("/terminals/:id/revoke", termH.Revoke)
			admin.GET("/terminals/:id/config", termH.GetConfig)
			admin.PUT("/terminals/:id/config", termH.UpdateConfig)
		}

		// 扩展治理：skill/MCP 安装审批 + Skill 分发（表/契约见 CLIENT.md 与 SKILL_CREATION.md）
		if extensionApprovalStore != nil && skillPackageStore != nil {
			extH := NewAdminExtensionHandler(extensionApprovalStore, skillPackageStore, terminalStore)
			ext := admin.Group("/extensions")
			{
				ext.GET("/approvals", extH.ListApprovals)
				ext.GET("/approvals/stats", extH.ApprovalStats)
				ext.POST("/approvals/:id/approve", extH.ApproveApproval)
				ext.POST("/approvals/:id/reject", extH.RejectApproval)
				ext.GET("/skill-packages", extH.ListSkillPackages)
				ext.POST("/skill-packages", extH.UploadSkillPackage)
				ext.PUT("/skill-packages/:id", extH.UpdateSkillPackage)
				ext.DELETE("/skill-packages/:id", extH.DeleteSkillPackage)
				ext.GET("/skill-packages/:id/assignments", extH.ListSkillPackageAssignments)
				ext.PUT("/skill-packages/:id/assignments", extH.ReplaceSkillPackageAssignments)
				ext.GET("/terminal-options", extH.TerminalOptions)
				ext.GET("/default-skill-packages", extH.GetDefaultSkillPackages)
				ext.PUT("/default-skill-packages", extH.SetDefaultSkillPackages)
			}
		}

		// OAuth provider management routes
		ssoHandler := NewAdminSSOHandler(oauth2Store)
		adminOAuth := admin.Group("/oauth-providers")
		{
			adminOAuth.GET("", ssoHandler.ListProviders)
			adminOAuth.POST("", ssoHandler.CreateProvider)
			adminOAuth.PUT("/:id", ssoHandler.UpdateProvider)
			adminOAuth.DELETE("/:id", ssoHandler.DeleteProvider)
			adminOAuth.PUT("/:id/toggle", ssoHandler.ToggleProvider)
		}
	}

	// Telemetry routes (agent terminals, per-terminal token auth)
	if terminalStore != nil {
		telemetryH := NewTelemetryHandler(terminalStore, settingsStore, apiKeyService, agentAuditEventStore, extensionApprovalStore, skillPackageStore, decider)
		telemetry := r.Group("/telemetry/v1")
		{
			// 注册端点无遥测令牌，凭一次性注册码换取令牌
			telemetry.POST("/register", telemetryH.Register)

			authed := telemetry.Group("")
			authed.Use(middleware.TelemetryAuth(terminalStore))
			authed.POST("/heartbeat", telemetryH.Heartbeat)
			authed.GET("/config", telemetryH.GetConfig)
			authed.POST("/config/applied", telemetryH.ConfirmConfigApplied)
			authed.POST("/report", telemetryH.Report)
			// 审计事件批量上传（Clawguard 审计层周期上报，幂等去重）
			authed.POST("/audit/events", telemetryH.UploadAuditEvents)
			// 扩展治理：安装审批上报/轮询 + skill 分发拉取/回执（store 未启用时返回 404）
			authed.POST("/extensions/requests", telemetryH.SubmitExtensionRequest)
			authed.GET("/extensions/requests", telemetryH.ListExtensionRequests)
			authed.GET("/skills", telemetryH.ListAssignedSkills)
			authed.POST("/skills/applied", telemetryH.ConfirmSkillApplied)
		}
	}

	return r
}

// corsMiddleware provides basic CORS support for development
func corsMiddleware(cfg *config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		origins := cfg.Server.CORSOrigins
		if len(origins) > 0 {
			c.Header("Access-Control-Allow-Origin", origins[0])
			c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
			c.Header("Access-Control-Allow-Headers", "Content-Type, Authorization")
		}
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}
		c.Next()
	}
}

// healthHandler returns server health status
func healthHandler(c *gin.Context) {
	c.JSON(200, gin.H{"status": "ok"})
}
