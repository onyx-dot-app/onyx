package exitcodes

import (
	"errors"
	"fmt"
	"testing"
)

func TestExitError_Error(t *testing.T) {
	e := New(NotConfigured, "not configured")
	if e.Error() != "not configured" {
		t.Fatalf("expected 'not configured', got %q", e.Error())
	}
	if e.Code != NotConfigured {
		t.Fatalf("expected code %d, got %d", NotConfigured, e.Code)
	}
}

func TestExitError_Newf(t *testing.T) {
	e := Newf(Unreachable, "cannot reach %s", "server")
	if e.Error() != "cannot reach server" {
		t.Fatalf("expected 'cannot reach server', got %q", e.Error())
	}
	if e.Code != Unreachable {
		t.Fatalf("expected code %d, got %d", Unreachable, e.Code)
	}
}

func TestExitError_ErrorsAs(t *testing.T) {
	e := New(BadRequest, "bad input")
	wrapped := fmt.Errorf("wrapper: %w", e)

	var exitErr *ExitError
	if !errors.As(wrapped, &exitErr) {
		t.Fatal("errors.As should find ExitError")
	}
	if exitErr.Code != BadRequest {
		t.Fatalf("expected code %d, got %d", BadRequest, exitErr.Code)
	}
}

func TestExitError_Unwrap(t *testing.T) {
	sentinel := fmt.Errorf("sentinel")
	e := &ExitError{Code: General, Err: sentinel}
	wrapped := fmt.Errorf("outer: %w", e)

	if !errors.Is(wrapped, sentinel) {
		t.Fatal("errors.Is should find the sentinel error through Unwrap")
	}

	var exitErr *ExitError
	if !errors.As(wrapped, &exitErr) {
		t.Fatal("errors.As should find ExitError")
	}
	if exitErr.Code != General {
		t.Fatalf("expected code %d, got %d", General, exitErr.Code)
	}
}

func TestForHTTPStatus(t *testing.T) {
	tests := []struct {
		status int
		want   Code
	}{
		{200, Success},
		{400, BadRequest},
		{422, BadRequest},
		{401, AuthFailure},
		{403, AuthFailure},
		{404, NotAvailable},
		{429, RateLimited},
		{408, Timeout},
		{500, ServerError},
		{502, ServerError},
		{503, ServerError},
		{504, Timeout},
		{418, General}, // unmapped status code hits default branch
	}
	for _, tt := range tests {
		got := ForHTTPStatus(tt.status)
		if got != tt.want {
			t.Errorf("ForHTTPStatus(%d) = %d, want %d", tt.status, got, tt.want)
		}
	}
}
