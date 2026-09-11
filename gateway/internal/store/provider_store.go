package store

import (
	"database/sql"
	"errors"
	"fmt"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/crypto"
	"github.com/llmgate/llmgate/internal/model"
)

// ProviderStore handles provider and model database operations
type ProviderStore struct {
	db        *sqlx.DB
	encryptor *crypto.Encryptor
}

// NewProviderStore creates a new ProviderStore
func NewProviderStore(db *sqlx.DB, encryptor *crypto.Encryptor) *ProviderStore {
	return &ProviderStore{db: db, encryptor: encryptor}
}

// CreateProvider inserts a new provider
func (s *ProviderStore) CreateProvider(provider *model.Provider) error {
	now := time.Now()
	provider.CreatedAt = now
	provider.UpdatedAt = now

	// Encrypt API key before storing
	encryptedKey, err := s.encryptor.Encrypt(provider.APIKey)
	if err != nil {
		return fmt.Errorf("failed to encrypt api key: %w", err)
	}

	query := `
		INSERT INTO providers (name, display_name, provider_type, api_base_url, api_key, is_active, created_at, updated_at)
		VALUES (:name, :display_name, :provider_type, :api_base_url, :api_key, :is_active, :created_at, :updated_at)
	`
	// Use a copy for DB insert with encrypted key
	dbProvider := *provider
	dbProvider.APIKey = encryptedKey
	result, err := s.db.NamedExec(query, &dbProvider)
	if err != nil {
		return fmt.Errorf("failed to create provider: %w", err)
	}

	id, err := result.LastInsertId()
	if err != nil {
		return fmt.Errorf("failed to get last insert id: %w", err)
	}
	provider.ID = id

	return nil
}

// GetProvider retrieves a provider by ID
func (s *ProviderStore) GetProvider(id int64) (*model.Provider, error) {
	var provider model.Provider
	query := `SELECT * FROM providers WHERE id = ?`
	if err := s.db.Get(&provider, query, id); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get provider: %w", err)
	}
	// Decrypt API key
	decryptedKey, err := s.encryptor.Decrypt(provider.APIKey)
	if err != nil {
		return nil, fmt.Errorf("failed to decrypt api key: %w", err)
	}
	provider.APIKey = decryptedKey
	return &provider, nil
}

// ListProviders retrieves all active providers
func (s *ProviderStore) ListProviders() ([]model.Provider, error) {
	var providers []model.Provider
	query := `SELECT * FROM providers WHERE is_active = 1 ORDER BY name`
	if err := s.db.Select(&providers, query); err != nil {
		return nil, fmt.Errorf("failed to list providers: %w", err)
	}
	// Decrypt API keys
	for i := range providers {
		decryptedKey, err := s.encryptor.Decrypt(providers[i].APIKey)
		if err != nil {
			return nil, fmt.Errorf("failed to decrypt api key for provider %d: %w", providers[i].ID, err)
		}
		providers[i].APIKey = decryptedKey
	}
	return providers, nil
}

// UpdateProvider updates provider fields
func (s *ProviderStore) UpdateProvider(provider *model.Provider) error {
	provider.UpdatedAt = time.Now()

	// Encrypt API key before storing
	encryptedKey, err := s.encryptor.Encrypt(provider.APIKey)
	if err != nil {
		return fmt.Errorf("failed to encrypt api key: %w", err)
	}

	query := `
		UPDATE providers
		SET name = :name, display_name = :display_name, provider_type = :provider_type,
		    api_base_url = :api_base_url, api_key = :api_key, is_active = :is_active, updated_at = :updated_at
		WHERE id = :id
	`
	// Use a copy for DB update with encrypted key
	dbProvider := *provider
	dbProvider.APIKey = encryptedKey
	result, err := s.db.NamedExec(query, &dbProvider)
	if err != nil {
		return fmt.Errorf("failed to update provider: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("provider not found")
	}

	return nil
}

// DeleteProvider performs a soft delete by setting is_active to 0
func (s *ProviderStore) DeleteProvider(id int64) error {
	query := `UPDATE providers SET is_active = 0, updated_at = ? WHERE id = ?`
	result, err := ExecWithRetry(s.db, query, time.Now(), id)
	if err != nil {
		return fmt.Errorf("failed to delete provider: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("provider not found")
	}

	return nil
}

// CreateModel inserts a new model
// ErrModelExists 表示该供应商下同名模型已处于启用状态。
var ErrModelExists = errors.New("model already exists")

// CreateModel 新增模型；若同名模型曾被软删除则直接复活（避免 UNIQUE 冲突），
// 若已处于启用状态则返回 ErrModelExists（调用方应转 409）。
func (s *ProviderStore) CreateModel(m *model.Model) error {
	var existing struct {
		ID       int64 `db:"id"`
		IsActive bool  `db:"is_active"`
	}
	err := s.db.Get(&existing, `SELECT id, is_active FROM models WHERE provider_id = ? AND model_id = ?`, m.ProviderID, m.ModelID)
	if err != nil && err != sql.ErrNoRows {
		return fmt.Errorf("failed to check existing model: %w", err)
	}
	if err == nil {
		if existing.IsActive {
			return ErrModelExists
		}
		if _, err := ExecWithRetry(s.db, `UPDATE models SET is_active = 1, display_name = ? WHERE id = ?`, m.DisplayName, existing.ID); err != nil {
			return fmt.Errorf("failed to reactivate model: %w", err)
		}
		m.ID = existing.ID
		m.IsActive = true
		return nil
	}

	m.CreatedAt = time.Now()

	query := `
		INSERT INTO models (provider_id, model_id, display_name, is_active, created_at)
		VALUES (:provider_id, :model_id, :display_name, :is_active, :created_at)
	`
	result, err := s.db.NamedExec(query, m)
	if err != nil {
		return fmt.Errorf("failed to create model: %w", err)
	}

	id, err := result.LastInsertId()
	if err != nil {
		return fmt.Errorf("failed to get last insert id: %w", err)
	}
	m.ID = id

	return nil
}

// ListModelsByProvider retrieves all models for a specific provider
func (s *ProviderStore) ListModelsByProvider(providerID int64) ([]model.Model, error) {
	var models []model.Model
	query := `SELECT * FROM models WHERE provider_id = ? AND is_active = 1 ORDER BY model_id`
	if err := s.db.Select(&models, query, providerID); err != nil {
		return nil, fmt.Errorf("failed to list models by provider: %w", err)
	}
	return models, nil
}

// ListAllActiveModels retrieves all active models with their provider information
func (s *ProviderStore) ListAllActiveModels() ([]model.ModelWithProvider, error) {
	var models []model.ModelWithProvider
	query := `
		SELECT m.*, p.name as provider_name, p.provider_type
		FROM models m
		JOIN providers p ON m.provider_id = p.id
		WHERE m.is_active = 1 AND p.is_active = 1
		ORDER BY p.name, m.model_id
	`
	if err := s.db.Select(&models, query); err != nil {
		return nil, fmt.Errorf("failed to list all active models: %w", err)
	}
	return models, nil
}

// GetModelByID retrieves a model by ID
func (s *ProviderStore) GetModelByID(id int64) (*model.Model, error) {
	var m model.Model
	query := `SELECT * FROM models WHERE id = ?`
	if err := s.db.Get(&m, query, id); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get model by id: %w", err)
	}
	return &m, nil
}

// DeleteModel performs a soft delete on a model
func (s *ProviderStore) DeleteModel(id int64) error {
	query := `UPDATE models SET is_active = 0 WHERE id = ?`
	result, err := ExecWithRetry(s.db, query, id)
	if err != nil {
		return fmt.Errorf("failed to delete model: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("model not found")
	}

	return nil
}
