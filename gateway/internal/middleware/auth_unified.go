package middleware

import (
	"log/slog"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/auth"
	"github.com/llmgate/llmgate/internal/service"
)

// UnifiedAuth returns a gin middleware that routes authentication based on the
// Authorization header. Tokens starting with "sk-" are treated as API key auth,
// otherwise JWT auth is used.
func UnifiedAuth(jwtSecret string, apiKeyService *service.APIKeyService) gin.HandlerFunc {
	jwtAuth := AuthRequired(jwtSecret)
	apiKeyAuth := APIKeyAuth(apiKeyService)

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

		token := strings.TrimSpace(parts[1])

		// Check if this is an API key request
		if strings.HasPrefix(token, "sk-") {
			slog.Debug("API key authentication path selected")
			apiKeyAuth(c)
			return
		}

		// JWT authentication path
		c.Set("auth_type", "jwt")
		jwtAuth(c)
	}
}

// getJWTClaims is a helper to extract and validate JWT claims from context
func getJWTClaims(c *gin.Context, jwtSecret string) (*auth.Claims, error) {
	authHeader := c.GetHeader("Authorization")
	parts := strings.SplitN(authHeader, " ", 2)
	if len(parts) != 2 {
		return nil, http.ErrAbortHandler
	}
	return auth.ValidateToken(strings.TrimSpace(parts[1]), jwtSecret)
}
