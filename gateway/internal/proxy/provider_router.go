package proxy

import (
	"fmt"
	"log/slog"
	"sync"

	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/store"
)

// ProviderRouter routes model requests to the correct provider
type ProviderRouter struct {
	mu            sync.RWMutex
	modelMap      map[string]*model.Provider // model_id -> provider
	providerMap   map[string]string          // model_id -> provider_name
	providerStore *store.ProviderStore
}

// NewProviderRouter creates a new ProviderRouter
func NewProviderRouter(providerStore *store.ProviderStore) *ProviderRouter {
	return &ProviderRouter{
		modelMap:      make(map[string]*model.Provider),
		providerMap:   make(map[string]string),
		providerStore: providerStore,
	}
}

// LoadModels loads all active models and builds the model->provider mapping.
// Call this on startup and when providers/models change.
func (r *ProviderRouter) LoadModels() error {
	models, err := r.providerStore.ListAllActiveModels()
	if err != nil {
		return fmt.Errorf("failed to load active models: %w", err)
	}

	// Build provider lookup cache
	providerCache := make(map[int64]*model.Provider)
	providers, err := r.providerStore.ListProviders()
	if err != nil {
		return fmt.Errorf("failed to list providers: %w", err)
	}
	for i := range providers {
		providerCache[providers[i].ID] = &providers[i]
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	// Clear existing mappings
	r.modelMap = make(map[string]*model.Provider)
	r.providerMap = make(map[string]string)

	for _, m := range models {
		p, ok := providerCache[m.ProviderID]
		if !ok {
			slog.Warn("provider not found for model", "model_id", m.ModelID, "provider_id", m.ProviderID)
			continue
		}
		r.modelMap[m.ModelID] = p
		r.providerMap[m.ModelID] = p.Name
	}

	slog.Info("loaded model routing table", "model_count", len(r.modelMap))
	return nil
}

// Route returns the provider config for a given model_id
func (r *ProviderRouter) Route(modelID string) (*model.Provider, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	provider, ok := r.modelMap[modelID]
	if !ok {
		return nil, fmt.Errorf("model %q not found or not active", modelID)
	}
	return provider, nil
}

// GetAvailableModels returns a list of all active model IDs
func (r *ProviderRouter) GetAvailableModels() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	models := make([]string, 0, len(r.modelMap))
	for id := range r.modelMap {
		models = append(models, id)
	}
	return models
}

// GetProviderNames returns the model_id -> provider_name mapping
func (r *ProviderRouter) GetProviderNames() map[string]string {
	r.mu.RLock()
	defer r.mu.RUnlock()

	result := make(map[string]string, len(r.providerMap))
	for k, v := range r.providerMap {
		result[k] = v
	}
	return result
}
