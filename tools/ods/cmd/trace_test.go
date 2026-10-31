package cmd

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	log "github.com/sirupsen/logrus"
)

// kubeGHDownloadScript fakes gh: --version succeeds, `run list` prints runs,
// and `run download <id> --dir <dir> ...` creates a trace.zip for each
// "<artifact>/<test>" entry.
func kubeGHDownloadScript(runs string, traces ...string) string {
	var download strings.Builder
	for _, tr := range traces {
		download.WriteString(`/bin/mkdir -p "$5/` + tr + `" &&: > "$5/` + tr + `/trace.zip"; `)
	}
	return `case "$1 $2" in
  "run list") printf '%s' '` + runs + `' ;;
  "run download") ` + download.String() + `;;
esac
`
}

// kubeTraceDir creates a trace.zip at each relative directory under root.
func kubeTraceDir(t *testing.T, root string, dirs ...string) {
	t.Helper()
	for _, d := range dirs {
		if err := os.MkdirAll(filepath.Join(root, d), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, d, "trace.zip"), nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func TestParseRunIDFromArg(t *testing.T) {
	cases := []struct {
		arg     string
		want    string
		wantErr bool
	}{
		{arg: "12345678", want: "12345678"},
		{arg: "https://github.com/onyx-dot-app/onyx/actions/runs/987/job/1", want: "987"},
		{arg: "12a", wantErr: true},
		{arg: "https://github.com/onyx-dot-app/onyx/pull/9500", wantErr: true},
	}
	for _, c := range cases {
		t.Run(c.arg, func(t *testing.T) {
			got, err := parseRunIDFromArg(c.arg)
			if c.wantErr {
				if err == nil || !strings.HasPrefix(err.Error(), "could not parse run ID from") {
					t.Fatalf("expected a parse error, got %q, %v", got, err)
				}
				return
			}
			if err != nil || got != c.want {
				t.Fatalf("expected %q, got %q, %v", c.want, got, err)
			}
		})
	}
}

func TestParseTraceSelection(t *testing.T) {
	cases := []struct {
		input string
		max   int
		want  []int
	}{
		{"1,3", 5, []int{0, 2}},
		{"2-4", 5, []int{1, 2, 3}},
		{"4-2", 5, nil},
		{"0,6,3", 5, []int{2}},
		{"5-9", 6, []int{4, 5}},
		{"1-3,2,1", 5, []int{0, 1, 2}},
		{" 2 , ,1 ", 5, []int{1, 0}},
		{"a,x-3,1-b,2", 5, []int{1}},
		{"-1", 5, nil},
	}
	for _, c := range cases {
		t.Run(c.input, func(t *testing.T) {
			if got := parseTraceSelection(c.input, c.max); !slices.Equal(got, c.want) {
				t.Fatalf("expected %v, got %v", c.want, got)
			}
		})
	}
}

func TestExtractProject(t *testing.T) {
	cases := []struct {
		artifactDir string
		want        string
	}{
		{"playwright-test-results-admin-42", "admin"},
		{"playwright-test-results-admin-shard-1-42", "admin-shard-1"},
		{"playwright-test-results-lite-420", "lite-420"},
		{"playwright-test-results--42", "playwright-test-results--42"},
		{"", ""},
	}
	for _, c := range cases {
		if got := extractProject(c.artifactDir, "42"); got != c.want {
			t.Fatalf("extractProject(%q): expected %q, got %q", c.artifactDir, c.want, got)
		}
	}
}

func TestGroupByProject_ordersAdminExclusiveLiteThenOthers(t *testing.T) {
	traces := []traceInfo{
		{Project: "zeta"}, {Project: "lite"}, {Project: "admin-shard-2"},
		{Project: "exclusive"}, {Project: "lite"}, {Project: "admin"}, {Project: "alpha"},
	}

	want := []string{"admin", "admin-shard-2", "exclusive", "lite", "alpha", "zeta"}
	if got := groupByProject(traces); !slices.Equal(got, want) {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestFindTraces_returnsSortedTraceZips(t *testing.T) {
	root := t.TempDir()
	kubeTraceDir(t, root, "b/test", "a/test", "a/test/retry")
	if err := os.WriteFile(filepath.Join(root, "a", "trace.json"), nil, 0o644); err != nil {
		t.Fatal(err)
	}

	got, err := findTraces(root)
	if err != nil {
		t.Fatalf("findTraces: %v", err)
	}
	want := []string{
		filepath.Join(root, "a/test/retry/trace.zip"),
		filepath.Join(root, "a/test/trace.zip"),
		filepath.Join(root, "b/test/trace.zip"),
	}
	if !slices.Equal(got, want) {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestFindTraces_failsOnAMissingDirectory(t *testing.T) {
	if _, err := findTraces(filepath.Join(t.TempDir(), "missing")); err == nil {
		t.Fatal("expected an error")
	}
	if _, err := findTraceInfos(filepath.Join(t.TempDir(), "missing"), "42"); err == nil {
		t.Fatal("expected an error")
	}
}

func TestFindTraceInfos_groupsAndSortsTraces(t *testing.T) {
	root := t.TempDir()
	kubeTraceDir(t, root,
		"playwright-test-results-lite-42/test-b",
		"playwright-test-results-admin-42/test-z",
		"playwright-test-results-admin-42/test-a/retry",
		"playwright-test-results-admin-42/test-a",
		"",
	)

	got, err := findTraceInfos(root, "42")
	if err != nil {
		t.Fatalf("findTraceInfos: %v", err)
	}
	want := []traceInfo{
		{Path: filepath.Join(root, "playwright-test-results-admin-42/test-a/retry/trace.zip"), Project: "admin", TestDir: "test-a"},
		{Path: filepath.Join(root, "playwright-test-results-admin-42/test-a/trace.zip"), Project: "admin", TestDir: "test-a"},
		{Path: filepath.Join(root, "playwright-test-results-admin-42/test-z/trace.zip"), Project: "admin", TestDir: "test-z"},
		{Path: filepath.Join(root, "playwright-test-results-lite-42/test-b/trace.zip"), Project: "lite", TestDir: "test-b"},
		// A trace outside any artifact directory is named after its parent.
		{Path: filepath.Join(root, "trace.zip"), Project: "", TestDir: filepath.Base(root)},
	}
	if !slices.Equal(got, want) {
		t.Fatalf("expected %+v, got %+v", want, got)
	}
}

func TestPrintTraceList_numbersTracesAcrossProjects(t *testing.T) {
	traces := []traceInfo{
		{Project: "admin", TestDir: "login"},
		{Project: "admin", TestDir: "settings"},
		{Project: "lite", TestDir: "chat"},
	}

	var out bytes.Buffer
	printTraceList(&out, traces, []string{"admin", "lite"})

	want := "\nFound 3 trace(s) across 2 project(s):\n" +
		"\n  admin (2):\n    [ 1] login\n    [ 2] settings\n" +
		"\n  lite (1):\n    [ 3] chat\n"
	if out.String() != want {
		t.Fatalf("expected %q, got %q", want, out.String())
	}
}

func TestPromptTraceSelection(t *testing.T) {
	traces := []traceInfo{
		{Path: "1", Project: "admin"},
		{Path: "2", Project: "lite"},
		{Path: "3", Project: "lite"},
	}
	cases := []struct {
		name  string
		input string
		want  []string
	}{
		{"empty opens all", "\n", []string{"1", "2", "3"}},
		{"all is case-insensitive", " ALL \n", []string{"1", "2", "3"}},
		{"project name", "Lite\n", []string{"2", "3"}},
		{"numbers", "3,1\n", []string{"3", "1"}},
		{"nothing valid opens all", "9\n", []string{"1", "2", "3"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			selected, err := promptTraceSelection(io.Discard, strings.NewReader(c.input), traces, []string{"admin", "lite"})
			if err != nil {
				t.Fatalf("promptTraceSelection: %v", err)
			}
			var got []string
			for _, s := range selected {
				got = append(got, s.Path)
			}
			if !slices.Equal(got, c.want) {
				t.Fatalf("expected %q, got %q", c.want, got)
			}
		})
	}

	t.Run("closed input", func(t *testing.T) {
		_, err := promptTraceSelection(io.Discard, strings.NewReader(""), traces, []string{"admin", "lite"})
		if err == nil || err.Error() != "Failed to read input: EOF" {
			t.Fatalf("expected an EOF error, got %v", err)
		}
	})
}

func TestPromptTraceSelectionAsText_writesTheListAndPromptToOut(t *testing.T) {
	traces := []traceInfo{
		{Path: "1", Project: "admin", TestDir: "login"},
		{Path: "2", Project: "lite", TestDir: "chat"},
	}

	var out bytes.Buffer
	selected, err := promptTraceSelectionAsText(&out, strings.NewReader("2\n"), traces, []string{"admin", "lite"})
	if err != nil {
		t.Fatalf("promptTraceSelectionAsText: %v", err)
	}

	if len(selected) != 1 || selected[0].Path != "2" {
		t.Fatalf("expected trace 2, got %+v", selected)
	}
	want := "\nFound 2 trace(s) across 2 project(s):\n" +
		"\n  admin (1):\n    [ 1] login\n" +
		"\n  lite (1):\n    [ 2] chat\n" +
		"\nOpen which traces? (e.g. 1,3,5 | 1-5 | all | admin | lite): "
	if out.String() != want {
		t.Fatalf("expected %q, got %q", want, out.String())
	}
}

func TestResolveRunID(t *testing.T) {
	runs := `[{"databaseId":555,"status":"completed","conclusion":"failure","headBranch":"feat","url":"u"}]`
	cases := []struct {
		name    string
		args    []string
		opts    TraceOptions
		git     func(t *testing.T) string
		gh      string
		want    string
		wantErr string
		wantGH  [][]string
	}{
		{
			name: "explicit run URL",
			args: []string{"https://github.com/o/r/actions/runs/777"},
			opts: TraceOptions{PR: "1", Branch: "main"},
			want: "777",
		},
		{
			name: "PR number",
			opts: TraceOptions{PR: "9500", Branch: "ignored"},
			gh: `case "$1" in
  pr) printf 'feat\n' ;;
  run) printf '%s' '` + runs + `' ;;
esac
`,
			want: "555",
			wantGH: [][]string{
				{"pr", "view", "9500", "--json", "headRefName", "--jq", ".headRefName"},
				{"run", "list", "--workflow", "Run Playwright Tests", "--branch", "feat", "--limit", "1", "--json", "databaseId,status,conclusion,headBranch,url"},
			},
		},
		{
			name: "explicit branch",
			opts: TraceOptions{Branch: "release"},
			gh:   `printf '%s' '` + runs + `'`,
			want: "555",
			wantGH: [][]string{
				{"run", "list", "--workflow", "Run Playwright Tests", "--branch", "release", "--limit", "1", "--json", "databaseId,status,conclusion,headBranch,url"},
			},
		},
		{
			name: "current branch",
			git:  func(t *testing.T) string { return kubeGitScript(t, "/repo", "my-branch") },
			gh:   `printf '%s' '` + runs + `'`,
			want: "555",
			wantGH: [][]string{
				{"run", "list", "--workflow", "Run Playwright Tests", "--branch", "my-branch", "--limit", "1", "--json", "databaseId,status,conclusion,headBranch,url"},
			},
		},
		{
			name:    "detached HEAD",
			git:     func(t *testing.T) string { return kubeGitScript(t, "/repo", "") },
			wantErr: "detached HEAD; specify a --branch, --pr, or run ID",
		},
		{
			name:    "git fails",
			git:     func(*testing.T) string { return "exit 128\n" },
			wantErr: "failed to get current branch: git branch failed: exit status 128",
		},
		{
			name:    "PR without a branch",
			opts:    TraceOptions{PR: "9500"},
			gh:      "exit 0\n",
			wantErr: "could not determine branch for PR #9500",
		},
		{
			name:    "gh pr view fails",
			opts:    TraceOptions{PR: "9500"},
			gh:      "printf 'no pull requests found' >&2\nexit 1\n",
			wantErr: "gh pr view failed: exit status 1: no pull requests found",
		},
		{
			name:    "no runs for the branch",
			opts:    TraceOptions{Branch: "release"},
			gh:      "printf '[]'\n",
			wantErr: `no Playwright runs found for branch "release"`,
		},
		{
			name:    "unparseable run list",
			opts:    TraceOptions{Branch: "release"},
			gh:      "printf 'not json'\n",
			wantErr: "failed to parse run list: invalid character 'o' in literal null (expecting 'u')",
		},
		{
			name:    "gh run list fails",
			opts:    TraceOptions{Branch: "release"},
			gh:      "printf 'HTTP 401' >&2\nexit 4\n",
			wantErr: "gh run list failed: exit status 4: HTTP 401",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			scripts := map[string]string{"git": ""}
			if c.git != nil {
				scripts["git"] = c.git(t)
			}
			if c.gh != "" {
				scripts["gh"] = c.gh
			}
			calls := kubeFakeTools(t, scripts)

			got, err := resolveRunID(c.args, &c.opts)
			if c.wantErr != "" {
				if err == nil || err.Error() != c.wantErr {
					t.Fatalf("expected error %q, got %q, %v", c.wantErr, got, err)
				}
				return
			}
			if err != nil || got != c.want {
				t.Fatalf("expected %q, got %q, %v", c.want, got, err)
			}
			kubeAssertCalls(t, kubeCallsTo(calls(), "gh"), c.wantGH)
		})
	}
}

func TestFindLatestRunForBranch_failsWithoutGH(t *testing.T) {
	kubeFakeTools(t, map[string]string{})

	_, err := findLatestRunForBranch("main")
	if err == nil || !strings.HasPrefix(err.Error(), `gh run list failed: exec: "gh": executable file not found`) {
		t.Fatalf("expected a lookup failure, got %v", err)
	}
}

func TestDownloadTraceArtifacts(t *testing.T) {
	cases := []struct {
		name        string
		project     string
		wantDir     string
		wantPattern string
	}{
		{"all projects", "", "42", "playwright-test-results-*"},
		{"one project", "admin", "42-admin", "playwright-test-results-admin-*"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			tmp := t.TempDir()
			t.Setenv("TMPDIR", tmp)
			calls := kubeFakeTools(t, map[string]string{
				"gh": kubeGHDownloadScript("", "playwright-test-results-admin-42/test-a"),
			})

			dest, err := downloadTraceArtifacts("42", c.project)
			if err != nil {
				t.Fatalf("downloadTraceArtifacts: %v", err)
			}

			wantDest := filepath.Join(tmp, "ods-traces", c.wantDir)
			if dest != wantDest {
				t.Fatalf("expected %q, got %q", wantDest, dest)
			}
			kubeAssertCalls(t, kubeCallsTo(calls(), "gh"), [][]string{
				{"run", "download", "42", "--dir", wantDest, "--pattern", c.wantPattern},
			})
		})
	}
}

func TestDownloadTraceArtifacts_reusesACachedDownload(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("TMPDIR", tmp)
	calls := kubeFakeTools(t, map[string]string{"gh": "exit 1\n"})
	cached := filepath.Join(tmp, "ods-traces", "42")
	kubeTraceDir(t, cached, "artifact/test")

	dest, err := downloadTraceArtifacts("42", "")
	if err != nil {
		t.Fatalf("downloadTraceArtifacts: %v", err)
	}
	if dest != cached {
		t.Fatalf("expected %q, got %q", cached, dest)
	}
	if got := calls(); len(got) != 0 {
		t.Fatalf("expected no gh calls, got %q", got)
	}
}

func TestDownloadTraceArtifacts_replacesACacheWithoutTraces(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("TMPDIR", tmp)
	kubeFakeTools(t, map[string]string{"gh": kubeGHDownloadScript("", "artifact/fresh")})
	stale := filepath.Join(tmp, "ods-traces", "42", "stale.txt")
	if err := os.MkdirAll(filepath.Dir(stale), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(stale, nil, 0o644); err != nil {
		t.Fatal(err)
	}

	dest, err := downloadTraceArtifacts("42", "")
	if err != nil {
		t.Fatalf("downloadTraceArtifacts: %v", err)
	}
	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Fatalf("expected the stale file to be removed, got %v", err)
	}
	if _, err := os.Stat(filepath.Join(dest, "artifact/fresh/trace.zip")); err != nil {
		t.Fatalf("expected the fresh trace: %v", err)
	}
}

func TestDownloadTraceArtifacts_removesTheDirectoryWhenGHFails(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("TMPDIR", tmp)
	kubeFakeTools(t, map[string]string{"gh": "/bin/mkdir -p \"$5/partial\"\nexit 1\n"})

	_, err := downloadTraceArtifacts("42", "")
	if err == nil || !strings.HasPrefix(err.Error(), "gh run download failed: exit status 1\n") {
		t.Fatalf("expected the download error, got %v", err)
	}
	if _, err := os.Stat(filepath.Join(tmp, "ods-traces", "42")); !os.IsNotExist(err) {
		t.Fatalf("expected the download directory to be removed, got %v", err)
	}
}

func TestDownloadTraceArtifacts_failsWhenTheCacheCannotBeCreated(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("TMPDIR", tmp)
	calls := kubeFakeTools(t, map[string]string{"gh": "exit 0\n"})
	if err := os.WriteFile(filepath.Join(tmp, "ods-traces"), nil, 0o644); err != nil {
		t.Fatal(err)
	}

	_, err := downloadTraceArtifacts("42", "")
	if err == nil || !strings.HasPrefix(err.Error(), "failed to create directory "+filepath.Join(tmp, "ods-traces", "42")) {
		t.Fatalf("expected the mkdir error, got %v", err)
	}
	if got := calls(); len(got) != 0 {
		t.Fatalf("expected no gh calls, got %q", got)
	}
}

func TestTrace_listPrintsTracesAndTheDownloadDirectory(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("TMPDIR", tmp)
	calls := kubeFakeTools(t, map[string]string{
		"gh": kubeGHDownloadScript("",
			"playwright-test-results-lite-42/chat",
			"playwright-test-results-admin-42/login",
		),
		"bunx": "exit 0\n",
	})

	out := kubeExecute(t, NewTraceCommand(), "--list", "https://github.com/o/r/actions/runs/42")

	dest := filepath.Join(tmp, "ods-traces", "42")
	want := "\nFound 2 trace(s) across 2 project(s):\n" +
		"\n  admin (1):\n    [ 1] login\n" +
		"\n  lite (1):\n    [ 2] chat\n" +
		"\nTraces downloaded to: " + dest + "\n"
	if out != want {
		t.Fatalf("expected %q, got %q", want, out)
	}
	if got := kubeCallsTo(calls(), "bunx"); len(got) != 0 {
		t.Fatalf("expected no bunx calls, got %q", got)
	}
}

func TestTrace_opensASingleTraceFromTheWebDirectory(t *testing.T) {
	tmp := t.TempDir()
	t.Setenv("TMPDIR", tmp)
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "web"), 0o755); err != nil {
		t.Fatal(err)
	}
	pwdFile := filepath.Join(t.TempDir(), "pwd")
	t.Setenv("ODS_TEST_PWD_FILE", pwdFile)
	calls := kubeFakeTools(t, map[string]string{
		"git":  kubeGitScript(t, root, "feat"),
		"gh":   kubeGHDownloadScript(`[{"databaseId":42}]`, "playwright-test-results-admin-42/login"),
		"bunx": `printf '%s' "$PWD" > "$ODS_TEST_PWD_FILE"` + "\n",
	})

	out := kubeExecute(t, NewTraceCommand(), "--project", "admin")

	if out != "" {
		t.Fatalf("expected no output, got %q", out)
	}
	trace := filepath.Join(tmp, "ods-traces", "42-admin", "playwright-test-results-admin-42", "login", "trace.zip")
	kubeAssertCalls(t, kubeCallsTo(calls(), "bunx"), [][]string{{"playwright", "show-trace", trace}})
	pwd, err := os.ReadFile(pwdFile)
	if err != nil {
		t.Fatal(err)
	}
	if string(pwd) != filepath.Join(root, "web") {
		t.Fatalf("expected bunx to run in %q, got %q", filepath.Join(root, "web"), pwd)
	}
}

func TestRunTrace_stopsWhenTheRunHasNoTraces(t *testing.T) {
	t.Setenv("TMPDIR", t.TempDir())
	calls := kubeFakeTools(t, map[string]string{
		"gh":   kubeGHDownloadScript(""),
		"bunx": "exit 0\n",
	})

	var out bytes.Buffer
	runTrace(&out, strings.NewReader(""), []string{"42"}, &TraceOptions{})

	if out.Len() != 0 {
		t.Fatalf("expected no output, got %q", out.String())
	}
	if got := kubeCallsTo(calls(), "bunx"); len(got) != 0 {
		t.Fatalf("expected no bunx calls, got %q", got)
	}
}

func TestOpenTraces_logsOnlyWhenPlaywrightCannotStart(t *testing.T) {
	traces := []traceInfo{{Path: "/tmp/a/trace.zip"}, {Path: "/tmp/b/trace.zip"}}

	t.Run("a non-zero exit is not an error", func(t *testing.T) {
		calls := kubeFakeTools(t, map[string]string{"bunx": "exit 1\n"})
		hook := kubeCaptureLogs(t)

		openTraces(traces)

		kubeAssertCalls(t, kubeCallsTo(calls(), "bunx"), [][]string{
			{"playwright", "show-trace", "/tmp/a/trace.zip", "/tmp/b/trace.zip"},
		})
		for _, e := range hook.AllEntries() {
			if e.Level <= log.ErrorLevel {
				t.Fatalf("expected no error logs, got %q", e.Message)
			}
		}
	})

	t.Run("a missing bunx is logged", func(t *testing.T) {
		kubeFakeTools(t, map[string]string{})
		hook := kubeCaptureLogs(t)

		openTraces(traces)

		last := hook.LastEntry()
		if last == nil || last.Level != log.ErrorLevel || !strings.HasPrefix(last.Message, "playwright show-trace failed: exec: ") {
			t.Fatalf("expected the show-trace error log, got %+v", last)
		}
	})
}
