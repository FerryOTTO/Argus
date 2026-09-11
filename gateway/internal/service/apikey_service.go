package service

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/store"
)

// APIKeyService handles API key generation and management
type APIKeyService struct {
	store     *store.APIKeyStore
	userStore *store.UserStore
}

// NewAPIKeyService creates a new APIKeyService
func NewAPIKeyService(store *store.APIKeyStore, userStore *store.UserStore) *APIKeyService {
	return &APIKeyService{store: store, userStore: userStore}
}

// ErrUserNotFound / ErrUserInactive are returned when a manually created key
// references a missing or disabled owning user.
var (
	ErrUserNotFound = errors.New("user not found")
	ErrUserInactive = errors.New("user is inactive")
)

// CreateManualKey creates an admin-issued key that is not linked to any
// terminal (list view shows source = manual). userID may be nil (unowned key);
// when set, the user must exist and be active. Returns the raw key (only
// shown once) and the stored key model.
func (s *APIKeyService) CreateManualKey(name string, userID *int64, permissions []string) (string, *model.APIKey, error) {
	if userID != nil {
		user, err := s.userStore.GetByID(*userID)
		if err != nil {
			return "", nil, fmt.Errorf("failed to load user: %w", err)
		}
		if user == nil {
			return "", nil, ErrUserNotFound
		}
		if !user.IsActive {
			return "", nil, ErrUserInactive
		}
	}
	return s.GenerateKey(userID, nil, name, permissions, nil)
}

// GenerateKey generates a new API key. userID may be nil (unowned key issued to
// a terminal without a bound user); terminalID records the issuing terminal.
// Returns the raw key (only shown once), the API key model, and any error.
func (s *APIKeyService) GenerateKey(userID *int64, terminalID *int64, name string, permissions []string, expiresAt *time.Time) (string, *model.APIKey, error) {
	// Normalise empty / nil whitelists to ["*"] (all models) so the stored
	// JSON is never "null" / "[]" with ambiguous meaning.
	if len(permissions) == 0 {
		permissions = []string{"*"}
	}

	// Generate random key: "sk-" + 32 bytes crypto/rand hex = "sk-" + 64 chars
	randomBytes := make([]byte, 32)
	if _, err := rand.Read(randomBytes); err != nil {
		return "", nil, fmt.Errorf("failed to generate random bytes: %w", err)
	}
	rawKey := "sk-" + hex.EncodeToString(randomBytes)

	// Compute SHA-256 hash of the key
	hash := sha256.Sum256([]byte(rawKey))
	keyHash := hex.EncodeToString(hash[:])

	// Key prefix: first 10 chars for display
	keyPrefix := rawKey[:10]

	// JSON-encode permissions
	permJSON, err := json.Marshal(permissions)
	if err != nil {
		return "", nil, fmt.Errorf("failed to encode permissions: %w", err)
	}

	apiKey := &model.APIKey{
		UserID:      userID,
		TerminalID:  terminalID,
		Name:        name,
		KeyHash:     keyHash,
		KeyPrefix:   keyPrefix,
		Permissions: string(permJSON),
		IsActive:    true,
		ExpiresAt:   expiresAt,
		CreatedAt:   time.Now(),
	}

	if err := s.store.Create(apiKey); err != nil {
		return "", nil, fmt.Errorf("failed to store api key: %w", err)
	}

	return rawKey, apiKey, nil
}

// ValidateKey validates a raw API key and returns the key model and the
// associated user. Keys without an owner (issued to an unbound terminal) are
// still valid and return (key, nil, nil) as long as they are active.
func (s *APIKeyService) ValidateKey(rawKey string) (*model.APIKey, *model.User, error) {
	// Hash the raw key
	hash := sha256.Sum256([]byte(rawKey))
	keyHash := hex.EncodeToString(hash[:])

	// Lookup by hash
	apiKey, err := s.store.GetByHash(keyHash)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to lookup api key: %w", err)
	}
	if apiKey == nil {
		return nil, nil, nil
	}

	// Check if key is active
	if !apiKey.IsActive {
		return nil, nil, nil
	}

	// Check expiration
	if apiKey.ExpiresAt != nil && apiKey.ExpiresAt.Before(time.Now()) {
		return nil, nil, nil
	}

	// Unbound key: no owner to verify against
	if apiKey.UserID == nil {
		return apiKey, nil, nil
	}

	// Load associated user
	user, err := s.userStore.GetByID(*apiKey.UserID)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to load user for api key: %w", err)
	}
	if user == nil {
		return nil, nil, nil
	}

	// Check user is active
	if !user.IsActive {
		return nil, nil, nil
	}

	return apiKey, user, nil
}

// UpdateKeyOwner re-assigns the owning user of a key (nil clears the owner)
func (s *APIKeyService) UpdateKeyOwner(id int64, userID *int64) error {
	return s.store.UpdateOwner(id, userID)
}

// ListKeys returns all API keys for a user
func (s *APIKeyService) ListKeys(userID int64) ([]model.APIKey, error) {
	return s.store.ListByUserID(userID)
}

// ListAllKeys returns all API keys (admin)
func (s *APIKeyService) ListAllKeys() ([]model.APIKey, error) {
	return s.store.ListAll()
}

// UpdateKey edits the display name and the model whitelist of a key.
// Empty permissions are normalised to ["*"] (all models), matching the
// semantics used at issuance time.
func (s *APIKeyService) UpdateKey(id int64, name string, permissions []string) error {
	if len(permissions) == 0 {
		permissions = []string{"*"}
	}
	permJSON, err := json.Marshal(permissions)
	if err != nil {
		return fmt.Errorf("failed to encode permissions: %w", err)
	}
	return s.store.UpdateMeta(id, name, string(permJSON))
}

// DeleteKey removes a key permanently. The caller is responsible for
// unlinking the key from any issuing terminal first.
func (s *APIKeyService) DeleteKey(id int64) error {
	return s.store.Delete(id)
}

// DeactivateKey deactivates an API key
func (s *APIKeyService) DeactivateKey(id int64) error {
	return s.store.Deactivate(id)
}
