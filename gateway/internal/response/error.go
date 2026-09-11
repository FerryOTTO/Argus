package response

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// ErrorResponse represents an OpenAI-compatible error response
type ErrorResponse struct {
	Error ErrorDetail `json:"error"`
}

// ErrorDetail contains the error details
type ErrorDetail struct {
	Message string  `json:"message"`
	Type    string  `json:"type"`
	Code    *string `json:"code,omitempty"`
}

// Error type constants
const (
	ErrorTypeInvalidRequest = "invalid_request_error"
	ErrorTypeAuthentication = "authentication_error"
	ErrorTypePermission     = "permission_error"
	ErrorTypeNotFound       = "not_found_error"
	ErrorTypeRateLimit      = "rate_limit_error"
	ErrorTypeUpstream       = "upstream_error"
	ErrorTypeInternal       = "internal_error"
)

// SendError sends an OpenAI-compatible error response
func SendError(c *gin.Context, statusCode int, errType string, message string, code string) {
	resp := ErrorResponse{
		Error: ErrorDetail{
			Message: message,
			Type:    errType,
		},
	}
	if code != "" {
		resp.Error.Code = &code
	}
	c.JSON(statusCode, resp)
}

// SendUpstreamError wraps upstream errors in OpenAI format
func SendUpstreamError(c *gin.Context, statusCode int, message string) {
	SendError(c, statusCode, ErrorTypeUpstream, message, "")
}

// SendModelNotFound sends a 404 error for unknown models
func SendModelNotFound(c *gin.Context, modelID string) {
	SendError(c, http.StatusNotFound, ErrorTypeNotFound, "The model '"+modelID+"' does not exist or is not active", "model_not_found")
}
