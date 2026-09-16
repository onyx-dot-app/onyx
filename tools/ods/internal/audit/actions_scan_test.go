package audit

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"sort"
	"strings"
	"sync"
	"testing"
)

const (
	changedFilesFixedSHA    = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	changedFilesUntaggedSHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
)

// fakeOSV serves canned advisories per action name and records every queried
// name. Names listed in failing get a 500.
type fakeOSV struct {
	t          *testing.T
	advisories map[string][]osvVuln
	failing    map[string]bool

	mu      sync.Mutex
	queried []string
}

func (f *fakeOSV) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		f.t.Errorf("expected POST, got %s", r.Method)
	}
	if got := r.Header.Get("Content-Type"); got != "application/json" {
		f.t.Errorf("expected content type %q, got %q", "application/json", got)
	}
	var body struct {
		Package osvPackage `json:"package"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		f.t.Errorf("failed to decode the query: %v", err)
	}
	if body.Package.Ecosystem != actionsEcosystem {
		f.t.Errorf("expected ecosystem %q, got %q", actionsEcosystem, body.Package.Ecosystem)
	}
	f.mu.Lock()
	f.queried = append(f.queried, body.Package.Name)
	f.mu.Unlock()

	if f.failing[body.Package.Name] {
		w.WriteHeader(http.StatusInternalServerError)
		return
	}
	if err := json.NewEncoder(w).Encode(map[string]any{"vulns": f.advisories[body.Package.Name]}); err != nil {
		f.t.Errorf("failed to write the response: %v", err)
	}
}

func (f *fakeOSV) queriedNames() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	names := append([]string(nil), f.queried...)
	sort.Strings(names)
	return names
}

func startFakeOSV(t *testing.T, advisories map[string][]osvVuln, failing ...string) (*fakeOSV, string) {
	t.Helper()
	fake := &fakeOSV{t: t, advisories: advisories, failing: map[string]bool{}}
	for _, name := range failing {
		fake.failing[name] = true
	}
	server := httptest.NewServer(fake)
	t.Cleanup(server.Close)
	return fake, server.URL
}

// writeActionsRepo lays out workflows and composite actions that exercise tag
// pins, SHA pins (resolvable and not), duplicates, and files the scan must skip.
func writeActionsRepo(t *testing.T, root string) {
	t.Helper()
	writeFixture(t, root, ".github/workflows/ci.yml", `on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: tj-actions/changed-files@v45.0.7
      - uses: tj-actions/changed-files@`+changedFilesFixedSHA+`
      - uses: tj-actions/changed-files@`+changedFilesUntaggedSHA+`
`)
	// Same ref as ci.yml: collapses into the ci.yml finding.
	writeFixture(t, root, ".github/workflows/release.yaml", `on: push
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: tj-actions/changed-files@v45.0.7
`)
	writeFixture(t, root, ".github/workflows/README.md", "uses: evil/not-a-workflow@v1\n")
	writeFixture(t, root, ".github/workflows/nested/skipped.yml", `jobs:
  x:
    steps:
      - uses: evil/nested@v1
`)
	writeFixture(t, root, ".github/actions/setup/action.yml", `name: setup
runs:
  using: composite
  steps:
    - uses: docker/login-action@v3
    - run: echo hi
      shell: bash
`)
	writeFixture(t, root, ".github/actions/node/action.yaml", "name: node\nruns:\n  using: node20\n  main: index.js\n")
	writeFixture(t, root, ".github/actions/empty/action.yml", "name: empty\nruns:\n  using: composite\n")
	writeFixture(t, root, ".github/actions/norun/action.yml", "name: metadata only\n")
	writeFixture(t, root, ".github/actions/broken/action.yml", "runs: [unclosed")
}

func changedFilesAdvisory() osvVuln {
	v := ecoVuln("GHSA-mrrh-fwg8-r2c3", map[string]string{"introduced": "0"}, map[string]string{"fixed": "46.0.1"})
	v.Summary = "changed-files leaks secrets"
	v.DatabaseSpecific = map[string]any{"severity": "HIGH"}
	return v
}

func loginActionAdvisory() osvVuln {
	v := ecoVuln("GHSA-dock", map[string]string{"introduced": "0"}, map[string]string{"fixed": "3.1.0"})
	v.Details = "Login action leaks credentials\nMore detail."
	v.DatabaseSpecific = map[string]any{"severity": "moderate"}
	v.Affected[0].Package.Name = "docker/login-action"
	return v
}

// findingKeys summarizes findings as sorted "id package@version manifest
// severity title" lines, since the scan does not order its output.
func findingKeys(findings []Finding) []string {
	keys := make([]string, 0, len(findings))
	for _, f := range findings {
		keys = append(keys, strings.Join([]string{f.ID, f.Package + "@" + f.Version, f.Manifest, string(f.Severity), f.Title}, " "))
	}
	sort.Strings(keys)
	return keys
}

func TestScanActions_matchesAdvisoriesAcrossWorkflowsAndCompositeActions(t *testing.T) {
	bin := fakeBinDir(t)
	root := chdirNewRepo(t)
	writeActionsRepo(t, root)

	writeFixture(t, bin, "tags.json", `[{"name":"v46.0.2","commit":{"sha":"`+changedFilesFixedSHA+`"}},{"name":"v46","commit":{"sha":"`+changedFilesFixedSHA+`"}}]`)
	ghArgs := writeFakeCommand(t, bin, "gh", `cat "$(dirname "$0")/tags.json"`)

	osv, url := startFakeOSV(t, map[string][]osvVuln{
		"tj-actions/changed-files": {changedFilesAdvisory()},
		"docker/login-action":      {loginActionAdvisory()},
	})

	findings, err := scanActions(url)
	if err != nil {
		t.Fatalf("scanActions: %v", err)
	}

	want := []string{
		"GHSA-dock docker/login-action@v3 .github/actions/setup/action.yml moderate Login action leaks credentials",
		"GHSA-mrrh-fwg8-r2c3 tj-actions/changed-files@" + changedFilesUntaggedSHA + " .github/workflows/ci.yml unknown unverified pin — changed-files leaks secrets",
		"GHSA-mrrh-fwg8-r2c3 tj-actions/changed-files@v45.0.7 .github/workflows/ci.yml high changed-files leaks secrets",
	}
	if got := findingKeys(findings); !reflect.DeepEqual(got, want) {
		t.Fatalf("expected findings\n%s\ngot\n%s", strings.Join(want, "\n"), strings.Join(got, "\n"))
	}

	// One query per action name; skipped files contribute nothing.
	wantQueried := []string{"actions/checkout", "docker/login-action", "tj-actions/changed-files"}
	if got := osv.queriedNames(); !reflect.DeepEqual(got, wantQueried) {
		t.Fatalf("expected queries for %v, got %v", wantQueried, got)
	}

	// Both SHA pins share a single tag lookup; tag pins need none.
	wantGH := [][]string{{"api", "repos/tj-actions/changed-files/tags?per_page=100", "--paginate"}}
	if got := ghArgs(); !reflect.DeepEqual(got, wantGH) {
		t.Fatalf("expected gh calls %q, got %q", wantGH, got)
	}
}

func TestScanActions_skipsTagLookupsWithoutAdvisories(t *testing.T) {
	bin := fakeBinDir(t)
	root := chdirNewRepo(t)
	writeActionsRepo(t, root)
	ghArgs := writeFakeCommand(t, bin, "gh", "exit 1")
	_, url := startFakeOSV(t, nil)

	findings, err := scanActions(url)
	if err != nil {
		t.Fatalf("scanActions: %v", err)
	}
	if findings != nil {
		t.Fatalf("expected no findings, got %+v", findings)
	}
	if got := ghArgs(); got != nil {
		t.Fatalf("expected no gh calls, got %q", got)
	}
}

func TestScanActions_toleratesPartialQueryFailures(t *testing.T) {
	root := chdirNewRepo(t)
	writeActionsRepo(t, root)
	_, url := startFakeOSV(t, map[string][]osvVuln{
		"docker/login-action": {loginActionAdvisory()},
	}, "tj-actions/changed-files", "actions/checkout")

	findings, err := scanActions(url)
	if err != nil {
		t.Fatalf("scanActions: %v", err)
	}
	if len(findings) != 1 || findings[0].ID != "GHSA-dock" {
		t.Fatalf("expected only the GHSA-dock finding, got %+v", findings)
	}
}

func TestScanActions_failsWhenEveryQueryFails(t *testing.T) {
	root := chdirNewRepo(t)
	writeActionsRepo(t, root)
	_, url := startFakeOSV(t, nil, "tj-actions/changed-files", "actions/checkout", "docker/login-action")

	findings, err := scanActions(url)
	if err == nil {
		t.Fatalf("expected an error, got findings %+v", findings)
	}
	if want := "all 3 OSV.dev advisory queries failed"; err.Error() != want {
		t.Fatalf("expected %q, got %q", want, err.Error())
	}
}

func TestScanActions_noActionsReferenced(t *testing.T) {
	chdirNewRepo(t)
	osv, url := startFakeOSV(t, nil)

	findings, err := scanActions(url)
	if err != nil || findings != nil {
		t.Fatalf("expected (nil, nil), got (%+v, %v)", findings, err)
	}
	if got := osv.queriedNames(); len(got) != 0 {
		t.Fatalf("expected no OSV queries, got %v", got)
	}
}

func TestScanActions_errors(t *testing.T) {
	t.Run("outside a git repository", func(t *testing.T) {
		chdirOutsideRepo(t)
		if _, err := scanActions("http://127.0.0.1:0"); err == nil {
			t.Fatal("expected an error outside a git repository")
		}
	})

	t.Run("unreadable workflows directory", func(t *testing.T) {
		root := chdirNewRepo(t)
		// A file where the workflows directory belongs cannot be listed.
		writeFixture(t, root, ".github/workflows", "not a directory")
		if _, err := scanActions("http://127.0.0.1:0"); err == nil {
			t.Fatal("expected an error when .github/workflows is not a directory")
		}
	})

	danglingManifests := []string{
		filepath.Join(".github", "workflows", "gone.yml"),
		filepath.Join(".github", "actions", "gone", "action.yml"),
	}
	for _, rel := range danglingManifests {
		t.Run("unreadable "+filepath.ToSlash(rel), func(t *testing.T) {
			if runtime.GOOS == "windows" {
				t.Skip("creating symlinks needs extra privileges on Windows")
			}
			root := chdirNewRepo(t)
			manifest := filepath.Join(root, rel)
			if err := os.MkdirAll(filepath.Dir(manifest), 0o755); err != nil {
				t.Fatal(err)
			}
			// A dangling symlink is listed as a file but cannot be read.
			if err := os.Symlink(filepath.Join(root, "missing.yml"), manifest); err != nil {
				t.Fatal(err)
			}
			_, err := scanActions("http://127.0.0.1:0")
			if !errors.Is(err, os.ErrNotExist) {
				t.Fatalf("expected the read error for the dangling %s, got %v", rel, err)
			}
		})
	}
}

func TestQueryActionAdvisories(t *testing.T) {
	t.Run("returns the advisories", func(t *testing.T) {
		_, url := startFakeOSV(t, map[string][]osvVuln{"a/b": {changedFilesAdvisory()}})
		vulns, err := queryActionAdvisories(http.DefaultClient, url, "a/b")
		if err != nil {
			t.Fatalf("queryActionAdvisories: %v", err)
		}
		if len(vulns) != 1 || vulns[0].ID != "GHSA-mrrh-fwg8-r2c3" || vulns[0].Affected[0].Ranges[0].Events[1]["fixed"] != "46.0.1" {
			t.Fatalf("expected the decoded GHSA-mrrh-fwg8-r2c3 advisory, got %+v", vulns)
		}
	})

	failures := []struct {
		name    string
		handler http.HandlerFunc
		want    string
	}{
		{
			name:    "non-200 status",
			handler: func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusServiceUnavailable) },
			want:    "osv.dev returned status 503",
		},
		{
			name: "malformed body",
			handler: func(w http.ResponseWriter, r *http.Request) {
				_, _ = w.Write([]byte("{not json"))
			},
			want: "invalid character",
		},
	}
	for _, tc := range failures {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(tc.handler)
			defer server.Close()
			_, err := queryActionAdvisories(http.DefaultClient, server.URL, "a/b")
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("expected an error containing %q, got %v", tc.want, err)
			}
		})
	}

	t.Run("unreachable server", func(t *testing.T) {
		server := httptest.NewServer(http.NotFoundHandler())
		url := server.URL
		server.Close()
		if _, err := queryActionAdvisories(http.DefaultClient, url, "a/b"); err == nil {
			t.Fatal("expected an error for a closed server")
		}
	})

	t.Run("invalid url", func(t *testing.T) {
		if _, err := queryActionAdvisories(http.DefaultClient, "http://[::1", "a/b"); err == nil {
			t.Fatal("expected an error for an invalid URL")
		}
	})
}

func TestResolveActionTags_errors(t *testing.T) {
	t.Run("gh failure includes its stderr", func(t *testing.T) {
		bin := fakeBinDir(t)
		writeFakeCommand(t, bin, "gh", "echo 'HTTP 404: Not Found' >&2\nexit 1")
		_, err := resolveActionTags("a/b")
		if err == nil || !strings.Contains(err.Error(), "HTTP 404: Not Found") {
			t.Fatalf("expected the gh stderr in the error, got %v", err)
		}
	})

	t.Run("gh not installed", func(t *testing.T) {
		t.Setenv("PATH", t.TempDir())
		if _, err := resolveActionTags("a/b"); err == nil {
			t.Fatal("expected an error without gh on PATH")
		}
	})

	t.Run("unparseable output", func(t *testing.T) {
		bin := fakeBinDir(t)
		writeFakeCommand(t, bin, "gh", "echo 'not json'")
		_, err := resolveActionTags("a/b")
		if err == nil || !strings.Contains(err.Error(), "failed to parse tags for a/b") {
			t.Fatalf("expected a parse error, got %v", err)
		}
	})
}

func TestActionVersion_shaPinCachesFailedLookups(t *testing.T) {
	bin := fakeBinDir(t)
	ghArgs := writeFakeCommand(t, bin, "gh", "exit 1")
	cache := map[string][]ghTag{}
	ref := actionRef{Name: "a/b", Ref: changedFilesFixedSHA, IsSHA: true}

	for i := 0; i < 2; i++ {
		if v, ok := actionVersion(ref, cache); ok {
			t.Fatalf("expected an unresolved pin, got %q", v)
		}
	}
	if got := ghArgs(); len(got) != 1 {
		t.Fatalf("expected one gh call for two lookups, got %q", got)
	}
}

func TestActionTitle(t *testing.T) {
	cases := []struct {
		name string
		vuln osvVuln
		want string
	}{
		{"summary wins", osvVuln{Summary: " Summary ", Details: "details"}, "Summary"},
		{"first line of details", osvVuln{Details: "  First line \nsecond"}, "First line"},
		{"single-line details", osvVuln{Details: " only line "}, "only line"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := actionTitle(tc.vuln); got != tc.want {
				t.Fatalf("expected %q, got %q", tc.want, got)
			}
		})
	}
}

func TestExtractCompositeActions_manifestsAreRepoRelative(t *testing.T) {
	root := t.TempDir()
	writeFixture(t, root, filepath.Join(".github", "actions", "b", "action.yml"), "runs:\n  using: composite\n  steps:\n    - uses: z/z@v1\n")
	writeFixture(t, root, filepath.Join(".github", "actions", "a", "action.yml"), "runs:\n  using: composite\n  steps:\n    - uses: y/y@v2\n    - uses: x/x@v1\n")

	refs, err := extractActions(root)
	if err != nil {
		t.Fatalf("extractActions: %v", err)
	}
	// Sorted by manifest, then name@ref, regardless of walk order.
	want := []actionRef{
		{Name: "x/x", Ref: "v1", Manifest: ".github/actions/a/action.yml"},
		{Name: "y/y", Ref: "v2", Manifest: ".github/actions/a/action.yml"},
		{Name: "z/z", Ref: "v1", Manifest: ".github/actions/b/action.yml"},
	}
	if !reflect.DeepEqual(refs, want) {
		t.Fatalf("expected %+v, got %+v", want, refs)
	}
}
