package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/store"
)

// responseWriter wraps gin.ResponseWriter to capture the status code
type responseWriter struct {
	gin.ResponseWriter
	statusCode int
}

func newResponseWriter(w gin.ResponseWriter) *responseWriter {
	return &responseWriter{ResponseWriter: w, statusCode: http.StatusOK}
}

func (rw *responseWriter) WriteHeader(code int) {
	rw.statusCode = code
	rw.ResponseWriter.WriteHeader(code)
}

// AuditLog returns a gin middleware that records audit log entries asynchronously
func AuditLog(auditStore *store.AuditStore) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()

		// Wrap response writer to capture status code
		w := newResponseWriter(c.Writer)
		c.Writer = w

		// Try to capture model_id from request body without consuming it
		var modelID *string
		if c.Request.Body != nil {
			bodyBytes, err := io.ReadAll(c.Request.Body)
			if err == nil {
				c.Request.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))
				var body map[string]interface{}
				if err := json.Unmarshal(bodyBytes, &body); err == nil {
					if m, ok := body["model"].(string); ok && m != "" {
						modelID = &m
					}
				}
			}
		}

		// Process request
		c.Next()

		// Build audit log entry
		latency := time.Since(start).Milliseconds()
		action := deriveAction(c.FullPath(), c.Request.URL.Path)

		entry := &model.AuditLog{
			UserID:      getUserIDFromContext(c),
			RequestPath: c.Request.URL.Path,
			StatusCode:  w.statusCode,
			LatencyMs:   latency,
			Action:      action,
			ModelID:     modelID,
			CreatedAt:   start,
		}

		// Extract API key ID if present
		if keyID, exists := c.Get("api_key_id"); exists {
			if id, ok := keyID.(int64); ok {
				entry.APIKeyID = &id
			}
		}

		// Extract client IP
		clientIP := c.ClientIP()
		if clientIP != "" {
			entry.ClientIP = &clientIP
		}

		// Extract user agent
		ua := c.Request.UserAgent()
		if ua != "" {
			entry.UserAgent = &ua
		}

		// Extract token counts from context (set by proxy handler after upstream response)
		if pt, exists := c.Get("prompt_tokens"); exists {
			if v, ok := pt.(int); ok {
				entry.PromptTokens = v
			}
		}
		if ct, exists := c.Get("completion_tokens"); exists {
			if v, ok := ct.(int); ok {
				entry.CompletionTokens = v
			}
		}

		// Non-blocking send to audit store
		auditStore.Log(entry)
	}
}

// deriveAction maps request paths to human-readable action names
func deriveAction(fullPath, requestPath string) string {
	// Use fullPath (route pattern) if available, otherwise fall back to requestPath
	path := fullPath
	if path == "" {
		path = requestPath
	}

	// Remove leading slash
	path = strings.TrimPrefix(path, "/")

	// Map common API paths to actions
	switch {
	case strings.HasPrefix(path, "v1/chat/completions"):
		return "chat_completion"
	case strings.HasPrefix(path, "v1/completions"):
		return "completion"
	case strings.HasPrefix(path, "v1/models"):
		return "list_models"
	case strings.HasPrefix(path, "v1/embeddings"):
		return "embedding"
	case strings.HasPrefix(path, "api/admin/providers"):
		return "admin_provider"
	case strings.HasPrefix(path, "api/admin/users"):
		return "admin_user"
	case strings.HasPrefix(path, "api/admin/api-keys"):
		return "admin_apikey"
	case strings.HasPrefix(path, "api/admin/quotas"):
		return "admin_quota"
	case strings.HasPrefix(path, "api/admin/audit-logs"):
		return "admin_audit"
	case strings.HasPrefix(path, "api/admin/dashboard"):
		return "admin_dashboard"
	case strings.HasPrefix(path, "api/user/api-keys"):
		return "user_apikey"
	case strings.HasPrefix(path, "api/user/usage"):
		return "user_usage"
	case strings.HasPrefix(path, "api/auth"):
		return "auth"
	default:
		return "unknown"
	}
}

// getUserIDFromContext extracts user_id from gin context safely
func getUserIDFromContext(c *gin.Context) int64 {
	if v, exists := c.Get("user_id"); exists {
		switch id := v.(type) {
		case int64:
			return id
		case float64:
			return int64(id)
		default:
			slog.Warn("unexpected user_id type in context", "type", v)
		}
	}
	return 0
}
