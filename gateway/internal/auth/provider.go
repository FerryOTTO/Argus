package auth

import (
	"context"

	"github.com/llmgate/llmgate/internal/model"
)

// AuthRequest represents an authentication request
type AuthRequest struct {
	Username    string `json:"username"`
	Password    string `json:"password"`
	// OAuth2 fields (for future SSO)
	Code        string `json:"code,omitempty"`
	State       string `json:"state,omitempty"`
	RedirectURI string `json:"redirect_uri,omitempty"`
}

// AuthResult represents the result of an authentication attempt
type AuthResult struct {
	User *model.User
	// For SSO redirect scenarios
	RedirectURL string
}

// AuthProvider defines the interface for authentication providers
type AuthProvider interface {
	Name() string
	Type() string // "local" | "oauth2" | "oidc"
	Authenticate(ctx context.Context, req *AuthRequest) (*AuthResult, error)
	IsEnabled() bool
}
