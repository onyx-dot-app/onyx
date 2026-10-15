package auditcmd

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

func TestRunAuditTrack_readsPaginatedAlertsAndUpdatesTheHistory(t *testing.T) {
	dir := t.TempDir()
	alerts := filepath.Join(dir, "alerts.json")
	// gh api --paginate prints one array per page.
	pages := `[{"state":"open","created_at":"2026-10-01T00:00:00Z","rule":{"id":"CVE-1","security_severity_level":"critical"},"most_recent_instance":{"category":"image-audit-sandbox"}}]
[{"state":"fixed","created_at":"2026-09-01T00:00:00Z","rule":{"id":"CVE-2","severity":"error"},"most_recent_instance":{"category":"image-audit-sandbox"}}]`
	if err := os.WriteFile(alerts, []byte(pages), 0644); err != nil {
		t.Fatal(err)
	}
	history := filepath.Join(dir, "history.json")
	summary := filepath.Join(dir, "summary.md")
	now := time.Date(2026, 10, 15, 0, 0, 0, 0, time.UTC)
	if err := runAuditTrack(&AuditTrackOptions{Alerts: alerts, History: history, Summary: summary}, now); err != nil {
		t.Fatal(err)
	}
	h, err := audit.ReadHistory(history)
	if err != nil {
		t.Fatal(err)
	}
	if len(h.Snapshots) != 1 || h.Snapshots[0].Images["sandbox"].Open != 1 || h.Snapshots[0].Images["sandbox"].Resolved != 1 {
		t.Fatalf("history: %+v", h)
	}
	got, err := os.ReadFile(summary)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(got), "• *sandbox*: 1 open (1 critical), 1 resolved, 2 total") {
		t.Fatalf("summary:\n%s", got)
	}

	if err := os.WriteFile(alerts, []byte("{"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := runAuditTrack(&AuditTrackOptions{Alerts: alerts, History: history}, now); err == nil || !strings.Contains(err.Error(), "failed to parse code scanning alerts") {
		t.Fatalf("want a parse error, got %v", err)
	}
}
