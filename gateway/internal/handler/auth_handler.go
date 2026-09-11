package handler

import (
	"crypto/rand"
	"encoding/hex"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/auth"
	"github.com/llmgate/llmgate/internal/config"
	"github.com/llmgate/llmgate/internal/store"
)

// AuthHandler handles authentication endpoints
type AuthHandler struct {
	cfg             *config.Config
	userStore       *store.UserStore
	registry        *auth.Registry
	oauth2Store     *auth.OAuth2ConfigStore
	settingsStore   *store.SettingsStore
	oauth2Mu        sync.RWMutex
	oauth2Providers map[string]*auth.OAuth2Provider
}

// NewAuthHandler creates a new AuthHandler
func NewAuthHandler(cfg *config.Config, userStore *store.UserStore, registry *auth.Registry, oauth2Store *auth.OAuth2ConfigStore, settingsStore *store.SettingsStore) *AuthHandler {
	h := &AuthHandler{
		cfg:             cfg,
		userStore:       userStore,
		registry:        registry,
		oauth2Store:     oauth2Store,
		settingsStore:   settingsStore,
		oauth2Providers: make(map[string]*auth.OAuth2Provider),
	}
	return h
}

type loginRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

// Login handles POST /api/auth/login
func (h *AuthHandler) Login(c *gin.Context) {
	var req loginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{
				"message": "username and password are required",
				"type":    "invalid_request_error",
				"code":    "missing_fields",
			},
		})
		return
	}

	user, err := h.userStore.GetByUsername(req.Username)
	if err != nil {
		slog.Error("failed to lookup user", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{
				"message": "internal error",
				"type":    "internal_error",
			},
		})
		return
	}

	if user == nil {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{
				"message": "invalid username or password",
				"type":    "authentication_error",
				"code":    "invalid_credentials",
			},
		})
		return
	}

	if !user.IsActive {
		c.JSON(http.StatusForbidden, gin.H{
			"error": gin.H{
				"message": "account is disabled",
				"type":    "authentication_error",
				"code":    "account_disabled",
			},
		})
		return
	}

	if err := auth.ComparePassword(user.PasswordHash, req.Password); err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{
				"message": "invalid username or password",
				"type":    "authentication_error",
				"code":    "invalid_credentials",
			},
		})
		return
	}

	// 普通用户不再有控制台界面：仅管理员可登录
	if user.Role != "admin" {
		c.JSON(http.StatusForbidden, gin.H{
			"error": gin.H{
				"message": "admin only: regular users cannot sign in to the console",
				"type":    "authentication_error",
				"code":    "admin_only",
			},
		})
		return
	}

	expiry := h.cfg.Server.JWTExpiry
	if expiry == 0 {
		expiry = 24 * time.Hour
	}

	token, err := auth.GenerateToken(user, h.cfg.Server.JWTSecret, expiry)
	if err != nil {
		slog.Error("failed to generate token", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{
				"message": "failed to generate token",
				"type":    "internal_error",
			},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"token":      token,
		"expires_at": time.Now().Add(expiry).Format(time.RFC3339),
		"user": gin.H{
			"id":                   user.ID,
			"username":             user.Username,
			"email":                user.Email,
			"role":                 user.Role,
			"must_change_password": user.MustChangePassword,
			"security_level":       user.SecurityLevel,
			"specials":             user.Specials,
		},
	})
}

// Refresh handles POST /api/auth/refresh
func (h *AuthHandler) Refresh(c *gin.Context) {
	authHeader := c.GetHeader("Authorization")
	if authHeader == "" {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{
				"message": "missing authorization header",
				"type":    "authentication_error",
			},
		})
		return
	}

	// Extract token - expect "Bearer <token>"
	var tokenStr string
	if len(authHeader) > 7 && authHeader[:7] == "Bearer " {
		tokenStr = authHeader[7:]
	} else {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{
				"message": "invalid authorization header format",
				"type":    "authentication_error",
			},
		})
		return
	}

	expiry := h.cfg.Server.JWTExpiry
	if expiry == 0 {
		expiry = 24 * time.Hour
	}

	newToken, err := auth.RefreshToken(tokenStr, h.cfg.Server.JWTSecret, expiry)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{
				"message": "invalid or expired token",
				"type":    "authentication_error",
			},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"token":      newToken,
		"expires_at": time.Now().Add(expiry).Format(time.RFC3339),
	})
}

// GetSSOProviders handles GET /api/auth/sso-providers
func (h *AuthHandler) GetSSOProviders(c *gin.Context) {
	if h.oauth2Store == nil {
		c.JSON(http.StatusOK, gin.H{"providers": []interface{}{}})
		return
	}

	configs, err := h.oauth2Store.ListActive()
	if err != nil {
		slog.Error("failed to list SSO providers", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to list SSO providers", "type": "internal_error"},
		})
		return
	}

	type providerInfo struct {
		Name string `json:"name"`
		Type string `json:"type"`
	}
	providers := make([]providerInfo, 0, len(configs))
	for _, cfg := range configs {
		providers = append(providers, providerInfo{Name: cfg.Name, Type: cfg.ProviderType})
	}

	c.JSON(http.StatusOK, gin.H{"providers": providers})
}

// GetEnterpriseInfo handles GET /api/auth/info — 登录页展示所需的公共信息
func (h *AuthHandler) GetEnterpriseInfo(c *gin.Context) {
	enterpriseName := ""
	if h.settingsStore != nil {
		if v, found, err := h.settingsStore.Get(store.SettingEnterpriseName); err == nil && found {
			enterpriseName = v
		}
	}
	c.JSON(http.StatusOK, gin.H{
		"data": gin.H{
			"enterprise_name": enterpriseName,
		},
	})
}

// SSOInitiate handles GET /api/auth/sso/:provider
func (h *AuthHandler) SSOInitiate(c *gin.Context) {
	providerName := c.Param("provider")
	provider, err := h.getOAuth2Provider(providerName)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "SSO provider not found: " + providerName, "type": "invalid_request_error"},
		})
		return
	}

	// Generate random state
	stateBytes := make([]byte, 16)
	if _, err := rand.Read(stateBytes); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to generate state", "type": "internal_error"},
		})
		return
	}
	state := hex.EncodeToString(stateBytes)

	redirectURI := c.Query("redirect_uri")
	authURL := provider.GetAuthURL(state, redirectURI)

	c.JSON(http.StatusOK, gin.H{
		"auth_url": authURL,
		"state":    state,
	})
}

// SSOCallback handles GET /api/auth/sso/:provider/callback
func (h *AuthHandler) SSOCallback(c *gin.Context) {
	providerName := c.Param("provider")
	provider, err := h.getOAuth2Provider(providerName)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": gin.H{"message": "SSO provider not found: " + providerName, "type": "invalid_request_error"},
		})
		return
	}

	code := c.Query("code")
	if code == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{"message": "missing authorization code", "type": "invalid_request_error"},
		})
		return
	}

	redirectURI := c.Query("redirect_uri")
	req := &auth.AuthRequest{
		Code:        code,
		RedirectURI: redirectURI,
	}

	result, err := provider.Authenticate(c.Request.Context(), req)
	if err != nil {
		slog.Error("SSO authentication failed", "provider", providerName, "error", err)
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{"message": "SSO authentication failed: " + err.Error(), "type": "authentication_error"},
		})
		return
	}

	// 普通用户不再有控制台界面：SSO 登录同样仅管理员
	if result.User.Role != "admin" {
		c.JSON(http.StatusForbidden, gin.H{
			"error": gin.H{
				"message": "admin only: regular users cannot sign in to the console",
				"type":    "authentication_error",
				"code":    "admin_only",
			},
		})
		return
	}

	expiry := h.cfg.Server.JWTExpiry
	if expiry == 0 {
		expiry = 24 * time.Hour
	}

	token, err := auth.GenerateToken(result.User, h.cfg.Server.JWTSecret, expiry)
	if err != nil {
		slog.Error("failed to generate token after SSO", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{"message": "failed to generate token", "type": "internal_error"},
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"token":      token,
		"expires_at": time.Now().Add(expiry).Format(time.RFC3339),
		"user": gin.H{
			"id":             result.User.ID,
			"username":       result.User.Username,
			"email":          result.User.Email,
			"role":           result.User.Role,
			"security_level": result.User.SecurityLevel,
			"specials":       result.User.Specials,
		},
	})
}

// getOAuth2Provider retrieves or creates an OAuth2 provider by name
func (h *AuthHandler) getOAuth2Provider(name string) (*auth.OAuth2Provider, error) {
	h.oauth2Mu.RLock()
	if p, ok := h.oauth2Providers[name]; ok {
		h.oauth2Mu.RUnlock()
		return p, nil
	}
	h.oauth2Mu.RUnlock()

	if h.oauth2Store == nil {
		return nil, nil
	}

	cfg, err := h.oauth2Store.GetByName(name)
	if err != nil {
		return nil, err
	}

	var p *auth.OAuth2Provider
	switch cfg.ProviderType {
	case "oidc":
		p = &auth.OAuth2Provider{}
		oidc := auth.NewOIDCProvider(*cfg, h.userStore)
		_ = p // use oidc instead
		h.oauth2Mu.Lock()
		h.oauth2Providers[name] = &oidc.OAuth2Provider
		h.oauth2Mu.Unlock()
		return &oidc.OAuth2Provider, nil
	default:
		p = auth.NewOAuth2Provider(*cfg, h.userStore)
	}

	h.oauth2Mu.Lock()
	h.oauth2Providers[name] = p
	h.oauth2Mu.Unlock()

	return p, nil
}
