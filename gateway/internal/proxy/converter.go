package proxy

import (
	"encoding/json"
	"fmt"
	"time"
)

// anthropicRequest represents an Anthropic Messages API request
type anthropicRequest struct {
	Model     string            `json:"model"`
	Messages  []json.RawMessage `json:"messages"`
	MaxTokens int               `json:"max_tokens,omitempty"`
	System    string            `json:"system,omitempty"`
	Stream    bool              `json:"stream,omitempty"`
}

// openaiRequest represents an OpenAI Chat Completions request
type openaiRequest struct {
	Model     string            `json:"model"`
	Messages  []json.RawMessage `json:"messages"`
	MaxTokens int               `json:"max_tokens,omitempty"`
	Stream    bool              `json:"stream,omitempty"`
}

// openaiMessage is used to construct the system message
type openaiMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// anthropicStreamEvent represents an Anthropic SSE event
type anthropicStreamEvent struct {
	Type  string          `json:"type"`
	Index int             `json:"index,omitempty"`
	Delta json.RawMessage `json:"delta,omitempty"`
	Usage json.RawMessage `json:"usage,omitempty"`

	// For message_start
	Message *struct {
		ID    string `json:"id"`
		Model string `json:"model"`
		Role  string `json:"role"`
		Usage struct {
			InputTokens  int `json:"input_tokens"`
			OutputTokens int `json:"output_tokens"`
		} `json:"usage"`
	} `json:"message,omitempty"`
}

// anthropicTextDelta represents a text_delta in content_block_delta
type anthropicTextDelta struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// anthropicInputJSONDelta represents an input_json_delta in content_block_delta
type anthropicInputJSONDelta struct {
	Type        string `json:"type"`
	PartialJSON string `json:"partial_json"`
}

// openaiStreamChunk represents an OpenAI SSE chunk
type openaiStreamChunk struct {
	ID      string `json:"id"`
	Object  string `json:"object"`
	Created int64  `json:"created"`
	Model   string `json:"model"`
	Choices []struct {
		Index        int          `json:"index"`
		Delta        openaiDelta  `json:"delta"`
		FinishReason *string      `json:"finish_reason"`
		Usage        *openaiUsage `json:"usage,omitempty"`
	} `json:"choices"`
}

// openaiDelta represents the delta in a choice
type openaiDelta struct {
	Role      string                `json:"role,omitempty"`
	Content   string                `json:"content,omitempty"`
	ToolCalls []openaiToolCallDelta `json:"tool_calls,omitempty"`
}

// openaiToolCallDelta represents a tool call delta
type openaiToolCallDelta struct {
	Index    int    `json:"index"`
	ID       string `json:"id,omitempty"`
	Type     string `json:"type,omitempty"`
	Function struct {
		Name      string `json:"name,omitempty"`
		Arguments string `json:"arguments,omitempty"`
	} `json:"function,omitempty"`
}

// openaiUsage represents usage info
type openaiUsage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

// anthropicUsage represents Anthropic usage info
type anthropicUsage struct {
	InputTokens  int `json:"input_tokens"`
	OutputTokens int `json:"output_tokens"`
}

// messageDeltaData represents the delta in message_delta event
type messageDeltaData struct {
	StopReason string `json:"stop_reason"`
}

// ConvertAnthropicRequest converts an Anthropic Messages API request body to OpenAI format.
// - Parses Anthropic JSON
// - If "system" field exists, prepends as a system message
// - Keeps messages array as-is (roles are compatible)
// - Maps max_tokens (both use same field name)
// - Returns OpenAI-format JSON
func ConvertAnthropicRequest(body []byte) ([]byte, error) {
	var anthropic anthropicRequest
	if err := json.Unmarshal(body, &anthropic); err != nil {
		return nil, fmt.Errorf("failed to parse anthropic request: %w", err)
	}

	// Build messages array, prepending system message if present
	messages := make([]json.RawMessage, 0, len(anthropic.Messages)+1)

	if anthropic.System != "" {
		sysMsg := openaiMessage{Role: "system", Content: anthropic.System}
		sysRaw, err := json.Marshal(sysMsg)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal system message: %w", err)
		}
		messages = append(messages, json.RawMessage(sysRaw))
	}

	messages = append(messages, anthropic.Messages...)

	openai := openaiRequest{
		Model:     anthropic.Model,
		Messages:  messages,
		MaxTokens: anthropic.MaxTokens,
		Stream:    anthropic.Stream,
	}

	result, err := json.Marshal(openai)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal openai request: %w", err)
	}

	return result, nil
}

// ConvertAnthropicStreamEvent converts Anthropic SSE events to OpenAI format.
// It maps Anthropic streaming events to OpenAI-compatible SSE chunks.
func ConvertAnthropicStreamEvent(data []byte) ([]byte, error) {
	// Parse the Anthropic event
	var event anthropicStreamEvent
	if err := json.Unmarshal(data, &event); err != nil {
		return nil, fmt.Errorf("failed to parse anthropic stream event: %w", err)
	}

	// If it's not a recognized event type, return empty to skip
	if event.Type == "" {
		return nil, nil
	}

	var chunk openaiStreamChunk
	chunk.ID = fmt.Sprintf("chatcmpl-anthropic-%d", time.Now().UnixNano())
	chunk.Object = "chat.completion.chunk"
	chunk.Created = time.Now().Unix()
	chunk.Choices = make([]struct {
		Index        int          `json:"index"`
		Delta        openaiDelta  `json:"delta"`
		FinishReason *string      `json:"finish_reason"`
		Usage        *openaiUsage `json:"usage,omitempty"`
	}, 1)
	chunk.Choices[0].Index = 0

	switch event.Type {
	case "message_start":
		// Send role as assistant
		if event.Message != nil {
			chunk.Model = event.Message.Model
			chunk.Choices[0].Delta.Role = "assistant"
		} else {
			chunk.Model = "unknown"
		}

	case "content_block_start":
		// Start of a new content block
		chunk.Model = "unknown"
		chunk.Choices[0].Delta.Content = ""

	case "content_block_delta":
		chunk.Model = "unknown"

		// Try to parse as text_delta first
		var textDelta anthropicTextDelta
		if err := json.Unmarshal(event.Delta, &textDelta); err == nil && textDelta.Type == "text_delta" {
			chunk.Choices[0].Delta.Content = textDelta.Text
		} else {
			// Try to parse as input_json_delta for tool calls
			var jsonDelta anthropicInputJSONDelta
			if err := json.Unmarshal(event.Delta, &jsonDelta); err == nil && jsonDelta.Type == "input_json_delta" {
				chunk.Choices[0].Delta.ToolCalls = []openaiToolCallDelta{
					{
						Index: event.Index,
						Function: struct {
							Name      string `json:"name,omitempty"`
							Arguments string `json:"arguments,omitempty"`
						}{
							Arguments: jsonDelta.PartialJSON,
						},
					},
				}
			}
		}

	case "message_delta":
		chunk.Model = "unknown"

		// Parse stop reason
		if event.Delta != nil {
			var deltaData messageDeltaData
			if err := json.Unmarshal(event.Delta, &deltaData); err == nil {
				stopReason := deltaData.StopReason
				chunk.Choices[0].FinishReason = &stopReason
			}
		}

		// Parse usage if present
		if event.Usage != nil {
			var usage anthropicUsage
			if err := json.Unmarshal(event.Usage, &usage); err == nil {
				chunk.Choices[0].Usage = &openaiUsage{
					PromptTokens:     usage.InputTokens,
					CompletionTokens: usage.OutputTokens,
					TotalTokens:      usage.InputTokens + usage.OutputTokens,
				}
			}
		}

	case "message_stop":
		// Return [DONE] signal
		return []byte("[DONE]"), nil

	case "ping", "content_block_stop":
		// Skip these events
		return nil, nil

	default:
		// Unknown event type, skip
		return nil, nil
	}

	// Marshal the chunk to JSON
	result, err := json.Marshal(chunk)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal openai stream chunk: %w", err)
	}

	return result, nil
}
