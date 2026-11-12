package cmd

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

func TestAgentsTableStripsControlSequences(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`[{"id":7,"name":"Help\u001b]52;c;cm0gLXJm\u0007Desk","description":"a\u001b[2Jb\u0007\n99\tFake\tRow","is_listed":true}]`))
	}))
	defer srv.Close()
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("ONYX_SERVER_URL", srv.URL)
	t.Setenv("ONYX_PAT", "test-pat")

	ios, out, _ := testutil.TestIOStreams()
	cmd := newAgentsCmd(ios)
	cmd.SetArgs([]string{})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("Execute: %v", err)
	}

	got := out.String()
	if strings.ContainsAny(got, "\x1b\x07") {
		t.Errorf("output contains control bytes: %q", got)
	}
	if lines := strings.Count(got, "\n"); lines != 2 {
		t.Errorf("output has %d lines, want header plus one row: %q", lines, got)
	}
	if !strings.Contains(got, "HelpDesk") {
		t.Errorf("output = %q, want the cleaned agent name", got)
	}
}
