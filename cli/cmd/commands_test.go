package cmd

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
	"github.com/spf13/cobra"
)

func discardIOStreams() *iostreams.IOStreams {
	return &iostreams.IOStreams{
		In:     strings.NewReader(""),
		Out:    io.Discard,
		ErrOut: io.Discard,
	}
}

func execCmd(cmd *cobra.Command, args ...string) error {
	cmd.SetArgs(args)
	cmd.SilenceErrors = true
	cmd.SilenceUsage = true
	return cmd.Execute()
}

func assertExitCode(t *testing.T, err error, wantCode exitcodes.Code) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected error with exit code %d, got nil", wantCode)
	}
	var exitErr *exitcodes.ExitError
	if !errors.As(err, &exitErr) {
		t.Fatalf("expected *ExitError, got %T: %v", err, err)
	}
	if exitErr.Code != wantCode {
		t.Errorf("exit code = %d, want %d (error: %v)", exitErr.Code, wantCode, err)
	}
}

// --- Agents tests ---

func TestAgentsCmd_ExitCodes(t *testing.T) {
	tests := []struct {
		name     string
		status   int
		wantCode exitcodes.Code
	}{
		{"401_auth_failure", 401, exitcodes.AuthFailure},
		{"403_auth_failure", 403, exitcodes.AuthFailure},
		{"404_not_available", 404, exitcodes.NotAvailable},
		{"429_rate_limited", 429, exitcodes.RateLimited},
		{"500_server_error", 500, exitcodes.ServerError},
		{"504_timeout", 504, exitcodes.Timeout},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := testutil.StatusServer(tt.status)
			defer srv.Close()
			testutil.IsolateConfig(t, srv.URL)

			ios := discardIOStreams()
			cmd := newAgentsCmd(ios)
			err := execCmd(cmd)
			assertExitCode(t, err, tt.wantCode)
		})
	}
}

func TestAgentsCmd_NotConfigured(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("ONYX_PAT", "")
	t.Setenv("ONYX_SERVER_URL", "")

	ios := discardIOStreams()
	cmd := newAgentsCmd(ios)
	err := execCmd(cmd)
	assertExitCode(t, err, exitcodes.NotConfigured)
}

func TestAgentsCmd_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/persona" {
			agents := []map[string]any{
				{"id": 1, "name": "Default", "description": "Default agent", "is_visible": true, "is_default_persona": true},
				{"id": 2, "name": "Hidden", "description": "Hidden agent", "is_visible": false, "is_default_persona": false},
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(agents)
			return
		}
		w.WriteHeader(200)
	}))
	defer srv.Close()
	testutil.IsolateConfig(t, srv.URL)

	ios, out, _ := testutil.TestIOStreams()
	cmd := newAgentsCmd(ios)
	err := execCmd(cmd)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !strings.Contains(out.String(), "Default") {
		t.Errorf("output should contain agent name 'Default', got: %s", out.String())
	}
	if strings.Contains(out.String(), "Hidden") {
		t.Errorf("output should not contain hidden agent, got: %s", out.String())
	}
}

// --- ValidateConfig tests ---

func TestValidateConfigCmd_ExitCodes(t *testing.T) {
	tests := []struct {
		name     string
		status   int
		wantCode exitcodes.Code
	}{
		{"401_auth_failure", 401, exitcodes.AuthFailure},
		{"429_rate_limited", 429, exitcodes.RateLimited},
		{"500_server_error", 500, exitcodes.ServerError},
		{"504_timeout", 504, exitcodes.Timeout},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/api/me" {
					w.WriteHeader(tt.status)
					return
				}
				// Root path must return 200 for reachability check
				w.WriteHeader(200)
			}))
			defer srv.Close()
			testutil.IsolateConfig(t, srv.URL)

			ios := discardIOStreams()
			cmd := newValidateConfigCmd(ios)
			err := execCmd(cmd)
			assertExitCode(t, err, tt.wantCode)
		})
	}
}

func TestValidateConfigCmd_Success(t *testing.T) {
	srv := testutil.OnyxServer(200)
	defer srv.Close()
	testutil.IsolateConfig(t, srv.URL)

	ios, out, _ := testutil.TestIOStreams()
	cmd := newValidateConfigCmd(ios)
	err := execCmd(cmd)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !strings.Contains(out.String(), "connected and authenticated") {
		t.Errorf("expected success message, got: %s", out.String())
	}
}

func TestValidateConfigCmd_NotConfigured(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("ONYX_PAT", "")
	t.Setenv("ONYX_SERVER_URL", "")

	ios := discardIOStreams()
	cmd := newValidateConfigCmd(ios)
	err := execCmd(cmd)
	assertExitCode(t, err, exitcodes.NotConfigured)
}

// --- Ask tests ---

func TestAskCmd_ExitCodes(t *testing.T) {
	tests := []struct {
		name     string
		status   int
		wantCode exitcodes.Code
	}{
		{"401_auth_failure", 401, exitcodes.AuthFailure},
		{"429_rate_limited", 429, exitcodes.RateLimited},
		{"500_server_error", 500, exitcodes.ServerError},
		{"504_timeout", 504, exitcodes.Timeout},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := testutil.StatusServer(tt.status)
			defer srv.Close()
			testutil.IsolateConfig(t, srv.URL)

			ios := discardIOStreams()
			ios.IsStdinTTY = true
			cmd := newAskCmd(ios)
			err := execCmd(cmd, "test question")
			assertExitCode(t, err, tt.wantCode)
		})
	}
}

func TestAskCmd_NotConfigured(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("ONYX_PAT", "")
	t.Setenv("ONYX_SERVER_URL", "")

	ios := discardIOStreams()
	ios.IsStdinTTY = true
	cmd := newAskCmd(ios)
	err := execCmd(cmd, "test question")
	assertExitCode(t, err, exitcodes.NotConfigured)
}

func TestAskCmd_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/chat/send-chat-message" {
			w.Header().Set("Content-Type", "application/json")
			// Send valid NDJSON stream: session_created + message_id + message_delta + stop
			// The parser expects placement as an object and obj with type field
			p := `{"turn_index":0,"tab_index":0}`
			lines := []string{
				`{"chat_session_id":"abc-123"}`,
				`{"reserved_assistant_message_id":1,"user_message_id":2}`,
				fmt.Sprintf(`{"placement":%s,"obj":{"type":"message_delta","content":"Hello world"}}`, p),
				fmt.Sprintf(`{"placement":%s,"obj":{"type":"stop"}}`, p),
			}
			for _, line := range lines {
				fmt.Fprintln(w, line)
			}
			return
		}
		w.WriteHeader(200)
	}))
	defer srv.Close()
	testutil.IsolateConfig(t, srv.URL)

	ios, out, _ := testutil.TestIOStreams()
	ios.IsStdinTTY = true
	cmd := newAskCmd(ios)
	err := execCmd(cmd, "--json", "test question")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	output := out.String()
	if !strings.Contains(output, "Hello world") {
		t.Errorf("expected output to contain message_delta content 'Hello world', got: %s", output)
	}
	if !strings.Contains(output, `"type":"message_delta"`) {
		t.Errorf("expected output to contain message_delta event type, got: %s", output)
	}
	if !strings.Contains(output, `"type":"stop"`) {
		t.Errorf("expected output to contain stop event, got: %s", output)
	}
}
