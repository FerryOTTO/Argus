package auth

import "sync"

// Registry manages multiple auth providers
type Registry struct {
	mu        sync.RWMutex
	providers map[string]AuthProvider
}

// NewRegistry creates a new auth provider registry
func NewRegistry() *Registry {
	return &Registry{
		providers: make(map[string]AuthProvider),
	}
}

// Register adds an auth provider to the registry
func (r *Registry) Register(provider AuthProvider) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.providers[provider.Name()] = provider
}

// Get retrieves an auth provider by name
func (r *Registry) Get(name string) (AuthProvider, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	p, ok := r.providers[name]
	return p, ok
}

// List returns all registered auth providers
func (r *Registry) List() []AuthProvider {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]AuthProvider, 0, len(r.providers))
	for _, p := range r.providers {
		result = append(result, p)
	}
	return result
}

// GetEnabled returns only the enabled auth providers
func (r *Registry) GetEnabled() []AuthProvider {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]AuthProvider, 0)
	for _, p := range r.providers {
		if p.IsEnabled() {
			result = append(result, p)
		}
	}
	return result
}
