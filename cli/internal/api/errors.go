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
