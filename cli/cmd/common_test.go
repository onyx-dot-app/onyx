package cmd

import (
	"errors"
	"fmt"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
)

func TestApiErrorToExit(t *testing.T) {
	tests := []struct {
		name     string
		err      error
		wantCode exitcodes.Code
	}{
		{"auth_error", &api.AuthError{Message: "denied"}, exitcodes.AuthFailure},
		{"api_429", &api.OnyxAPIError{StatusCode: 429, Detail: "slow down"}, exitcodes.RateLimited},
		{"api_500", &api.OnyxAPIError{StatusCode: 500, Detail: "boom"}, exitcodes.ServerError},
		{"api_504", &api.OnyxAPIError{StatusCode: 504, Detail: "timeout"}, exitcodes.Timeout},
		{"api_400", &api.OnyxAPIError{StatusCode: 400, Detail: "bad request"}, exitcodes.BadRequest},
		{"api_401", &api.OnyxAPIError{StatusCode: 401, Detail: "unauthorized"}, exitcodes.AuthFailure},
		{"api_404", &api.OnyxAPIError{StatusCode: 404, Detail: "not found"}, exitcodes.NotAvailable},
		{"generic_error", fmt.Errorf("connection refused"), exitcodes.Unreachable},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := apiErrorToExit(tt.err, "test action")
			var exitErr *exitcodes.ExitError
			if !errors.As(err, &exitErr) {
				t.Fatalf("want *ExitError, got %T", err)
			}
			if exitErr.Code != tt.wantCode {
				t.Errorf("exit code = %d, want %d", exitErr.Code, tt.wantCode)
			}
		})
	}
}

func TestApiErrorToExit_ActionInMessage(t *testing.T) {
	tests := []struct {
		name   string
		err    error
		action string
	}{
		{"auth_error", &api.AuthError{Message: "denied"}, "listing agents"},
		{"api_error", &api.OnyxAPIError{StatusCode: 500, Detail: "boom"}, "fetching sessions"},
		{"generic_error", fmt.Errorf("connection refused"), "sending message"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := apiErrorToExit(tt.err, tt.action)
			if !strings.Contains(err.Error(), tt.action) {
				t.Errorf("error message %q does not contain action %q", err.Error(), tt.action)
			}
		})
	}
}
