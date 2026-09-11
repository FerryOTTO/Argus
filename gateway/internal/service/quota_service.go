package service

import (
	"fmt"
	"time"

	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/store"
)

// QuotaService handles quota checking and usage recording
type QuotaService struct {
	quotaStore *store.QuotaStore
}

// NewQuotaService creates a new QuotaService
func NewQuotaService(quotaStore *store.QuotaStore) *QuotaService {
	return &QuotaService{quotaStore: quotaStore}
}

// CheckQuota checks if the user has exceeded any quota for the given model
// Returns nil if allowed, error if quota exceeded
func (s *QuotaService) CheckQuota(userID int64, modelID string) error {
	// Load quotas for user (both specific model and global '*')
	quotas, err := s.quotaStore.GetByUserAndModel(userID, modelID)
	if err != nil {
		return fmt.Errorf("failed to check quota: %w", err)
	}

	// If no quotas defined for user, allow (no restriction)
	if len(quotas) == 0 {
		return nil
	}

	// For each quota, check current usage against limit
	for _, q := range quotas {
		currentUsage, err := s.quotaStore.GetCurrentWindowUsage(userID, q.ModelID, q.QuotaType)
		if err != nil {
			return fmt.Errorf("failed to get current usage: %w", err)
		}

		if currentUsage >= q.LimitValue {
			return fmt.Errorf("quota exceeded: %s limit is %.0f for %s", q.QuotaType, q.LimitValue, q.ModelID)
		}
	}

	return nil
}

// RecordUsage inserts a usage record (apiKeyID/userID may be nil: JWT calls carry no key, unowned keys carry no user)
func (s *QuotaService) RecordUsage(apiKeyID *int64, userID *int64, modelID string, promptTokens, completionTokens int, latencyMs int64, statusCode int, clientIP string) error {
	record := &model.UsageRecord{
		APIKeyID:         apiKeyID,
		UserID:           userID,
		ModelID:          modelID,
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		LatencyMs:        latencyMs,
		StatusCode:       statusCode,
		CreatedAt:        time.Now(),
	}
	if clientIP != "" {
		record.ClientIP = &clientIP
	}

	return s.quotaStore.RecordUsage(record)
}

// GetUsage retrieves usage records for a user since a given time
func (s *QuotaService) GetUsage(userID int64, since time.Time) ([]model.UsageRecord, error) {
	return s.quotaStore.GetUsageByUserID(userID, since)
}
