package api

import (
	"errors"
	"fmt"
	"net/http"
)

// ErrorCodeApprovalPending rejects a new message while the chat's response
// waits for the user: a tool call's approval, or answers to its questions. It
// also rejects a typed answer to questions while an approval of the response
// waits.
const ErrorCodeApprovalPending = "APPROVAL_PENDING"

// OnyxAPIError is returned when an Onyx API call fails.
type OnyxAPIError struct {
	StatusCode int
	// ErrorCode is the server's machine-readable code, empty when the body has none.
	ErrorCode string
	Detail    string
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

// IsNoLongerWaiting reports a decision or an answer that the server cannot
// apply because the request was already decided or answered, ended with its
// response, or does not exist.
func IsNoLongerWaiting(err error) bool {
	var apiErr *OnyxAPIError
	return errors.As(err, &apiErr) && apiErr.ErrorCode != ErrorCodeApprovalPending &&
		(apiErr.StatusCode == http.StatusConflict || apiErr.StatusCode == http.StatusNotFound)
}

// IsApprovalPending reports a typed answer that the server refused because an
// approval request of the response still waits.
func IsApprovalPending(err error) bool {
	var apiErr *OnyxAPIError
	return errors.As(err, &apiErr) && apiErr.ErrorCode == ErrorCodeApprovalPending
}
