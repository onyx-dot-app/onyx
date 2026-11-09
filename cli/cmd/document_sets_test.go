package cmd

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

func serveDocumentSets(t *testing.T, body string) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/manage/document-set" {
			t.Errorf("path = %s, want /api/manage/document-set", r.URL.Path)
		}
		if got := r.URL.Query().Get("searchable_only"); got != "true" {
			t.Errorf("searchable_only = %q, want true", got)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(body))
	}))
	t.Cleanup(srv.Close)
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("ONYX_SERVER_URL", srv.URL)
	t.Setenv("ONYX_PAT", "test-pat")
}

func TestDocumentSetsTable(t *testing.T) {
	serveDocumentSets(t, `[{"id":3,"name":"Engineering\u001b[2J Wiki","description":"Runbooks","is_public":true},{"id":4,"name":"Sales","description":null}]`)

	ios, out, _ := testutil.TestIOStreams()
	cmd := newDocumentSetsCmd(ios)
	cmd.SetArgs([]string{})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("Execute: %v", err)
	}

	got := out.String()
	if strings.Contains(got, "\x1b") {
		t.Errorf("output contains control bytes: %q", got)
	}
	if lines := strings.Count(got, "\n"); lines != 3 {
		t.Errorf("output has %d lines, want header plus two rows: %q", lines, got)
	}
	if !strings.Contains(got, "Engineering Wiki") || !strings.Contains(got, "Runbooks") {
		t.Errorf("output = %q, want the cleaned name and description", got)
	}
}

func TestDocumentSetsJSON(t *testing.T) {
	serveDocumentSets(t, `[{"id":3,"name":"Engineering Wiki","description":"Runbooks","cc_pair_summaries":[]}]`)

	ios, out, _ := testutil.TestIOStreams()
	cmd := newDocumentSetsCmd(ios)
	cmd.SetArgs([]string{"--json"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("Execute: %v", err)
	}

	var got []models.DocumentSetSummary
	if err := json.Unmarshal(out.Bytes(), &got); err != nil {
		t.Fatalf("output is not JSON: %v\n%s", err, out.String())
	}
	if len(got) != 1 || got[0].Name != "Engineering Wiki" || got[0].ID != 3 {
		t.Errorf("got %+v, want the one document set", got)
	}
	if strings.Contains(out.String(), "cc_pair_summaries") {
		t.Errorf("JSON output leaks server-only fields: %s", out.String())
	}
}

func TestDocumentSetsEmptyJSONIsArray(t *testing.T) {
	serveDocumentSets(t, `[]`)

	ios, out, _ := testutil.TestIOStreams()
	cmd := newDocumentSetsCmd(ios)
	cmd.SetArgs([]string{"--json"})
	if err := cmd.Execute(); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if strings.TrimSpace(out.String()) != "[]" {
		t.Errorf("output = %q, want []", out.String())
	}
}
