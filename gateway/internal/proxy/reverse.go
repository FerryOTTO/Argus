package proxy

import (
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"

	"github.com/llmgate/llmgate/internal/model"
)

// NewReverseProxy creates a reverse proxy for the given provider
func NewReverseProxy(provider *model.Provider) (*httputil.ReverseProxy, error) {
	target, err := url.Parse(provider.APIBaseURL)
	if err != nil {
		return nil, fmt.Errorf("failed to parse provider API base URL %q: %w", provider.APIBaseURL, err)
	}

	// Ensure base path doesn't end with slash for clean joining
	basePath := strings.TrimRight(target.Path, "/")

	director := func(req *http.Request) {
		req.URL.Scheme = target.Scheme
		req.URL.Host = target.Host
		// Preserve original path, append to base path
		originalPath := req.URL.Path
		req.URL.Path = basePath + originalPath
		req.Host = target.Host

		// Set authorization header
		req.Header.Set("Authorization", "Bearer "+provider.APIKey)
		// Remove any proxy-specific headers
		req.Header.Del("Connection")
	}

	modifyResponse := func(resp *http.Response) error {
		if resp.StatusCode >= http.StatusBadRequest {
			slog.Warn("upstream error response",
				"provider", provider.Name,
				"status", resp.StatusCode,
			)
		}
		return nil
	}

	errorHandler := func(rw http.ResponseWriter, req *http.Request, err error) {
		slog.Error("reverse proxy error",
			"provider", provider.Name,
			"error", err,
		)
		rw.Header().Set("Content-Type", "application/json")
		rw.WriteHeader(http.StatusBadGateway)
		errorJSON := fmt.Sprintf(`{"error":{"message":"Failed to connect to upstream provider %q: %s","type":"upstream_error","code":"bad_gateway"}}`, provider.Name, err.Error())
		rw.Write([]byte(errorJSON))
	}

	return &httputil.ReverseProxy{
		Director:       director,
		ModifyResponse: modifyResponse,
		ErrorHandler:   errorHandler,
	}, nil
}
