package api

import "fmt"

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
