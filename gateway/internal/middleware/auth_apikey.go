package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/service"
)

// APIKeyAuth returns a gin middleware that authenticates requests using API keys
func APIKeyAuth(apiKeyService *service.APIKeyService) gin.HandlerFunc {
	return func(c *gin.Context) {
		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error": gin.H{
					"message": "missing authorization header",
					"type":    "authentication_error",
					"code":    "invalid_api_key",
				},
			})
			return
		}

		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error": gin.H{
					"message": "invalid authorization header format",
					"type":    "authentication_error",
					"code":    "invalid_api_key",
				},
			})
			return
		}

		rawKey := strings.TrimSpace(parts[1])
		if !strings.HasPrefix(rawKey, "sk-") {
			// Not an API key request; pass through for other auth methods
			c.Next()
			return
		}

		// Validate the API key
		apiKey, user, err := apiKeyService.ValidateKey(rawKey)
		if err != nil {
			slog.Error("API key validation error", "error", err)
			c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
				"error": gin.H{
					"message": "internal error during authentication",
					"type":    "internal_error",
				},
			})
			return
		}

		if apiKey == nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error": gin.H{
					"message": "invalid or expired API key",
					"type":    "authentication_error",
					"code":    "invalid_api_key",
				},
			})
			return
		}

		// Check if key's permissions allow the requested model
		// Parse request body to get "model" field
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

		// Check permissions if the key has restrictions
		if apiKey.Permissions != "" && apiKey.Permissions != "[]" {
			var allowedModels []string
			if err := json.Unmarshal([]byte(apiKey.Permissions), &allowedModels); err == nil && len(allowedModels) > 0 {
				if modelID != "" {
					allowed := false
					for _, m := range allowedModels {
						if m == modelID || m == "*" {
							allowed = true
							break
						}
					}
					if !allowed {
						c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
							"error": gin.H{
								"message": "API key does not have permission for model: " + modelID,
								"type":    "permission_error",
								"code":    "model_not_permitted",
							},
						})
						return
					}
				}
			}
		}

		// Set context values. Unbound keys (issued to terminals without a bound
		// user) carry no user_id/username/role; downstream quota/audit/conversation
		// code treats the missing identity as anonymous.
		c.Set("auth_type", "apikey")
		c.Set("api_key_id", apiKey.ID)
		c.Set("api_key_permissions", apiKey.Permissions)
		if user != nil {
			c.Set("user_id", user.ID)
			c.Set("username", user.Username)
			c.Set("role", user.Role)
		}

		c.Next()
	}
}
