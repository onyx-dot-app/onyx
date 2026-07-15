package client

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// APIError is a non-2xx response from the Onyx API. ErrorCode and Detail are
// populated from the standard OnyxError JSON shape
// {"error_code": "...", "detail": "..."} when present.
type APIError struct {
	StatusCode int
	ErrorCode  string
	Detail     string
}

func (e *APIError) Error() string {
	if e.ErrorCode != "" {
		return fmt.Sprintf("onyx API error (HTTP %d, %s): %s", e.StatusCode, e.ErrorCode, e.Detail)
	}
	return fmt.Sprintf("onyx API error (HTTP %d): %s", e.StatusCode, e.Detail)
}

// IsNotFound reports whether err is an APIError with HTTP 404.
func IsNotFound(err error) bool {
	var apiErr *APIError
	return errors.As(err, &apiErr) && apiErr.StatusCode == http.StatusNotFound
}

func checkResponse(resp *http.Response) error {
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return nil
	}

	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	apiErr := &APIError{StatusCode: resp.StatusCode}

	if isHTMLResponse(resp.Header.Get("Content-Type"), body) {
		apiErr.Detail = "server returned HTML instead of JSON — check that the endpoint and api_prefix are correct"
		return apiErr
	}

	var parsed struct {
		ErrorCode string          `json:"error_code"`
		Detail    json.RawMessage `json:"detail"`
	}
	if err := json.Unmarshal(body, &parsed); err == nil {
		apiErr.ErrorCode = parsed.ErrorCode
		// detail is usually a string but can be a structured validation error.
		var detailStr string
		if json.Unmarshal(parsed.Detail, &detailStr) == nil {
			apiErr.Detail = detailStr
		} else if len(parsed.Detail) > 0 {
			apiErr.Detail = string(parsed.Detail)
		}
	}
	if apiErr.Detail == "" {
		apiErr.Detail = strings.TrimSpace(string(body))
	}
	return apiErr
}

func isHTMLResponse(contentType string, body []byte) bool {
	if strings.Contains(contentType, "text/html") {
		return true
	}
	lower := strings.ToLower(strings.TrimSpace(string(body)))
	return strings.HasPrefix(lower, "<!doctype") || strings.HasPrefix(lower, "<html")
}
