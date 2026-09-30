package auditcmd

import (
	"bytes"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

const blockingResult = `{"findings":[{"id":"GHSA-next","ecosystem":"npm","package":"next","severity":"critical"}],"blocking":[{"id":"GHSA-next","ecosystem":"npm","package":"next","severity":"critical"}]}`

func runAlert(t *testing.T, args ...string) (string, error) {
	t.Helper()
	cmd := NewRootCommand("1.2.3", "abc123")
	var stdout bytes.Buffer
	cmd.SetOut(&stdout)
	cmd.SetErr(&bytes.Buffer{})
	cmd.SetArgs(append([]string{"alert"}, args...))
	err := cmd.Execute()
	return stdout.String(), err
}

func TestAlertCommand_dryRunPrintsTheAlerts(t *testing.T) {
	restoreLogger(t)
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	writeFakeCommand(t, bin, "gh", "echo '[]'")
	results := writeFixture(t, t.TempDir(), "deps.json", blockingResult)
	allowlist := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores":[]}`)

	out, err := runAlert(t, "--results", results, "--ignore-url", allowlist, "--dry-run")
	if err != nil {
		t.Fatalf("Execute: %v", err)
	}
	var alerts []audit.Alert
	if err := json.Unmarshal([]byte(out), &alerts); err != nil {
		t.Fatalf("expected a JSON array on stdout: %v\n%s", err, out)
	}
	if len(alerts) != 1 || alerts[0].Key != "npm/next" || alerts[0].Reason != audit.AlertNew {
		t.Fatalf("expected one new npm/next alert, got %+v", alerts)
	}
}

// brokenWriter fails every write, like a closed stdout pipe.
type brokenWriter struct{}

func (brokenWriter) Write([]byte) (int, error) { return 0, errors.New("closed pipe") }

func TestAlertCommand_reportsAnUnwritableStdout(t *testing.T) {
	restoreLogger(t)
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	writeFakeCommand(t, bin, "gh", "echo '[]'")
	results := writeFixture(t, t.TempDir(), "deps.json", blockingResult)
	allowlist := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores":[]}`)

	err := runAuditAlert(&AuditAlertOptions{Results: []string{results}, IgnoreURL: allowlist, DryRun: true}, brokenWriter{})
	if err == nil || !strings.Contains(err.Error(), "closed pipe") {
		t.Fatalf("expected the write error, got %v", err)
	}
}

func TestAlertCommand_printsAlertsBeforeFailing(t *testing.T) {
	restoreLogger(t)
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	// The allowlist is unreadable, so the sync fails before recording anything.
	writeFakeCommand(t, bin, "gh", "echo '[]'")
	results := writeFixture(t, t.TempDir(), "deps.json", blockingResult)

	var out bytes.Buffer
	err := runAuditAlert(&AuditAlertOptions{Results: []string{results}, IgnoreURL: "/nonexistent/ignores.json"}, &out)
	requireCommandError(t, err, "Alert sync failed: failed to fetch the allowlist")
	if strings.TrimSpace(out.String()) != "[]" {
		t.Fatalf("expected an empty JSON array even on failure, got %q", out.String())
	}
}
