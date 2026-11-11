package auditcmd

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/audit"
)

const failingAlerts = `[{"key":"Debian:13/chromium","issue":7,"ecosystem":"Debian:13","package":"chromium","version":"155","advisories":[{"id":"DEBIAN-CVE-1","severity":"critical","images":["sandbox"]},{"id":"DEBIAN-CVE-2","severity":"critical","images":["sandbox"]}]}]`

func runAnnounce(t *testing.T, args ...string) (audit.AnnouncePlan, error) {
	t.Helper()
	cmd := NewRootCommand("1.2.3", "abc123")
	var stdout bytes.Buffer
	cmd.SetOut(&stdout)
	cmd.SetErr(&bytes.Buffer{})
	cmd.SetArgs(append([]string{"announce"}, args...))
	if err := cmd.Execute(); err != nil {
		return audit.AnnouncePlan{}, err
	}
	var plan audit.AnnouncePlan
	if err := json.Unmarshal(stdout.Bytes(), &plan); err != nil {
		t.Fatalf("expected a JSON plan on stdout: %v\n%s", err, stdout.String())
	}
	return plan, nil
}

func TestAnnounceCommand_plansTheRunsPosts(t *testing.T) {
	restoreLogger(t)
	dir := t.TempDir()
	failing := writeFixture(t, dir, "failing.json", failingAlerts)
	threads := writeFixture(t, dir, "threads.json", `{"DEBIAN-CVE-2":"111.222"}`)
	triage := filepath.Join(dir, "triage")
	if err := os.Mkdir(triage, 0755); err != nil {
		t.Fatal(err)
	}
	writeFixture(t, triage, "7.json", `{"issue":7,"fix":"*Fix PR:* none.","verdict":"affected","reason":"no fix yet"}`)

	plan, err := runAnnounce(t, "--failing", failing, "--threads", threads, "--triage-dir", triage,
		"--branch", "main", "--run-url", "https://run", "--owner", "<@U1>", "--expires", "2026-11-14")
	if err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if plan.Post == nil || !strings.Contains(plan.Post.Text, "DEBIAN-CVE-1") || strings.Contains(plan.Post.Text, "DEBIAN-CVE-2") {
		t.Fatalf("expected only the unseen advisory in the new post, got %+v", plan.Post)
	}
	if !strings.Contains(strings.Join(plan.Post.Thread, "\n"), "--expires 2026-11-14") {
		t.Fatalf("expected the given expiry in the commands, got %q", plan.Post.Thread)
	}
	if len(plan.Replies) != 1 || plan.Replies[0].TS != "111.222" || !strings.Contains(plan.Replies[0].Text, "DEBIAN-CVE-2") {
		t.Fatalf("expected a follow-up in the known thread, got %+v", plan.Replies)
	}
}

func TestAnnounceCommand_defaultsTheExpiryToThirtyDays(t *testing.T) {
	restoreLogger(t)
	failing := writeFixture(t, t.TempDir(), "failing.json", failingAlerts)
	plan, err := runAnnounce(t, "--failing", failing, "--run-url", "https://run", "--owner", "@me")
	if err != nil {
		t.Fatalf("Execute: %v", err)
	}
	want := time.Now().UTC().AddDate(0, 0, 30).Format(time.DateOnly)
	if !strings.Contains(strings.Join(plan.Post.Thread, "\n"), "--expires "+want) {
		t.Fatalf("expected --expires %s, got %q", want, plan.Post.Thread)
	}
}

func TestAnnounceCommand_rejectsUnreadableInputs(t *testing.T) {
	restoreLogger(t)
	dir := t.TempDir()
	failing := writeFixture(t, dir, "failing.json", failingAlerts)
	badThreads := writeFixture(t, dir, "threads.json", `[`)
	badTriage := filepath.Join(dir, "triage")
	if err := os.Mkdir(badTriage, 0755); err != nil {
		t.Fatal(err)
	}
	writeFixture(t, badTriage, "7.json", `{`)

	for name, opts := range map[string]AuditAnnounceOptions{
		"missing failing": {Failing: filepath.Join(dir, "nope.json")},
		"bad threads":     {Failing: failing, Threads: badThreads},
		"bad triage":      {Failing: failing, TriageDir: badTriage},
		"bad triage glob": {Failing: failing, TriageDir: "["},
	} {
		t.Run(name, func(t *testing.T) {
			opts.RunURL = "https://run"
			if err := runAuditAnnounce(&opts, &bytes.Buffer{}); err == nil {
				t.Fatal("expected an error")
			}
		})
	}
}

func TestAlertCommand_writesEveryFailingAlert(t *testing.T) {
	restoreLogger(t)
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	writeFakeCommand(t, bin, "gh", "echo '[]'")
	results := writeFixture(t, t.TempDir(), "deps.json", blockingResult)
	allowlist := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores":[]}`)
	failing := filepath.Join(t.TempDir(), "failing.json")

	if _, err := runAlert(t, "--results", results, "--ignore-url", allowlist, "--dry-run", "--failing", failing); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	var alerts []audit.Alert
	data, err := os.ReadFile(failing)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(data, &alerts); err != nil || len(alerts) != 1 || alerts[0].Key != "npm/next" {
		t.Fatalf("expected npm/next failing, got %s (%v)", data, err)
	}

	empty := writeFixture(t, t.TempDir(), "deps.json", `{"findings":[],"blocking":[]}`)
	if _, err := runAlert(t, "--results", empty, "--ignore-url", allowlist, "--dry-run", "--failing", failing); err != nil {
		t.Fatalf("Execute: %v", err)
	}
	if data, _ := os.ReadFile(failing); strings.TrimSpace(string(data)) != "[]" {
		t.Fatalf("expected an empty array, got %s", data)
	}

	unwritable := &AuditAlertOptions{Results: []string{results}, IgnoreURL: allowlist, DryRun: true, Failing: filepath.Join(t.TempDir(), "no", "dir.json")}
	if err := runAuditAlert(unwritable, &bytes.Buffer{}); err == nil {
		t.Fatal("expected an unwritable --failing to fail")
	}
}
