package middleware

import (
	"log/slog"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/crypto"
	"github.com/llmgate/llmgate/internal/store"
)

// TelemetryAuth validates the per-terminal Bearer token on /telemetry/v1 routes
// (excluding /register, which authenticates with a registration code instead).
// On success the resolved terminal is attached to the context.
func TelemetryAuth(terminalStore *store.TerminalStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error": gin.H{
					"message": "missing authorization header",
					"type":    "authentication_error",
					"code":    "invalid_telemetry_token",
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
					"code":    "invalid_telemetry_token",
				},
			})
			return
		}

		token := strings.TrimSpace(parts[1])
		if token == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error": gin.H{
					"message": "empty token",
					"type":    "authentication_error",
					"code":    "invalid_telemetry_token",
				},
			})
			return
		}

		terminal, err := terminalStore.FindActiveByTokenHash(crypto.HashSecret(token))
		if err != nil {
			slog.Error("telemetry auth lookup failed", "error", err)
			c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
				"error": gin.H{
					"message": "internal error",
					"type":    "internal_error",
				},
			})
			return
		}
		if terminal == nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error": gin.H{
					"message": "invalid or revoked token",
					"type":    "authentication_error",
					"code":    "invalid_telemetry_token",
				},
			})
			return
		}

		c.Set("terminal_id", terminal.ID)
		c.Set("terminal_name", terminal.Name)
		c.Next()
	}
}
