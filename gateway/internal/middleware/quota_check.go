package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/response"
	"github.com/llmgate/llmgate/internal/service"
)

// QuotaCheck returns a gin middleware that checks quota before allowing the request
func QuotaCheck(quotaService *service.QuotaService) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Only applies to /v1/* routes
		if !isV1Route(c.FullPath()) {
			c.Next()
			return
		}

		// Extract user_id from context (set by auth middleware)
		userIDVal, exists := c.Get("user_id")
		if !exists {
			c.Next()
			return
		}

		userID, ok := userIDVal.(int64)
		if !ok || userID == 0 {
			c.Next()
			return
		}

		// Extract model from request body (need to read and re-set body)
		var modelID string
		if c.Request.Body != nil {
			bodyBytes, err := io.ReadAll(c.Request.Body)
			if err == nil {
				// Restore the body for downstream handlers
				c.Request.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))

				var body map[string]interface{}
				if err := json.Unmarshal(bodyBytes, &body); err == nil {
					if m, ok := body["model"].(string); ok {
						modelID = m
					}
				}
			}
		}

		if modelID == "" {
			// No model specified, skip quota check
			c.Next()
			return
		}

		// Check quota
		if err := quotaService.CheckQuota(userID, modelID); err != nil {
			response.SendError(c, http.StatusTooManyRequests, response.ErrorTypeRateLimit,
				"Quota exceeded. "+err.Error(), "quota_exceeded")
			c.Abort()
			return
		}

		// Store start time in context for latency calculation
		c.Set("start_time", time.Now())

		c.Next()
	}
}

// isV1Route checks if the request is for a /v1/* route
func isV1Route(fullPath string) bool {
	return len(fullPath) >= 3 && fullPath[:3] == "/v1"
}
