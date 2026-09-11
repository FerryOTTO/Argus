package proxy

import (
	"bufio"
	"encoding/json"
	"io"
	"net/http"
	"strings"
)

// StreamResponse handles SSE streaming from upstream.
// It copies the response body directly to the client and sets appropriate headers.
// If contentCollector is non-nil, it accumulates the delta content from each SSE chunk.
// If reasoningCollector is non-nil, it accumulates reasoning_content separately.
// Returns accumulated prompt and completion tokens from the last SSE chunk's usage field.
func StreamResponse(w http.ResponseWriter, resp *http.Response, contentCollector *strings.Builder, reasoningCollector *strings.Builder) (promptTokens, completionTokens int, err error) {
	// Set SSE headers
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("Transfer-Encoding", "chunked")
	w.WriteHeader(resp.StatusCode)

	// Create a flusher to ensure data is sent immediately
	flusher, ok := w.(http.Flusher)
	if !ok {
		_, err := io.Copy(w, resp.Body)
		return 0, 0, err
	}

	scanner := bufio.NewScanner(resp.Body)
	// Increase buffer size for potentially large SSE lines
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)

	for scanner.Scan() {
		line := scanner.Text()
		// Write the line as-is to the client
		w.Write([]byte(line))
		w.Write([]byte("\n"))
		flusher.Flush()

		// If contentCollector is enabled, parse data lines for content and usage
		if contentCollector != nil && strings.HasPrefix(line, "data: ") {
			data := strings.TrimPrefix(line, "data: ")
			if data != "[DONE]" {
				// Try to extract content delta
				var chunk struct {
					Choices []struct {
						Delta struct {
							Content          string `json:"content"`
							ReasoningContent string `json:"reasoning_content"`
						} `json:"delta"`
					} `json:"choices"`
					Usage struct {
						PromptTokens     int `json:"prompt_tokens"`
						CompletionTokens int `json:"completion_tokens"`
					} `json:"usage"`
				}
				if jsonErr := json.Unmarshal([]byte(data), &chunk); jsonErr == nil {
					for _, choice := range chunk.Choices {
						if choice.Delta.Content != "" && contentCollector != nil {
							contentCollector.WriteString(choice.Delta.Content)
						}
						if choice.Delta.ReasoningContent != "" && reasoningCollector != nil {
							reasoningCollector.WriteString(choice.Delta.ReasoningContent)
						}
					}
					// Extract usage from the last chunk that contains it
					if chunk.Usage.PromptTokens > 0 {
						promptTokens = chunk.Usage.PromptTokens
					}
					if chunk.Usage.CompletionTokens > 0 {
						completionTokens = chunk.Usage.CompletionTokens
					}
				}
			}
		}
	}

	if err := scanner.Err(); err != nil {
		return 0, 0, err
	}
	return promptTokens, completionTokens, nil
}

// IsStreamRequest checks if the request body contains "stream": true
func IsStreamRequest(body []byte) bool {
	var req struct {
		Stream bool `json:"stream"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		return false
	}
	return req.Stream
}
