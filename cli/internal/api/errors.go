package api

import (
	"errors"
	"fmt"
	"net/http"
)

// OnyxAPIError is returned when an Onyx API call fails.
type OnyxAPIError struct {
	StatusCode int
	Detail     string
}

func (e *OnyxAPIError) Error() string {
	return fmt.Sprintf("HTTP %d: %s", e.StatusCode, e.Detail)
}

// AuthError is returned when authentication or authorization fails.
type AuthError struct {
	Message string
}

func (e *AuthError) Error() string {
	return e.Message
}

// IsRetryableReadinessError distinguishes temporary failures from unsupported or denied requests.
func IsRetryableReadinessError(err error) bool {
	if err == nil {
		return false
	}
	var authErr *AuthError
	if errors.As(err, &authErr) {
		return false
	}
	var apiErr *OnyxAPIError
	if errors.As(err, &apiErr) {
		return apiErr.StatusCode == http.StatusRequestTimeout || apiErr.StatusCode == http.StatusTooManyRequests || apiErr.StatusCode >= http.StatusInternalServerError
	}
	// Transport errors and malformed responses can recover on a later request.
	return true
}
