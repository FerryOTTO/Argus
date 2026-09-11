package middleware

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

// AdminRequired returns a gin middleware that restricts access to admin users only
func AdminRequired() gin.HandlerFunc {
	return func(c *gin.Context) {
		role, exists := c.Get("role")
		if !exists {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error": gin.H{
					"message": "access denied: admin role required",
					"type":    "authorization_error",
					"code":    "forbidden",
				},
			})
			return
		}

		if roleStr, ok := role.(string); !ok || roleStr != "admin" {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error": gin.H{
					"message": "access denied: admin role required",
					"type":    "authorization_error",
					"code":    "forbidden",
				},
			})
			return
		}

		c.Next()
	}
}

// ActiveUserRequired returns a gin middleware that ensures the authenticated user is active
func ActiveUserRequired() gin.HandlerFunc {
	return func(c *gin.Context) {
		// Check that user_id exists in context (set by auth middleware)
		userID, exists := c.Get("user_id")
		if !exists {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error": gin.H{
					"message": "authentication required",
					"type":    "authentication_error",
					"code":    "invalid_api_key",
				},
			})
			return
		}

		// Ensure user_id is valid (non-zero)
		if id, ok := userID.(int64); !ok || id == 0 {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error": gin.H{
					"message": "invalid user identity",
					"type":    "authentication_error",
					"code":    "invalid_api_key",
				},
			})
			return
		}

		c.Next()
	}
}
