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

func TestExitError_Unwrap(t *testing.T) {
	inner := fmt.Errorf("inner error")
	e := Wrap(AuthFailure, inner)
	if !errors.Is(e, inner) {
		t.Fatal("Unwrap should return the inner error")
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
