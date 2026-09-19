package audit

import (
	"bytes"
	"encoding/json"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// fakeDependabot installs a gh that prints alertsJSON, and returns its args log.
func fakeDependabot(t *testing.T, bin, alertsJSON string) func() [][]string {
	t.Helper()
	writeFixture(t, bin, "alerts.json", alertsJSON)
	return writeFakeCommand(t, bin, "gh", `cat "$(dirname "$0")/alerts.json"`)
}

func findingIDs(findings []Finding) []string {
	ids := make([]string, 0, len(findings))
	for _, f := range findings {
		ids = append(ids, f.ID)
	}
	return ids
}

func TestRun_combinesBackendsAndAppliesTheAllowlist(t *testing.T) {
	bin := fakeBinDir(t)
	root := chdirNewRepo(t)
	// An empty lockfile scans cleanly without querying OSV.dev.
	writeFixture(t, root, "uv.lock", "")
	ghArgs := fakeDependabot(t, bin, dependabotFixture)
	allowlist := writeFixture(t, t.TempDir(), "ignores.json", `{"ignores":[{"id":"GHSA-dddd","reason":"not reachable"}]}`)

	var stdout, stderr bytes.Buffer
	res, err := Run(Options{
		Format:    "json",
		FailOn:    SeverityHigh,
		IgnoreURL: allowlist,
		Stdout:    &stdout,
		Stderr:    &stderr,
	})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}

	if got := findingIDs(res.Findings); !reflect.DeepEqual(got, []string{"GHSA-aaaa-bbbb-cccc"}) {
		t.Fatalf("expected findings [GHSA-aaaa-bbbb-cccc], got %v", got)
	}
	if got := findingIDs(res.Ignored); !reflect.DeepEqual(got, []string{"GHSA-dddd"}) {
		t.Fatalf("expected ignored [GHSA-dddd], got %v", got)
	}
	if got := findingIDs(res.Blocking); !reflect.DeepEqual(got, []string{"GHSA-aaaa-bbbb-cccc"}) {
		t.Fatalf("expected blocking [GHSA-aaaa-bbbb-cccc], got %v", got)
	}
	if got := res.Findings[0].Manifest; got != "pyproject.toml" {
		t.Fatalf("expected manifest %q, got %q", "pyproject.toml", got)
	}

	// The lone json format goes to stdout and round-trips the result.
	var decoded Result
	if err := json.Unmarshal(stdout.Bytes(), &decoded); err != nil {
		t.Fatalf("stdout is not a JSON result: %v\n%s", err, stdout.String())
	}
	if !reflect.DeepEqual(&decoded, res) {
		t.Fatalf("expected stdout to encode %+v, got %+v", res, decoded)
	}
	if stderr.Len() != 0 {
		t.Fatalf("expected nothing on stderr, got %q", stderr.String())
	}

	wantGH := [][]string{{"api", "repos/{owner}/{repo}/dependabot/alerts", "--paginate", "-f", "state=open", "-f", "per_page=100"}}
	if got := ghArgs(); !reflect.DeepEqual(got, wantGH) {
		t.Fatalf("expected gh calls %q, got %q", wantGH, got)
	}
}

func TestRun_unavailableAllowlistStillBlocks(t *testing.T) {
	bin := fakeBinDir(t)
	chdirNewRepo(t)
	fakeDependabot(t, bin, dependabotFixture)

	var stdout bytes.Buffer
	res, err := Run(Options{
		Dependabot: true,
		Format:     "text",
		FailOn:     SeverityCritical,
		IgnoreURL:  filepath.Join(t.TempDir(), "missing.json"),
		Stdout:     &stdout,
		Stderr:     &bytes.Buffer{},
	})
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if len(res.Ignored) != 0 {
		t.Fatalf("expected no suppressions, got %v", findingIDs(res.Ignored))
	}
	if got := findingIDs(res.Blocking); !reflect.DeepEqual(got, []string{"GHSA-aaaa-bbbb-cccc"}) {
		t.Fatalf("expected blocking [GHSA-aaaa-bbbb-cccc], got %v", got)
	}
	if !strings.Contains(stdout.String(), "Action required: 1 finding(s)") {
		t.Fatalf("expected the runbook in the text report, got:\n%s", stdout.String())
	}
}

func TestRun_lockfileScanDowngradesOtherBackendFailures(t *testing.T) {
	bin := fakeBinDir(t)
	root := chdirNewRepo(t)
	writeFixture(t, root, "uv.lock", "")
	writeFakeCommand(t, bin, "gh", "echo 'gh: Not Found (HTTP 404)' >&2\nexit 1")
	// A file where the workflows directory belongs makes the actions scan fail.
	writeFixture(t, root, ".github/workflows", "not a directory")

	var stdout bytes.Buffer
	res, err := Run(Options{Format: "text", FailOn: SeverityCritical, Stdout: &stdout, Stderr: &bytes.Buffer{}})
	if err != nil {
		t.Fatalf("expected the failures to be warnings, got %v", err)
	}
	if len(res.Findings) != 0 || len(res.Blocking) != 0 {
		t.Fatalf("expected a clean result, got %+v", res)
	}
	if got := strings.TrimSpace(stdout.String()); got != "No dependency vulnerabilities found." {
		t.Fatalf("expected the clean text report, got %q", got)
	}
}

func TestRun_errors(t *testing.T) {
	cases := []struct {
		name  string
		setup func(t *testing.T, bin, root string)
		opts  Options
		want  string
	}{
		{
			name: "explicit dependabot failure",
			setup: func(t *testing.T, bin, root string) {
				writeFakeCommand(t, bin, "gh", "exit 1")
			},
			opts: Options{Dependabot: true},
			want: "dependabot audit failed",
		},
		{
			name: "explicit actions failure",
			setup: func(t *testing.T, bin, root string) {
				writeFixture(t, root, ".github/workflows", "not a directory")
			},
			opts: Options{Actions: true},
			want: "github actions audit failed",
		},
		{
			name: "unscannable lockfile",
			setup: func(t *testing.T, bin, root string) {
				writeFixture(t, root, "web/bun.lock", "{not json")
			},
			opts: Options{Web: true},
			want: "dependency scan failed",
		},
		{
			name: "unknown format",
			setup: func(t *testing.T, bin, root string) {
				writeFixture(t, root, "uv.lock", "")
			},
			opts: Options{Python: true, Format: "xml"},
			want: `unknown format "xml"`,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			bin := fakeBinDir(t)
			root := chdirNewRepo(t)
			tc.setup(t, bin, root)
			tc.opts.FailOn = SeverityCritical
			tc.opts.Stdout = &bytes.Buffer{}
			tc.opts.Stderr = &bytes.Buffer{}

			res, err := Run(tc.opts)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("expected an error containing %q, got result %+v and error %v", tc.want, res, err)
			}
		})
	}

	t.Run("outside a git repository", func(t *testing.T) {
		chdirOutsideRepo(t)
		_, err := Run(Options{Python: true, Stdout: &bytes.Buffer{}, Stderr: &bytes.Buffer{}})
		if err == nil || !strings.Contains(err.Error(), "failed to locate lockfiles") {
			t.Fatalf("expected a lockfile location error, got %v", err)
		}
	})
}

func TestLockfilePaths_selectsExistingLockfiles(t *testing.T) {
	root := chdirNewRepo(t)
	writeFixture(t, root, "web/bun.lock", "")
	writeFixture(t, root, "uv.lock", "")
	// A directory named like a lockfile is not a lockfile.
	writeFixture(t, root, "bun.lock/placeholder", "")

	cases := []struct {
		name        string
		web, python bool
		want        []string
	}{
		{"web", true, false, []string{filepath.Join(root, "web", "bun.lock")}},
		{"python", false, true, []string{filepath.Join(root, "uv.lock")}},
		{"both", true, true, []string{filepath.Join(root, "web", "bun.lock"), filepath.Join(root, "uv.lock")}},
		{"neither", false, false, nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := lockfilePaths(tc.web, tc.python)
			if err != nil {
				t.Fatalf("lockfilePaths: %v", err)
			}
			if !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("expected %v, got %v", tc.want, got)
			}
		})
	}
}

func TestScanLockfiles_missingLockfileFails(t *testing.T) {
	if _, err := scanLockfiles([]string{filepath.Join(t.TempDir(), "uv.lock")}); err == nil {
		t.Fatal("expected an error for a missing lockfile")
	}
}

func TestRelManifest(t *testing.T) {
	root := filepath.FromSlash("/repo")
	cases := []struct {
		name, path, want string
	}{
		{"empty", "", ""},
		{"under the root", filepath.Join(root, "web", "bun.lock"), "web/bun.lock"},
		{"outside the root", filepath.FromSlash("/elsewhere/./uv.lock"), "/elsewhere/uv.lock"},
		{"image ref", "docker.io/onyx/backend:v1", "docker.io/onyx/backend:v1"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := relManifest(root, tc.path); got != tc.want {
				t.Fatalf("expected %q, got %q", tc.want, got)
			}
		})
	}
}

func TestSortFindings_bySeverityThenEcosystemPackageAndID(t *testing.T) {
	findings := []Finding{
		{ID: "low", Ecosystem: "npm", Package: "a", Severity: SeverityLow},
		{ID: "unknown", Ecosystem: "npm", Package: "a", Severity: SeverityUnknown},
		{ID: "crit-pypi", Ecosystem: "PyPI", Package: "a", Severity: SeverityCritical},
		{ID: "crit-npm-b", Ecosystem: "npm", Package: "b", Severity: SeverityCritical},
		{ID: "crit-npm-a-2", Ecosystem: "npm", Package: "a", Severity: SeverityCritical},
		{ID: "crit-npm-a-1", Ecosystem: "npm", Package: "a", Severity: SeverityCritical},
		{ID: "moderate", Ecosystem: "npm", Package: "a", Severity: SeverityModerate},
		{ID: "high", Ecosystem: "npm", Package: "a", Severity: SeverityHigh},
	}
	sortFindings(findings)

	want := []string{"crit-pypi", "crit-npm-a-1", "crit-npm-a-2", "crit-npm-b", "high", "moderate", "low", "unknown"}
	if got := findingIDs(findings); !reflect.DeepEqual(got, want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
}
