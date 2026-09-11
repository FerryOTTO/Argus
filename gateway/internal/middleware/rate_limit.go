package middleware

import (
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/response"
)

// rateLimitEntry tracks request counts for a single key
type rateLimitEntry struct {
	count       int
	windowStart time.Time
}

// rateLimiter is a simple sliding window counter per key
type rateLimiter struct {
	mu      sync.Mutex
	entries map[string]*rateLimitEntry
	limit   int
	window  time.Duration
}

// newRateLimiter creates a rate limiter with the given requests per minute
func newRateLimiter(requestsPerMinute int) *rateLimiter {
	rl := &rateLimiter{
		entries: make(map[string]*rateLimitEntry),
		limit:   requestsPerMinute,
		window:  time.Minute,
	}
	// Start background cleanup
	go rl.cleanup()
	return rl
}

// allow checks if the key is allowed to make a request
func (rl *rateLimiter) allow(key string) bool {
	rl.mu.Lock()
	defer rl.mu.Unlock()

	now := time.Now()
	entry, ok := rl.entries[key]
	if !ok || now.Sub(entry.windowStart) >= rl.window {
		// Reset window
		rl.entries[key] = &rateLimitEntry{count: 1, windowStart: now}
		return true
	}

	if entry.count >= rl.limit {
		return false
	}

	entry.count++
	return true
}

// cleanup periodically removes stale entries
func (rl *rateLimiter) cleanup() {
	ticker := time.NewTicker(2 * time.Minute)
	defer ticker.Stop()
	for range ticker.C {
		rl.mu.Lock()
		now := time.Now()
		for key, entry := range rl.entries {
			if now.Sub(entry.windowStart) >= rl.window {
				delete(rl.entries, key)
			}
		}
		rl.mu.Unlock()
	}
}

// GlobalRateLimit returns a middleware that rate limits requests per IP.
// requestsPerMinute specifies the maximum number of requests per minute per IP.
func GlobalRateLimit(requestsPerMinute int) gin.HandlerFunc {
	rl := newRateLimiter(requestsPerMinute)
	return func(c *gin.Context) {
		ip := c.ClientIP()
		if !rl.allow(ip) {
			response.SendError(c, http.StatusTooManyRequests, response.ErrorTypeRateLimit,
				"Rate limit exceeded. Please try again later.", "rate_limit_exceeded")
			c.Abort()
			return
		}
		c.Next()
	}
}

// UserRateLimit returns a middleware that rate limits requests per user ID.
// Falls back to IP-based limiting if user ID is not available in context.
func UserRateLimit(requestsPerMinute int) gin.HandlerFunc {
	rl := newRateLimiter(requestsPerMinute)
	return func(c *gin.Context) {
		// Try to get user ID from context, fall back to IP
		key := ""
		if userID, exists := c.Get("user_id"); exists {
			key = fmt.Sprintf("user:%v", userID)
		} else {
			key = "ip:" + c.ClientIP()
		}
		if !rl.allow(key) {
			response.SendError(c, http.StatusTooManyRequests, response.ErrorTypeRateLimit,
				"Rate limit exceeded. Please try again later.", "rate_limit_exceeded")
			c.Abort()
			return
		}
		c.Next()
	}
}
