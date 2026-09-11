package auth

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"golang.org/x/oauth2"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/store"
)

// OAuth2Config represents a stored OAuth2 provider configuration
type OAuth2Config struct {
	ID           int64  `db:"id" json:"id"`
	Name         string `db:"name" json:"name"`
	ProviderType string `db:"provider_type" json:"provider_type"`
	ClientID     string `db:"client_id" json:"client_id"`
	ClientSecret string `db:"client_secret" json:"-"`
	AuthURL      string `db:"auth_url" json:"auth_url"`
	TokenURL     string `db:"token_url" json:"token_url"`
	UserInfoURL  string `db:"userinfo_url" json:"userinfo_url"`
	Scopes       string `db:"scopes" json:"scopes"`
	AutoCreate   bool   `db:"auto_create_user" json:"auto_create_user"`
	DefaultRole  string    `db:"default_role" json:"default_role"`
	IsActive     bool      `db:"is_active" json:"is_active"`
	CreatedAt    time.Time `db:"created_at" json:"created_at"`
}

// OAuth2Provider implements AuthProvider for OAuth2
type OAuth2Provider struct {
	config    OAuth2Config
	oauthConf *oauth2.Config
	userStore *store.UserStore
}

// NewOAuth2Provider creates a new OAuth2Provider
func NewOAuth2Provider(cfg OAuth2Config, userStore *store.UserStore) *OAuth2Provider {
	scopes := strings.Split(cfg.Scopes, " ")
	if len(scopes) == 0 || (len(scopes) == 1 && scopes[0] == "") {
		scopes = []string{"openid", "profile", "email"}
	}

	oauthConf := &oauth2.Config{
		ClientID:     cfg.ClientID,
		ClientSecret: cfg.ClientSecret,
		Endpoint: oauth2.Endpoint{
			AuthURL:  cfg.AuthURL,
			TokenURL: cfg.TokenURL,
		},
		Scopes: scopes,
	}

	return &OAuth2Provider{
		config:    cfg,
		oauthConf: oauthConf,
		userStore: userStore,
	}
}

// Name returns the provider name
func (p *OAuth2Provider) Name() string {
	return p.config.Name
}

// Type returns the provider type
func (p *OAuth2Provider) Type() string {
	return "oauth2"
}

// IsEnabled returns whether the provider is active
func (p *OAuth2Provider) IsEnabled() bool {
	return p.config.IsActive
}

// GetAuthURL generates the OAuth2 authorization URL
func (p *OAuth2Provider) GetAuthURL(state, redirectURI string) string {
	conf := p.oauthConf
	if redirectURI != "" {
		conf = &oauth2.Config{
			ClientID:     p.oauthConf.ClientID,
			ClientSecret: p.oauthConf.ClientSecret,
			Endpoint:     p.oauthConf.Endpoint,
			Scopes:       p.oauthConf.Scopes,
			RedirectURL:  redirectURI,
		}
	}
	return conf.AuthCodeURL(state)
}

// Authenticate exchanges the authorization code for a token and fetches user info
func (p *OAuth2Provider) Authenticate(ctx context.Context, req *AuthRequest) (*AuthResult, error) {
	if req.Code == "" {
		return nil, fmt.Errorf("authorization code is required")
	}

	conf := p.oauthConf
	if req.RedirectURI != "" {
		conf = &oauth2.Config{
			ClientID:     p.oauthConf.ClientID,
			ClientSecret: p.oauthConf.ClientSecret,
			Endpoint:     p.oauthConf.Endpoint,
			Scopes:       p.oauthConf.Scopes,
			RedirectURL:  req.RedirectURI,
		}
	}

	// Exchange code for token
	token, err := conf.Exchange(ctx, req.Code)
	if err != nil {
		return nil, fmt.Errorf("failed to exchange code: %w", err)
	}

	// Fetch user info
	userInfo, err := p.fetchUserInfo(token)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch user info: %w", err)
	}

	// Find or create user
	var username string
	if v, ok := userInfo["preferred_username"].(string); ok && v != "" {
		username = v
	} else if v, ok := userInfo["email"].(string); ok && v != "" {
		username = v
	} else if v, ok := userInfo["sub"].(string); ok && v != "" {
		username = v
	} else {
		return nil, fmt.Errorf("could not determine username from user info")
	}

	user, err := p.userStore.GetByUsername(username)
	if err != nil {
		return nil, fmt.Errorf("failed to lookup user: %w", err)
	}

	if user == nil {
		if !p.config.AutoCreate {
			return nil, fmt.Errorf("user not found and auto-create is disabled")
		}
		// Create new user
		user = &model.User{
			Username: username,
			Role:     p.config.DefaultRole,
			IsActive: true,
			// SSO 自建账号默认最低可用等级，管理员后续在后台上调
			SecurityLevel: "internal",
		}
		if email, ok := userInfo["email"].(string); ok && email != "" {
			user.Email = &email
		}
		if err := p.userStore.Create(user); err != nil {
			return nil, fmt.Errorf("failed to create user: %w", err)
		}
		slog.Info("auto-created user via SSO", "username", username, "provider", p.config.Name)
	}

	if !user.IsActive {
		return nil, fmt.Errorf("account is disabled")
	}

	return &AuthResult{User: user}, nil
}

// fetchUserInfo retrieves user info from the OAuth2 provider
func (p *OAuth2Provider) fetchUserInfo(token *oauth2.Token) (map[string]interface{}, error) {
	client := p.oauthConf.Client(context.Background(), token)
	resp, err := client.Get(p.config.UserInfoURL)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch user info: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read user info response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("user info request failed with status %d: %s", resp.StatusCode, string(body))
	}

	var userInfo map[string]interface{}
	if err := json.Unmarshal(body, &userInfo); err != nil {
		return nil, fmt.Errorf("failed to parse user info: %w", err)
	}

	return userInfo, nil
}

// OAuth2ConfigStore provides methods to load OAuth2 configs from the database
type OAuth2ConfigStore struct {
	db *sqlx.DB
}

// NewOAuth2ConfigStore creates a new OAuth2ConfigStore
func NewOAuth2ConfigStore(db *sqlx.DB) *OAuth2ConfigStore {
	return &OAuth2ConfigStore{db: db}
}

// ListActive returns all active OAuth2 provider configs
func (s *OAuth2ConfigStore) ListActive() ([]OAuth2Config, error) {
	var configs []OAuth2Config
	err := s.db.Select(&configs, "SELECT * FROM oauth_providers WHERE is_active = 1")
	if err != nil {
		return nil, fmt.Errorf("failed to list oauth providers: %w", err)
	}
	return configs, nil
}

// List returns all OAuth2 provider configs
func (s *OAuth2ConfigStore) List() ([]OAuth2Config, error) {
	var configs []OAuth2Config
	err := s.db.Select(&configs, "SELECT * FROM oauth_providers ORDER BY created_at DESC")
	if err != nil {
		return nil, fmt.Errorf("failed to list oauth providers: %w", err)
	}
	return configs, nil
}

// Get returns an OAuth2 config by ID
func (s *OAuth2ConfigStore) Get(id int64) (*OAuth2Config, error) {
	var cfg OAuth2Config
	err := s.db.Get(&cfg, "SELECT * FROM oauth_providers WHERE id = ?", id)
	if err != nil {
		return nil, fmt.Errorf("failed to get oauth provider: %w", err)
	}
	return &cfg, nil
}

// GetByName returns an OAuth2 config by name
func (s *OAuth2ConfigStore) GetByName(name string) (*OAuth2Config, error) {
	var cfg OAuth2Config
	err := s.db.Get(&cfg, "SELECT * FROM oauth_providers WHERE name = ?", name)
	if err != nil {
		return nil, fmt.Errorf("failed to get oauth provider: %w", err)
	}
	return &cfg, nil
}

// Create inserts a new OAuth2 provider config
func (s *OAuth2ConfigStore) Create(cfg *OAuth2Config) error {
	result, err := s.db.Exec(
		`INSERT INTO oauth_providers (name, provider_type, client_id, client_secret, auth_url, token_url, userinfo_url, scopes, auto_create_user, default_role, is_active)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		cfg.Name, cfg.ProviderType, cfg.ClientID, cfg.ClientSecret, cfg.AuthURL, cfg.TokenURL, cfg.UserInfoURL, cfg.Scopes, cfg.AutoCreate, cfg.DefaultRole, cfg.IsActive,
	)
	if err != nil {
		return fmt.Errorf("failed to create oauth provider: %w", err)
	}
	id, err := result.LastInsertId()
	if err != nil {
		return fmt.Errorf("failed to get last insert id: %w", err)
	}
	cfg.ID = id
	return nil
}

// Update updates an existing OAuth2 provider config
func (s *OAuth2ConfigStore) Update(cfg *OAuth2Config) error {
	_, err := s.db.Exec(
		`UPDATE oauth_providers SET name=?, provider_type=?, client_id=?, client_secret=?, auth_url=?, token_url=?, userinfo_url=?, scopes=?, auto_create_user=?, default_role=?, is_active=? WHERE id=?`,
		cfg.Name, cfg.ProviderType, cfg.ClientID, cfg.ClientSecret, cfg.AuthURL, cfg.TokenURL, cfg.UserInfoURL, cfg.Scopes, cfg.AutoCreate, cfg.DefaultRole, cfg.IsActive, cfg.ID,
	)
	if err != nil {
		return fmt.Errorf("failed to update oauth provider: %w", err)
	}
	return nil
}

// Delete removes an OAuth2 provider config by ID
func (s *OAuth2ConfigStore) Delete(id int64) error {
	_, err := s.db.Exec("DELETE FROM oauth_providers WHERE id = ?", id)
	if err != nil {
		return fmt.Errorf("failed to delete oauth provider: %w", err)
	}
	return nil
}

// Toggle enables or disables an OAuth2 provider
func (s *OAuth2ConfigStore) Toggle(id int64, isActive bool) error {
	_, err := s.db.Exec("UPDATE oauth_providers SET is_active = ? WHERE id = ?", isActive, id)
	if err != nil {
		return fmt.Errorf("failed to toggle oauth provider: %w", err)
	}
	return nil
}
