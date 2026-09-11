package auth

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/llmgate/llmgate/internal/store"
)

// LocalAuth implements AuthProvider for local username/password authentication
type LocalAuth struct {
	userStore *store.UserStore
}

// NewLocalAuth creates a new LocalAuth instance
func NewLocalAuth(userStore *store.UserStore) *LocalAuth {
	return &LocalAuth{userStore: userStore}
}

// Name returns the provider name
func (l *LocalAuth) Name() string {
	return "local"
}

// Type returns the provider type
func (l *LocalAuth) Type() string {
	return "local"
}

// IsEnabled returns true as local auth is always enabled
func (l *LocalAuth) IsEnabled() bool {
	return true
}

// Authenticate validates username and password against the local user store
func (l *LocalAuth) Authenticate(ctx context.Context, req *AuthRequest) (*AuthResult, error) {
	if req.Username == "" || req.Password == "" {
		return nil, fmt.Errorf("username and password are required")
	}

	user, err := l.userStore.GetByUsername(req.Username)
	if err != nil {
		slog.Error("failed to look up user", "username", req.Username, "error", err)
		return nil, fmt.Errorf("authentication failed")
	}
	if user == nil {
		return nil, fmt.Errorf("invalid username or password")
	}

	if !user.IsActive {
		return nil, fmt.Errorf("user account is inactive")
	}

	if err := ComparePassword(user.PasswordHash, req.Password); err != nil {
		return nil, fmt.Errorf("invalid username or password")
	}

	return &AuthResult{User: user}, nil
}
