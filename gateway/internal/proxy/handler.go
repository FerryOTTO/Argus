package proxy

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/internal/model"
	"github.com/llmgate/llmgate/internal/response"
	"github.com/llmgate/llmgate/internal/service"
	"github.com/llmgate/llmgate/internal/store"
)

func init() {
	// Force HTTP/1.1 globally — some LLM providers (e.g. DeepSeek) have HTTP/2 compatibility issues
	http.DefaultTransport.(*http.Transport).TLSNextProto = map[string]func(string, *tls.Conn) http.RoundTripper{}
}

// ProxyHandler handles OpenAI-compatible API requests
type ProxyHandler struct {
	router       *ProviderRouter
	convStore    *store.ConversationStore
	convEnabled  bool
	quotaService *service.QuotaService
}

// NewProxyHandler creates a new ProxyHandler
func NewProxyHandler(router *ProviderRouter, convStore *store.ConversationStore, convEnabled bool, quotaService *service.QuotaService) *ProxyHandler {
	return &ProxyHandler{router: router, convStore: convStore, convEnabled: convEnabled, quotaService: quotaService}
}

// responseCaptureWriter wraps gin.ResponseWriter to capture the response body
type responseCaptureWriter struct {
	gin.ResponseWriter
	body *bytes.Buffer
}

func (w *responseCaptureWriter) Write(b []byte) (int, error) {
	w.body.Write(b)
	return w.ResponseWriter.Write(b)
}

// chatRequest is used to extract the model field from the request body
type chatRequest struct {
	Model string `json:"model"`
}

// HandleChatCompletions handles POST /v1/chat/completions
func (h *ProxyHandler) HandleChatCompletions(c *gin.Context) {
	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		response.SendError(c, http.StatusBadRequest, response.ErrorTypeInvalidRequest, "Failed to read request body", "invalid_body")
		return
	}

	var req chatRequest
	if err := json.Unmarshal(body, &req); err != nil {
		response.SendError(c, http.StatusBadRequest, response.ErrorTypeInvalidRequest, "Invalid JSON in request body", "invalid_json")
		return
	}

	if req.Model == "" {
		response.SendError(c, http.StatusBadRequest, response.ErrorTypeInvalidRequest, "Missing required field: model", "missing_model")
		return
	}

	h.proxyRequest(c, req.Model, body, "/v1/chat/completions")
}

// HandleCompletions handles POST /v1/completions
func (h *ProxyHandler) HandleCompletions(c *gin.Context) {
	body, err := io.ReadAll(c.Request.Body)
	if err != nil {
		response.SendError(c, http.StatusBadRequest, response.ErrorTypeInvalidRequest, "Failed to read request body", "invalid_body")
		return
	}

	var req chatRequest
	if err := json.Unmarshal(body, &req); err != nil {
		response.SendError(c, http.StatusBadRequest, response.ErrorTypeInvalidRequest, "Invalid JSON in request body", "invalid_json")
		return
	}

	if req.Model == "" {
		response.SendError(c, http.StatusBadRequest, response.ErrorTypeInvalidRequest, "Missing required field: model", "missing_model")
		return
	}

	h.proxyRequest(c, req.Model, body, "/v1/completions")
}

// HandleListModels handles GET /v1/models
func (h *ProxyHandler) HandleListModels(c *gin.Context) {
	models := h.router.GetAvailableModels()
	providerNames := h.router.GetProviderNames()

	// API key 白名单：key permissions（JSON 模型数组，[] 或 "*" 不限）命中时裁剪列表
	if permsVal, exists := c.Get("api_key_permissions"); exists {
		if permsStr, ok := permsVal.(string); ok && permsStr != "" && permsStr != "[]" {
			var allowed []string
			if err := json.Unmarshal([]byte(permsStr), &allowed); err == nil && len(allowed) > 0 {
				set := make(map[string]bool, len(allowed))
				for _, m := range allowed {
					set[m] = true
				}
				filtered := make([]string, 0, len(models))
				for _, m := range models {
					if set[m] || set["*"] {
						filtered = append(filtered, m)
					}
				}
				models = filtered
			}
		}
	}

	resp := response.BuildModelListResponse(models, providerNames)
	c.JSON(http.StatusOK, resp)
}

// proxyRequest is the internal helper that does the actual proxying
func (h *ProxyHandler) proxyRequest(c *gin.Context, modelID string, body []byte, endpoint string) {
	// Route to the correct provider
	provider, err := h.router.Route(modelID)
	if err != nil {
		response.SendModelNotFound(c, modelID)
		return
	}

	// If provider is Anthropic, convert the request body from Anthropic to OpenAI format
	if provider.ProviderType == "anthropic" {
		converted, err := ConvertAnthropicRequest(body)
		if err != nil {
			slog.Error("failed to convert anthropic request", "error", err)
			response.SendError(c, http.StatusBadRequest, response.ErrorTypeInvalidRequest, "Failed to convert Anthropic request", "conversion_error")
			return
		}
		body = converted
	}

	// Save the original request body for conversation logging
	requestBody := string(body)

	// Create reverse proxy for this provider
	rp, err := NewReverseProxy(provider)
	if err != nil {
		slog.Error("failed to create reverse proxy", "provider", provider.Name, "error", err)
		response.SendError(c, http.StatusInternalServerError, response.ErrorTypeInternal, "Failed to create proxy for provider", "proxy_error")
		return
	}

	// Check if this is a streaming request
	isStream := IsStreamRequest(body)

	// Create the upstream request with a fresh body reader
	upstreamURL := provider.APIBaseURL + endpoint
	upstreamReq, err := http.NewRequestWithContext(c.Request.Context(), http.MethodPost, upstreamURL, bytes.NewReader(body))
	if err != nil {
		slog.Error("failed to create upstream request", "error", err)
		response.SendError(c, http.StatusInternalServerError, response.ErrorTypeInternal, "Failed to create upstream request", "request_error")
		return
	}

	// Set headers
	upstreamReq.Header.Set("Content-Type", "application/json")
	upstreamReq.Header.Set("Authorization", "Bearer "+provider.APIKey)

	// Also reset c.Request.Body so the reverse proxy (non-streaming path) can read it.
	// NOTE: ContentLength must be synced after Anthropic conversion changes body size,
	// otherwise Go transport aborts with ContentLength mismatch (Anthropic 502).
	c.Request.Body = io.NopCloser(bytes.NewReader(body))
	c.Request.ContentLength = int64(len(body))
	c.Request.Header.Set("Content-Length", strconv.FormatInt(int64(len(body)), 10))

	var responseBody string
	var statusCode int
	var promptTokens, completionTokens int

	if isStream {
		// For streaming, execute the request and stream the response
		resp, err := http.DefaultClient.Do(upstreamReq)
		if err != nil {
			slog.Error("upstream request failed", "provider", provider.Name, "error", err)
			response.SendUpstreamError(c, http.StatusBadGateway, "Failed to connect to upstream provider")
			return
		}
		defer resp.Body.Close()

		statusCode = resp.StatusCode

		// Use strings.Builders to collect streamed content and reasoning separately
		var contentCollector strings.Builder
		var reasoningCollector strings.Builder
		pt, ct, err := StreamResponse(c.Writer, resp, &contentCollector, &reasoningCollector)
		if err != nil {
			slog.Error("streaming error", "provider", provider.Name, "error", err)
		}
		// Combine reasoning + content into response body
		if reasoningCollector.Len() > 0 {
			var combined strings.Builder
			combined.WriteString("<reasoning>\n")
			combined.WriteString(reasoningCollector.String())
			combined.WriteString("\n</reasoning>\n")
			combined.WriteString(contentCollector.String())
			responseBody = combined.String()
		} else {
			responseBody = contentCollector.String()
		}
		promptTokens = pt
		completionTokens = ct
	} else {
		// For non-streaming, use a responseCaptureWriter to capture the response body
		captureWriter := &responseCaptureWriter{
			ResponseWriter: c.Writer,
			body:           &bytes.Buffer{},
		}
		rp.ServeHTTP(captureWriter, c.Request.WithContext(c.Request.Context()))
		responseBody = captureWriter.body.String()
		statusCode = captureWriter.ResponseWriter.Status()

		// Try to extract usage tokens from the non-streaming response
		var respData struct {
			Usage struct {
				PromptTokens     int `json:"prompt_tokens"`
				CompletionTokens int `json:"completion_tokens"`
			} `json:"usage"`
		}
		if err := json.Unmarshal(captureWriter.body.Bytes(), &respData); err == nil {
			promptTokens = respData.Usage.PromptTokens
			completionTokens = respData.Usage.CompletionTokens
		}
	}

	// Pass token counts to gin context so audit middleware can use them
	c.Set("prompt_tokens", promptTokens)
	c.Set("completion_tokens", completionTokens)

	// Log conversation if enabled (synchronous write to avoid SQLite lock contention with audit store)
	if h.convEnabled && h.convStore != nil {
		apiKeyID, _ := c.Get("api_key_id")

		var uid *int64
		if v, ok := c.Get("user_id"); ok {
			if id, ok := v.(int64); ok && id != 0 {
				uid = &id
			}
		}
		var akID *int64
		if v, ok := apiKeyID.(int64); ok {
			akID = &v
		}

		entry := &model.ConversationLog{
			UserID:           uid,
			APIKeyID:         akID,
			ModelID:          &modelID,
			RequestBody:      requestBody,
			ResponseBody:     &responseBody,
			IsStream:         isStream,
			PromptTokens:     promptTokens,
			CompletionTokens: completionTokens,
			StatusCode:       statusCode,
			CreatedAt:        time.Now(),
		}
		h.convStore.WriteSync(entry)
	}
	// Record usage for quota (usage_records). QuotaCheck reads this table,
	// so without this call all RPM/RPD/TPM/TPD quotas are no-ops.
	if h.quotaService != nil {
		startTime := time.Now()
		if v, ok := c.Get("start_time"); ok {
			if st, ok := v.(time.Time); ok {
				startTime = st
			}
		}
		latencyMs := time.Since(startTime).Milliseconds()
		var usageKeyID *int64
		hasUsageKey := false
		if v, ok := c.Get("api_key_id"); ok {
			if id, ok := v.(int64); ok && id != 0 {
				cpk := id
				usageKeyID = &cpk
				hasUsageKey = true
			}
		}
		var usageUserID *int64
		if v, ok := c.Get("user_id"); ok {
			if id, ok := v.(int64); ok && id != 0 {
				cp := id
				usageUserID = &cp
			}
		}
		if hasUsageKey || usageUserID != nil {
			if rerr := h.quotaService.RecordUsage(usageKeyID, usageUserID, modelID, promptTokens, completionTokens, latencyMs, statusCode, c.ClientIP()); rerr != nil {
				slog.Warn("failed to record usage", "error", rerr)
			}
		}
	}
}
