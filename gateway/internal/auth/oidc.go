package auth

import (
	"context"

	"github.com/llmgate/llmgate/internal/store"
)

// OIDCProvider implements AuthProvider for OpenID Connect
type OIDCProvider struct {
	OAuth2Provider
}

// NewOIDCProvider creates a new OIDCProvider
func NewOIDCProvider(cfg OAuth2Config, userStore *store.UserStore) *OIDCProvider {
	return &OIDCProvider{
		OAuth2Provider: *NewOAuth2Provider(cfg, userStore),
	}
}

// Type returns the provider type
func (p *OIDCProvider) Type() string {
	return "oidc"
}

// Authenticate performs OIDC authentication (currently delegates to OAuth2 flow)
// Future enhancement: verify id_token signature and claims
func (p *OIDCProvider) Authenticate(ctx context.Context, req *AuthRequest) (*AuthResult, error) {
	// For now, delegate to the OAuth2 implementation
	// In the future, this could verify the id_token and extract claims directly
	return p.OAuth2Provider.Authenticate(ctx, req)
}
