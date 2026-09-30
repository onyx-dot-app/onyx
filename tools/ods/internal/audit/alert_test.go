package audit

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"testing"
)

func TestGroupAlerts_mergesSourcesPerPackage(t *testing.T) {
	findings := []Finding{
		{ID: "GHSA-next-a", Ecosystem: "npm", Package: "next", Version: "16.3.3", Severity: SeverityCritical, Source: SourceOSV, Manifest: "web/bun.lock"},
		// Dependabot reports the same advisory by an alias, with the fix version.
		{ID: "CVE-2026-1", Aliases: []string{"GHSA-next-a", "CVE-2026-1"}, Ecosystem: "npm", Package: "next", Severity: SeverityCritical, Title: "RCE", Source: SourceDependabot, FixedIn: "16.3.6", Manifest: "sandbox/package.json"},
		{ID: "GHSA-next-b", Ecosystem: "npm", Package: "next", Version: "16.2.9", Severity: SeverityCritical, FixedIn: "16.3.4", Manifest: "sandbox/bun.lock"},
		// Dependabot's "pip" is OSV's "PyPI".
		{ID: "GHSA-req", Ecosystem: "pip", Package: "Requests", Severity: SeverityCritical, FixedIn: "2.32.0"},
		// PEP 503 spells both names "requests".
		{ID: "PYSEC-1", Aliases: []string{"GHSA-req"}, Ecosystem: "PyPI", Package: "requests", Version: "2.31.0", Severity: SeverityCritical},
		// The third record links the first two, so all three are one advisory.
		{ID: "GHSA-a", Ecosystem: "npm", Package: "lodash", Severity: SeverityCritical},
		{ID: "CVE-b", Ecosystem: "npm", Package: "lodash", Severity: SeverityCritical},
		{ID: "PYSEC-c", Aliases: []string{"GHSA-a", "CVE-b"}, Ecosystem: "npm", Package: "lodash", Severity: SeverityCritical},
	}
	// A non-blocking record lends its names but adds no advisory of its own,
	// whichever side of the merge it lands on.
	scanned := []Finding{
		{ID: "OSV-2026-9", Aliases: []string{"GHSA-next-b"}, Ecosystem: "npm", Package: "next", Severity: SeverityLow},
		{ID: "GHSA-other", Ecosystem: "npm", Package: "next", Severity: SeverityLow},
		{ID: "GHSA-a", Ecosystem: "npm", Package: "lodash", Severity: SeverityLow},
	}

	got := groupAlerts(findings, scanned, "main")

	want := []Alert{
		{
			Key: "PyPI/requests", Ecosystem: "PyPI", Package: "requests",
			// The merged-in finding's own id becomes an alias.
			Advisories: []Advisory{{ID: "GHSA-req", Aliases: []string{"PYSEC-1"}, Severity: SeverityCritical, FixedIn: "2.32.0"}},
			Versions:   []string{"2.31.0"},
			Branch:     "cve-alerts/main/PyPI/requests-4238921e",
		},
		{
			Key: "npm/lodash", Ecosystem: "npm", Package: "lodash",
			Advisories: []Advisory{{ID: "GHSA-a", Aliases: []string{"PYSEC-c", "CVE-b"}, Severity: SeverityCritical}},
			Branch:     "cve-alerts/main/npm/lodash-ce6919c5",
		},
		{
			Key: "npm/next", Ecosystem: "npm", Package: "next",
			Advisories: []Advisory{
				{ID: "GHSA-next-a", Aliases: []string{"CVE-2026-1"}, Severity: SeverityCritical, Title: "RCE", FixedIn: "16.3.6"},
				{ID: "GHSA-next-b", Aliases: []string{"OSV-2026-9"}, Severity: SeverityCritical, FixedIn: "16.3.4"},
			},
			Versions:  []string{"16.2.9", "16.3.3"},
			Manifests: []string{"sandbox/bun.lock", "sandbox/package.json", "web/bun.lock"},
			Branch:    "cve-alerts/main/npm/next-df6d942f",
		},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("groupAlerts mismatch\n got: %+v\nwant: %+v", got, want)
	}
}

func TestAlertBranch_keepsKeysGitSafe(t *testing.T) {
	for key, want := range map[string]string{
		"npm/@radix-ui/react-slider": "cve-alerts/release/v4.8/npm/radix-ui/react-slider-2b362228",
		"Debian:13/libc6":            "cve-alerts/release/v4.8/Debian-13/libc6-51735b0c",
		"GitHub Actions/actions/foo": "cve-alerts/release/v4.8/GitHub-Actions/actions/foo-6e197ae6",
	} {
		if got := alertBranch("release/v4.8", key); got != want {
			t.Errorf("alertBranch(%q) = %q, want %q", key, got, want)
		}
	}
}

func TestPlanAlerts(t *testing.T) {
	alerts := []Alert{
		{Key: "npm/new", Advisories: []Advisory{{ID: "GHSA-1"}}},
		{Key: "npm/known", Advisories: []Advisory{{ID: "GHSA-2"}}},
		{Key: "npm/grew", Advisories: []Advisory{{ID: "GHSA-3"}, {ID: "GHSA-4"}}},
		// This scan named the advisory by its CVE, and the issue recorded its GHSA.
		{Key: "npm/renamed", Advisories: []Advisory{{ID: "CVE-2026-6", Aliases: []string{"GHSA-6"}}}},
		{Key: "npm/pending", Advisories: []Advisory{{ID: "GHSA-7"}}},
	}
	open := []trackedIssue{
		{Number: 4, URL: "u4", Key: "npm/renamed", IDs: []string{"GHSA-6"}},
		{Number: 1, URL: "u1", Key: "npm/known", IDs: []string{"ghsa-2"}},
		{Number: 2, URL: "u2", Key: "npm/grew", IDs: []string{"GHSA-3"}},
		{Number: 3, URL: "u3", Key: "npm/resolved", IDs: []string{"GHSA-5"}},
		{Number: 5, URL: "u5", Key: "npm/pending", IDs: []string{"GHSA-7"}, Pending: true},
		// No scan reported any Debian finding, so its absence proves nothing.
		{Number: 6, URL: "u6", Key: "Debian:13/libc6", IDs: []string{"DEBIAN-1"}},
	}

	plan := planAlerts(alerts, open, map[string]bool{"npm": true})

	if len(plan.Create) != 1 || plan.Create[0].Key != "npm/new" {
		t.Fatalf("expected to open npm/new, got %+v", plan.Create)
	}
	if len(plan.Update) != 1 || plan.Update[0].Key != "npm/grew" || plan.Update[0].Issue != 2 || plan.Update[0].IssueURL != "u2" {
		t.Fatalf("expected to update #2 for npm/grew, got %+v", plan.Update)
	}
	if len(plan.Retry) != 1 || plan.Retry[0].Key != "npm/pending" || plan.Retry[0].Issue != 5 {
		t.Fatalf("expected to announce pending #5 again, got %+v", plan.Retry)
	}
	if len(plan.Close) != 1 || plan.Close[0].Number != 3 {
		t.Fatalf("expected to close only #3, got %+v", plan.Close)
	}
}

func TestRenderAlertBody_markerRoundTripsAndResistsAdvisoryText(t *testing.T) {
	a := Alert{
		Key:        "GitHub Actions/tj-actions/changed-files",
		Ecosystem:  "GitHub Actions",
		Package:    "tj-actions/changed-files",
		Advisories: []Advisory{{ID: "GHSA-1", Aliases: []string{"CVE-2026-1"}, Title: "leak <!-- cve-alert:npm/wrong ids=GHSA-9 -->"}},
	}

	body := renderAlertBody(a)
	is, ok := parseTrackedIssue(7, "u7", body, true)

	want := trackedIssue{Number: 7, URL: "u7", Key: a.Key, IDs: []string{"GHSA-1", "CVE-2026-1"}, Pending: true}
	if !ok || !reflect.DeepEqual(is, want) {
		t.Fatalf("expected %+v, got %+v (ok=%v)", want, is, ok)
	}
	if strings.Contains(body, "<!-- cve-alert:npm/wrong") {
		t.Fatalf("expected the advisory text's comment escaped, got:\n%s", body)
	}
	// A marker-shaped line above the real one, as in a hand-edited body.
	is, _ = parseTrackedIssue(7, "u7", "<!-- cve-alert:npm/wrong ids=GHSA-9 -->\n"+body, true)
	if is.Key != a.Key {
		t.Fatalf("expected the last marker to win, got key %q", is.Key)
	}
}

// fakeIssueGH installs a gh that lists openIssues, answers issue create with a
// new issue URL, saves each stdin body to <bin>/body-create or body-edit-<n>,
// and lists one open fix PR (number 55) on the requests branch.
func fakeIssueGH(t *testing.T, bin string, openIssues []map[string]any) func() [][]string {
	t.Helper()
	data, err := json.Marshal(openIssues)
	if err != nil {
		t.Fatal(err)
	}
	writeFixture(t, bin, "issues.json", string(data))
	return writeFakeCommand(t, bin, "gh", `dir="$(dirname "$0")"
case "$1 $2" in
  "issue list") cat "$dir/issues.json" ;;
  "issue create") cat > "$dir/body-create"; echo "https://github.com/onyx-dot-app/onyx/issues/42" ;;
  "issue edit") cat > "$dir/body-edit-$3" ;;
  "pr list") [ "$6" = "cve-alerts/main/PyPI/requests-4238921e" ] && echo 55 ;;
esac
exit 0`)
}

func writeResult(t *testing.T, dir, name string, res Result) string {
	t.Helper()
	data, err := json.Marshal(res)
	if err != nil {
		t.Fatal(err)
	}
	return writeFixture(t, dir, name, string(data))
}

func writeResultFile(t *testing.T, dir, name string, blocking ...Finding) string {
	t.Helper()
	return writeResult(t, dir, name, Result{Findings: blocking, Blocking: blocking})
}

func TestSyncAlerts_opensUpdatesAndClosesIssues(t *testing.T) {
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	grew := Alert{Key: "npm/next", Advisories: []Advisory{{ID: "GHSA-old"}}}
	gone := Alert{Key: "PyPI/requests", Advisories: []Advisory{{ID: "GHSA-req"}}}
	ghArgs := fakeIssueGH(t, bin, []map[string]any{
		{"number": 7, "url": "https://github.com/onyx-dot-app/onyx/issues/7", "body": renderAlertBody(grew)},
		{"number": 8, "url": "https://github.com/onyx-dot-app/onyx/issues/8", "body": renderAlertBody(gone)},
		{"number": 9, "url": "https://github.com/onyx-dot-app/onyx/issues/9", "body": "labelled by hand, no marker"},
	})
	dir := t.TempDir()
	blocking := []Finding{
		{ID: "GHSA-old", Ecosystem: "npm", Package: "next", Severity: SeverityCritical},
		{ID: "GHSA-new", Ecosystem: "npm", Package: "next", Severity: SeverityCritical, Title: "RCE | next/og", URL: "https://osv.dev/vulnerability/GHSA-new"},
	}
	// A non-blocking PyPI finding shows the scan covered PyPI, so the missing
	// requests finding means it was fixed.
	deps := writeResult(t, dir, "deps.json", Result{
		Findings: append(slices.Clone(blocking), Finding{ID: "GHSA-low", Ecosystem: "PyPI", Package: "urllib3", Severity: SeverityLow}),
		Blocking: blocking,
	})
	image := writeResultFile(t, dir, "image.json",
		Finding{ID: "DEBIAN-CVE-1", Ecosystem: "Debian:13", Package: "libc6", Version: "2.41-12", Severity: SeverityCritical, Manifest: "docker.io/onyxdotapp/onyx-backend:edge"},
	)

	alerts, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps, image}, Scope: "main"})
	if err != nil {
		t.Fatalf("SyncAlerts: %v", err)
	}

	var keys []string
	for _, a := range alerts {
		keys = append(keys, a.Key)
	}
	if !reflect.DeepEqual(keys, []string{"Debian:13/libc6", "npm/next"}) {
		t.Fatalf("expected alerts for the new package and the new advisory, got %v", keys)
	}
	if alerts[0].Issue != 42 || alerts[0].IssueURL != "https://github.com/onyx-dot-app/onyx/issues/42" {
		t.Fatalf("expected the opened issue on the new alert, got #%d %q", alerts[0].Issue, alerts[0].IssueURL)
	}
	if alerts[1].Issue != 7 {
		t.Fatalf("expected the existing issue on the grown alert, got #%d", alerts[1].Issue)
	}

	wantGH := [][]string{
		{"issue", "list", "--label", AlertLabel, "--label", "cve-alert:main", "--state", "open", "--limit", "500", "--json", "number,url,body,labels"},
		{"label", "create", AlertLabel, "--color", "B60205", "--description", "Tracks a blocking dependency vulnerability; opened and closed by the CVE alerts workflow", "--force"},
		{"label", "create", AlertPendingLabel, "--color", "B60205", "--description", "The CVE alerts workflow has not announced this alert yet", "--force"},
		{"label", "create", "cve-alert:main", "--color", "B60205", "--description", "CVE alert on the main branch", "--force"},
		{"issue", "create", "--title", "Vulnerable dependency: libc6 (Debian:13)", "--label", AlertLabel, "--label", "cve-alert:main", "--label", AlertPendingLabel, "--body-file", "-"},
		{"issue", "edit", "7", "--add-label", AlertPendingLabel},
		{"issue", "edit", "7", "--body-file", "-"},
		{"pr", "list", "--state", "open", "--head", "cve-alerts/main/PyPI/requests-4238921e", "--json", "number", "--jq", ".[].number"},
		{"pr", "close", "55", "--comment", "This package no longer has a blocking finding: it was fixed or suppressed in the audit allowlist."},
		{"issue", "close", "8", "--comment", "This package no longer has a blocking finding: it was fixed or suppressed in the audit allowlist."},
	}
	if got := ghArgs(); !reflect.DeepEqual(got, wantGH) {
		t.Fatalf("gh calls mismatch\n got: %q\nwant: %q", got, wantGH)
	}

	// The refreshed body records both advisories, so the next sync stays quiet.
	edited, err := os.ReadFile(filepath.Join(bin, "body-edit-7"))
	if err != nil {
		t.Fatal(err)
	}
	is, ok := parseTrackedIssue(7, "", string(edited), false)
	if !ok || is.Key != "npm/next" || !reflect.DeepEqual(is.IDs, []string{"GHSA-new", "GHSA-old"}) {
		t.Fatalf("expected the marker to record both advisories, got %+v (ok=%v)", is, ok)
	}
	if !strings.Contains(string(edited), `RCE \| next/og`) {
		t.Fatalf("expected the pipe in the summary escaped for the table, got:\n%s", edited)
	}
}

func TestSyncAlerts_returnsRecordedAlertsAfterAFailedChange(t *testing.T) {
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	writeFixture(t, bin, "issues.json", "[]")
	writeFakeCommand(t, bin, "gh", `case "$1 $2" in
  "issue list") cat "$(dirname "$0")/issues.json" ;;
  "issue create")
    cat > /dev/null
    case "$4" in *broken*) echo "HTTP 502" >&2; exit 1 ;; esac
    echo "https://github.com/onyx-dot-app/onyx/issues/42" ;;
esac`)
	deps := writeResultFile(t, t.TempDir(), "deps.json",
		Finding{ID: "GHSA-1", Ecosystem: "npm", Package: "broken", Severity: SeverityCritical},
		Finding{ID: "GHSA-2", Ecosystem: "npm", Package: "next", Severity: SeverityCritical},
	)

	alerts, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps}})

	if err == nil || !strings.Contains(err.Error(), "HTTP 502") {
		t.Fatalf("expected the failed create in the error, got %v", err)
	}
	if len(alerts) != 1 || alerts[0].Key != "npm/next" || alerts[0].Issue != 42 {
		t.Fatalf("expected the alert whose issue was opened, got %+v", alerts)
	}
}

// TestSyncAlerts_reportsEachFailedGhCall makes one gh subcommand fail per case
// and checks the sync names it, keeps going, and still returns what it recorded.
func TestSyncAlerts_reportsEachFailedGhCall(t *testing.T) {
	open := []map[string]any{
		{"number": 7, "url": "u7", "body": renderAlertBody(Alert{Key: "npm/next", Advisories: []Advisory{{ID: "GHSA-old"}}})},
		{"number": 8, "url": "u8", "body": renderAlertBody(Alert{Key: "PyPI/requests", Advisories: []Advisory{{ID: "GHSA-req"}}})},
	}
	openJSON, err := json.Marshal(open)
	if err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		fail string // "<verb> <noun>" that exits 1, or a special script
		want string
	}{
		{"label create", "failed to create the cve-alert label"},
		{"issue edit", "failed to mark issue #7 pending"},
		{"issue edit --body-file", "failed to update issue #7"},
		{"pr list", "failed to find the fix PR for PyPI/requests"},
		{"pr close", "failed to close fix PR #55 for PyPI/requests"},
		{"issue close", "failed to close issue #8"},
		{"issue create", "failed to open an issue for Debian:13/libc6"},
	}
	for _, tc := range cases {
		t.Run(tc.fail, func(t *testing.T) {
			bin := fakeBinDir(t)
			chdirNewRepo(t)
			writeFixture(t, bin, "issues.json", string(openJSON))
			writeFixture(t, bin, "fail.txt", tc.fail)
			writeFakeCommand(t, bin, "gh", `dir="$(dirname "$0")"
if [ "$1 $2" = "$(cat "$dir/fail.txt")" ] || [ "$1 $2 $4" = "$(cat "$dir/fail.txt")" ]; then echo "boom" >&2; exit 1; fi
case "$1 $2" in
  "issue list") cat "$dir/issues.json" ;;
  "issue create") cat > /dev/null; echo "https://github.com/onyx-dot-app/onyx/issues/42" ;;
  "issue edit") cat > /dev/null ;;
  "pr list") [ "$6" = "cve-alerts/main/PyPI/requests-4238921e" ] && echo 55 ;;
esac
exit 0`)
			deps := writeResult(t, t.TempDir(), "deps.json", Result{
				Findings: []Finding{{ID: "GHSA-low", Ecosystem: "PyPI", Package: "urllib3", Severity: SeverityLow}},
				Blocking: []Finding{
					{ID: "GHSA-old", Ecosystem: "npm", Package: "next", Severity: SeverityCritical},
					{ID: "GHSA-new", Ecosystem: "npm", Package: "next", Severity: SeverityCritical},
					{ID: "DEBIAN-1", Ecosystem: "Debian:13", Package: "libc6", Severity: SeverityCritical},
				},
			})

			_, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps}})
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("expected an error containing %q, got %v", tc.want, err)
			}
		})
	}
}

func TestSyncAlerts_inputErrors(t *testing.T) {
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	dir := t.TempDir()
	allowlist := writeFixture(t, dir, "ignores.json", `{"ignores":[]}`)
	deps := writeResultFile(t, dir, "deps.json", Finding{ID: "GHSA-1", Ecosystem: "npm", Package: "next", Severity: SeverityCritical})

	if _, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{filepath.Join(dir, "missing.json")}, IgnoreURL: allowlist}); err == nil {
		t.Fatal("expected a missing result file to fail")
	}
	bad := writeFixture(t, dir, "bad.json", "{not json")
	if _, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{bad}, IgnoreURL: allowlist}); err == nil || !strings.Contains(err.Error(), "failed to parse audit result") {
		t.Fatalf("expected a parse error, got %v", err)
	}

	writeFakeCommand(t, bin, "gh", "echo 'not json'")
	if _, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps}, IgnoreURL: allowlist}); err == nil || !strings.Contains(err.Error(), "failed to parse cve-alert issues") {
		t.Fatalf("expected an issue list parse error, got %v", err)
	}
	writeFakeCommand(t, bin, "gh", "echo 'HTTP 500' >&2; exit 1")
	if _, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps}, IgnoreURL: allowlist}); err == nil || !strings.Contains(err.Error(), "failed to list cve-alert issues") {
		t.Fatalf("expected an issue list error, got %v", err)
	}
	writeFakeCommand(t, bin, "gh", `case "$1 $2" in "issue list") echo '[]' ;; "issue create") cat > /dev/null; echo "not a url" ;; esac; exit 0`)
	if _, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps}, IgnoreURL: allowlist}); err == nil || !strings.Contains(err.Error(), "unexpected gh issue create output") {
		t.Fatalf("expected a bad create output error, got %v", err)
	}
}

func TestSyncAlerts_dryRunLogsEveryPlannedChange(t *testing.T) {
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	grown := renderAlertBody(Alert{Key: "npm/next", Advisories: []Advisory{{ID: "GHSA-old"}}})
	pending := renderAlertBody(Alert{Key: "npm/react", Advisories: []Advisory{{ID: "GHSA-r"}}})
	gone := renderAlertBody(Alert{Key: "npm/left-pad", Advisories: []Advisory{{ID: "GHSA-gone"}}})
	fakeIssueGH(t, bin, []map[string]any{
		{"number": 1, "url": "u1", "body": grown},
		{"number": 2, "url": "u2", "body": pending, "labels": []map[string]string{{"name": AlertPendingLabel}}},
		{"number": 3, "url": "u3", "body": gone},
	})
	deps := writeResultFile(t, t.TempDir(), "deps.json",
		Finding{ID: "GHSA-old", Ecosystem: "npm", Package: "next", Severity: SeverityCritical},
		Finding{ID: "GHSA-new", Ecosystem: "npm", Package: "next", Severity: SeverityCritical, URL: "https://osv.dev/vulnerability/GHSA-new"},
		Finding{ID: "GHSA-r", Ecosystem: "npm", Package: "react", Severity: SeverityCritical},
	)

	alerts, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps}, DryRun: true})
	if err != nil {
		t.Fatalf("SyncAlerts: %v", err)
	}
	var reasons []AlertReason
	for _, a := range alerts {
		reasons = append(reasons, a.Reason)
	}
	if !reflect.DeepEqual(reasons, []AlertReason{AlertGrown, AlertRetry}) {
		t.Fatalf("expected a grown and a retried alert, got %+v", alerts)
	}
}

func TestSyncAlerts_appliesTheAllowlist(t *testing.T) {
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	ghArgs := fakeIssueGH(t, bin, []map[string]any{
		{"number": 8, "url": "u8", "body": renderAlertBody(Alert{Key: "npm/next", Advisories: []Advisory{{ID: "GHSA-next"}}})},
	})
	// The scan ran without the allowlist, so the result still blocks on it.
	blocking := []Finding{
		{ID: "GHSA-next", Ecosystem: "npm", Package: "next", Severity: SeverityCritical},
		{ID: "GHSA-flask", Aliases: []string{"GHSA-flask"}, Ecosystem: "pip", Package: "flask", Severity: SeverityCritical, Source: SourceDependabot},
	}
	// Only OSV's non-blocking record knows the PYSEC alias the allowlist names.
	// Grouping carries it to Dependabot's blocking copy.
	deps := writeResult(t, t.TempDir(), "deps.json", Result{
		Findings: append(slices.Clone(blocking), Finding{ID: "PYSEC-flask", Aliases: []string{"GHSA-flask"}, Ecosystem: "PyPI", Package: "flask", Severity: SeverityModerate}),
		Blocking: blocking,
	})
	allowlist := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores":[{"id":"GHSA-next","reason":"not reachable"},{"id":"PYSEC-flask","reason":"not reachable"}]}`)

	alerts, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps}, IgnoreURL: allowlist})
	if err != nil {
		t.Fatalf("SyncAlerts: %v", err)
	}
	if len(alerts) != 0 {
		t.Fatalf("expected no alerts for a suppressed advisory, got %+v", alerts)
	}
	calls := ghArgs()
	if last := calls[len(calls)-1]; last[0] != "issue" || last[1] != "close" || last[2] != "8" {
		t.Fatalf("expected the suppressed package's issue closed, got %q", calls)
	}

	_, err = SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps}, IgnoreURL: filepath.Join(t.TempDir(), "missing.json")})
	if err == nil || !strings.Contains(err.Error(), "failed to fetch the allowlist") {
		t.Fatalf("expected an unreadable allowlist to fail the sync, got %v", err)
	}
}

func TestSyncAlerts_failsAtTheIssueLimit(t *testing.T) {
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	open := make([]map[string]any, alertIssueLimit)
	for i := range open {
		open[i] = map[string]any{"number": i + 1, "url": "u", "body": renderAlertBody(Alert{Key: "npm/p" + strconv.Itoa(i), Advisories: []Advisory{{ID: "GHSA-1"}}})}
	}
	ghArgs := fakeIssueGH(t, bin, open)
	deps := writeResultFile(t, t.TempDir(), "deps.json", Finding{ID: "GHSA-1", Ecosystem: "npm", Package: "next", Severity: SeverityCritical})

	_, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps}})

	if err == nil || !strings.Contains(err.Error(), "the most a sync reads") {
		t.Fatalf("expected the sync to refuse a possibly truncated issue list, got %v", err)
	}
	if got := ghArgs(); len(got) != 1 {
		t.Fatalf("expected no issue changes, got %q", got)
	}
}

func TestSyncAlerts_dryRunChangesNothing(t *testing.T) {
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	ghArgs := fakeIssueGH(t, bin, []map[string]any{
		{"number": 8, "url": "u8", "body": renderAlertBody(Alert{Key: "PyPI/requests", Advisories: []Advisory{{ID: "GHSA-req"}}})},
	})
	deps := writeResultFile(t, t.TempDir(), "deps.json",
		Finding{ID: "GHSA-new", Ecosystem: "npm", Package: "next", Severity: SeverityCritical},
	)

	alerts, err := SyncAlerts(SyncAlertsOptions{ResultFiles: []string{deps}, DryRun: true})
	if err != nil {
		t.Fatalf("SyncAlerts: %v", err)
	}
	if len(alerts) != 1 || alerts[0].Key != "npm/next" || alerts[0].Issue != 0 {
		t.Fatalf("expected one unopened alert for npm/next, got %+v", alerts)
	}
	if got := ghArgs(); len(got) != 1 || got[0][1] != "list" {
		t.Fatalf("expected only the issue list call, got %q", got)
	}
}
