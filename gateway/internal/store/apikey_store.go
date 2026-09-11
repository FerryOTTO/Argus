package store

import (
	"database/sql"
	"errors"
	"fmt"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
)

// ErrAPIKeyNotFound is returned when an api key row does not exist
var ErrAPIKeyNotFound = errors.New("api key not found")

// APIKeyStore handles API key database operations
type APIKeyStore struct {
	db *sqlx.DB
}

// NewAPIKeyStore creates a new APIKeyStore
func NewAPIKeyStore(db *sqlx.DB) *APIKeyStore {
	return &APIKeyStore{db: db}
}

// Create inserts a new API key (user_id / terminal_id are nullable: unowned keys)
func (s *APIKeyStore) Create(key *model.APIKey) error {
	query := `
		INSERT INTO api_keys (user_id, terminal_id, name, key_hash, key_prefix, permissions, is_active, expires_at, created_at)
		VALUES (:user_id, :terminal_id, :name, :key_hash, :key_prefix, :permissions, :is_active, :expires_at, :created_at)
	`
	result, err := s.db.NamedExec(query, key)
	if err != nil {
		return fmt.Errorf("failed to create api key: %w", err)
	}

	id, err := result.LastInsertId()
	if err != nil {
		return fmt.Errorf("failed to get last insert id: %w", err)
	}
	key.ID = id

	return nil
}

// GetByHash looks up an API key by its SHA-256 hash
func (s *APIKeyStore) GetByHash(keyHash string) (*model.APIKey, error) {
	var key model.APIKey
	query := `SELECT * FROM api_keys WHERE key_hash = ?`
	if err := s.db.Get(&key, query, keyHash); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get api key by hash: %w", err)
	}
	return &key, nil
}

// GetByID retrieves an API key by ID
func (s *APIKeyStore) GetByID(id int64) (*model.APIKey, error) {
	var key model.APIKey
	query := `SELECT * FROM api_keys WHERE id = ?`
	if err := s.db.Get(&key, query, id); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get api key by id: %w", err)
	}
	return &key, nil
}

// ListByUserID returns all API keys for a specific user
func (s *APIKeyStore) ListByUserID(userID int64) ([]model.APIKey, error) {
	var keys []model.APIKey
	query := `SELECT * FROM api_keys WHERE user_id = ? ORDER BY id DESC`
	if err := s.db.Select(&keys, query, userID); err != nil {
		return nil, fmt.Errorf("failed to list api keys by user: %w", err)
	}
	return keys, nil
}

// ListAll returns all API keys (admin view), JOIN users / agent_terminals to
// expose the owning user and the issuing terminal for display purposes.
func (s *APIKeyStore) ListAll() ([]model.APIKey, error) {
	var keys []model.APIKey
	query := `
		SELECT k.id, k.user_id, k.terminal_id, k.name, k.key_hash, k.key_prefix,
		       k.permissions, k.is_active, k.expires_at, k.created_at,
		       u.username AS owner_username, t.name AS terminal_name
		FROM api_keys k
		LEFT JOIN users u ON u.id = k.user_id
		LEFT JOIN agent_terminals t ON t.id = k.terminal_id
		ORDER BY k.id DESC
	`
	if err := s.db.Select(&keys, query); err != nil {
		return nil, fmt.Errorf("failed to list all api keys: %w", err)
	}
	return keys, nil
}

// UpdateOwner re-assigns (or clears, when userID is nil) the owning user of a key.
// Keys issued to a terminal track the terminal's bound user, see admin_terminal.go.
func (s *APIKeyStore) UpdateOwner(id int64, userID *int64) error {
	query := `UPDATE api_keys SET user_id = ? WHERE id = ?`
	result, err := ExecWithRetry(s.db, query, userID, id)
	if err != nil {
		return fmt.Errorf("failed to update api key owner: %w", err)
	}
	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("%w", ErrAPIKeyNotFound)
	}
	return nil
}

// UpdateMeta updates editable display metadata of a key: name and the model
// whitelist (permissions, JSON array). Owner / terminal / expiry are managed
// by their own flows and must not be changed here.
func (s *APIKeyStore) UpdateMeta(id int64, name, permissions string) error {
	query := `UPDATE api_keys SET name = ?, permissions = ? WHERE id = ?`
	result, err := ExecWithRetry(s.db, query, name, permissions, id)
	if err != nil {
		return fmt.Errorf("failed to update api key: %w", err)
	}
	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("%w", ErrAPIKeyNotFound)
	}
	return nil
}

// Delete removes a key row permanently. Callers must unlink the key from any
// terminal (ClearLLMKeyByKeyID) first, otherwise the FK on
// agent_terminals.llm_api_key_id rejects the delete.
func (s *APIKeyStore) Delete(id int64) error {
	// conversation_logs.api_key_id references api_keys(id) with FK enforcement ON.
	// Unlink session logs first so deleting a used key does not hit FK constraint.
	if _, err := ExecWithRetry(s.db, `UPDATE conversation_logs SET api_key_id = NULL WHERE api_key_id = ?`, id); err != nil {
		return err
	}
	if _, err := ExecWithRetry(s.db, `UPDATE usage_records SET api_key_id = NULL WHERE api_key_id = ?`, id); err != nil {
		return err
	}
	query := `DELETE FROM api_keys WHERE id = ?`
	result, err := ExecWithRetry(s.db, query, id)
	if err != nil {
		return fmt.Errorf("failed to delete api key: %w", err)
	}
	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("%w", ErrAPIKeyNotFound)
	}
	return nil
}

// Deactivate performs a soft delete by setting is_active to 0
func (s *APIKeyStore) Deactivate(id int64) error {
	query := `UPDATE api_keys SET is_active = 0 WHERE id = ?`
	result, err := ExecWithRetry(s.db, query, id)
	if err != nil {
		return fmt.Errorf("failed to deactivate api key: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("%w", ErrAPIKeyNotFound)
	}

	return nil
}
