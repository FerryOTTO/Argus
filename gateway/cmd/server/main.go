package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/llmgate/llmgate/internal/auth"
	"github.com/llmgate/llmgate/internal/cleanup"
	"github.com/llmgate/llmgate/internal/config"
	"github.com/llmgate/llmgate/internal/crypto"
	"github.com/llmgate/llmgate/internal/handler"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/proxy"
	"github.com/llmgate/llmgate/internal/service"
	"github.com/llmgate/llmgate/internal/static"
	"github.com/llmgate/llmgate/internal/store"
)

func main() {
	configPath := flag.String("config", "configs/config.yaml", "Path to config file")
	flag.Parse()

	// 1. Load config
	cfg, err := config.Load(*configPath)
	if err != nil {
		slog.Error("Failed to load config", "error", err)
		os.Exit(1)
	}

	// 2. Initialize database
	db, err := store.Open(cfg.Database.Path)
	if err != nil {
		slog.Error("Failed to open database", "error", err)
		os.Exit(1)
	}
	defer db.Close()

	// 3. Run migrations
	if err := store.RunMigrations(db, "migrations"); err != nil {
		slog.Error("Failed to run migrations", "error", err)
		os.Exit(1)
	}

	// 4. Create encryptor for provider API key encryption
	encryptor, err := crypto.NewEncryptor(cfg.Security.EncryptKey)
	if err != nil {
		slog.Error("Failed to create encryptor", "error", err)
		os.Exit(1)
	}
	if encryptor == nil {
		slog.Warn("Provider API keys will be stored in plaintext (encrypt_key not configured)")
	} else {
		slog.Info("Provider API key encryption enabled")
	}

	// 5. Create stores
	userStore := store.NewUserStore(db)
	providerStore := store.NewProviderStore(db, encryptor)
	apiKeyStore := store.NewAPIKeyStore(db)
	quotaStore := store.NewQuotaStore(db)
	auditStore := store.NewAuditStore(db, 1024)
	defer auditStore.Close()
	convStore := store.NewConversationStore(db, cfg.Conversation.BatchSize)
	defer convStore.Close()
	terminalStore := store.NewTerminalStore(db)
	settingsStore := store.NewSettingsStore(db)
	agentAuditEventStore := store.NewAgentAuditEventStore(db)
	// 扩展治理 store（skill/MCP 安装审批 + Skill 分发）
	extensionApprovalStore := store.NewExtensionApprovalStore(db)
	skillPackageStore := store.NewSkillPackageStore(db, settingsStore)

	// 6. Create default admin user if not exists
	ensureDefaultAdmin(userStore)

	// 7. Create services
	apiKeyService := service.NewAPIKeyService(apiKeyStore, userStore)
	quotaService := service.NewQuotaService(quotaStore)

	// 8. Build proxy router
	proxyRouter := proxy.NewProviderRouter(providerStore)
	if err := proxyRouter.LoadModels(); err != nil {
		slog.Warn("Failed to load models for proxy", "error", err)
	}
	proxyHandler := proxy.NewProxyHandler(proxyRouter, convStore, true, quotaService)

	// 9. Setup auth registry and SSO
	registry := auth.NewRegistry()
	// Register local auth provider
	localProvider := auth.NewLocalAuth(userStore)
	registry.Register(localProvider)

	// Load OAuth2 providers from DB
	oauth2Store := auth.NewOAuth2ConfigStore(db)
	if configs, err := oauth2Store.ListActive(); err == nil {
		for _, cfg := range configs {
			var provider auth.AuthProvider
			switch cfg.ProviderType {
			case "oidc":
				provider = auth.NewOIDCProvider(cfg, userStore)
			default:
				provider = auth.NewOAuth2Provider(cfg, userStore)
			}
			registry.Register(provider)
			slog.Info("Registered SSO provider", "name", cfg.Name, "type", cfg.ProviderType)
		}
	} else {
		slog.Warn("Failed to load SSO providers", "error", err)
	}

	// 10. Setup HTTP router
	reloadModels := func() {
		if err := proxyRouter.LoadModels(); err != nil {
			slog.Warn("Failed to reload model routing table", "error", err)
		}
	}
	r := handler.SetupRouter(cfg, db, userStore, providerStore, apiKeyService, quotaService, quotaStore, proxyHandler, auditStore, convStore, terminalStore, settingsStore, registry, oauth2Store, agentAuditEventStore, reloadModels, extensionApprovalStore, skillPackageStore, nil /* decider: 自动审批决策器（预留，nil=仅人工审批，见 service.ApprovalDecider） */)

	// 11. Start cleanup worker for old audit and conversation logs
	cleanupWorker := cleanup.NewWorker(auditStore, convStore, agentAuditEventStore, cfg.Conversation.RetentionDays)
	cleanupWorker.Start()
	defer cleanupWorker.Stop()

	// 12. Serve frontend static files
	static.SetupStatic(r, "web/dist")

	// 13. Start server with graceful shutdown
	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", cfg.Server.Port),
		Handler: r,
	}

	go func() {
		slog.Info("LLMGate server starting", "port", cfg.Server.Port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("Server failed", "error", err)
			os.Exit(1)
		}
	}()

	// Wait for interrupt signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	slog.Info("Shutting down server...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		slog.Error("Server forced to shutdown", "error", err)
	}
	slog.Info("Server exited")
}

// ensureDefaultAdmin creates a default admin user if no admin exists
func ensureDefaultAdmin(userStore *store.UserStore) {
	existing, err := userStore.GetByUsername("admin")
	if err != nil {
		slog.Error("Failed to check for default admin", "error", err)
		return
	}
	if existing != nil {
		return
	}

	hash, err := auth.HashPassword("admin123")
	if err != nil {
		slog.Error("Failed to hash default admin password", "error", err)
		return
	}

	admin := &model.User{
		Username:           "admin",
		PasswordHash:       hash,
		Role:               "admin",
		IsActive:           true,
		MustChangePassword: true,
	}
	if err := userStore.Create(admin); err != nil {
		slog.Error("Failed to create default admin", "error", err)
		return
	}
	slog.Info("Default admin user created (username: admin, password: admin123)")
}
