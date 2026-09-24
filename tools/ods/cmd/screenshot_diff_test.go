package cmd

import (
	"bytes"
	"encoding/json"
	"image/color"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/imgdiff"
)

var (
	shotWhite = color.RGBA{R: 255, G: 255, B: 255, A: 255}
	shotRed   = color.RGBA{R: 255, A: 255}
)

func TestResolveCompareDefaults(t *testing.T) {
	tests := []struct {
		name   string
		bucket string
		opts   ScreenshotDiffCompareOptions
		want   ScreenshotDiffCompareOptions
	}{
		{
			name: "project against main",
			opts: ScreenshotDiffCompareOptions{Project: "admin"},
			want: ScreenshotDiffCompareOptions{
				Project:  "admin",
				Baseline: "s3://onyx-playwright-artifacts/baselines/admin/main/",
				Current:  "web/output/screenshots",
				Output:   filepath.Join("web/output/screenshot-diff", "admin", "index.html"),
			},
		},
		{
			name:   "project against a release branch in another bucket",
			bucket: "my-bucket",
			opts:   ScreenshotDiffCompareOptions{Project: "admin", Rev: "release/2.5"},
			want: ScreenshotDiffCompareOptions{
				Project:  "admin",
				Rev:      "release/2.5",
				Baseline: "s3://my-bucket/baselines/admin/release-2.5/",
				Current:  "web/output/screenshots",
				Output:   filepath.Join("web/output/screenshot-diff", "admin", "index.html"),
			},
		},
		{
			name: "cross-revision ignores rev",
			opts: ScreenshotDiffCompareOptions{Project: "chat", Rev: "main", FromRev: "v1.0.0", ToRev: "release/2.0"},
			want: ScreenshotDiffCompareOptions{
				Project:  "chat",
				Rev:      "main",
				FromRev:  "v1.0.0",
				ToRev:    "release/2.0",
				Baseline: "s3://onyx-playwright-artifacts/baselines/chat/v1.0.0/",
				Current:  "s3://onyx-playwright-artifacts/baselines/chat/release-2.0/",
				Output:   filepath.Join("web/output/screenshot-diff", "chat", "index.html"),
			},
		},
		{
			name: "explicit flags win over the project",
			opts: ScreenshotDiffCompareOptions{Project: "admin", FromRev: "a", ToRev: "b", Baseline: "base", Current: "cur", Output: "out.html"},
			want: ScreenshotDiffCompareOptions{Project: "admin", FromRev: "a", ToRev: "b", Baseline: "base", Current: "cur", Output: "out.html"},
		},
		{
			name: "explicit flags win in standard mode",
			opts: ScreenshotDiffCompareOptions{Project: "admin", Baseline: "base", Current: "cur"},
			want: ScreenshotDiffCompareOptions{
				Project:  "admin",
				Baseline: "base",
				Current:  "cur",
				Output:   filepath.Join("web/output/screenshot-diff", "admin", "index.html"),
			},
		},
		{
			name: "no project only defaults the output",
			opts: ScreenshotDiffCompareOptions{Baseline: "base"},
			want: ScreenshotDiffCompareOptions{Baseline: "base", Output: "screenshot-diff/index.html"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Setenv("PLAYWRIGHT_S3_BUCKET", tt.bucket)
			got := tt.opts

			resolveCompareDefaults(&got)

			if got != tt.want {
				t.Fatalf("expected %+v, got %+v", tt.want, got)
			}
		})
	}
}

func TestResolveUploadDefaults(t *testing.T) {
	tests := []struct {
		name   string
		bucket string
		opts   ScreenshotDiffUploadOptions
		want   ScreenshotDiffUploadOptions
	}{
		{
			name: "project on main",
			opts: ScreenshotDiffUploadOptions{Project: "admin"},
			want: ScreenshotDiffUploadOptions{Project: "admin", Dir: "web/output/screenshots", Dest: "s3://onyx-playwright-artifacts/baselines/admin/main/"},
		},
		{
			name:   "project on a release branch in another bucket",
			bucket: "my-bucket",
			opts:   ScreenshotDiffUploadOptions{Project: "admin", Rev: "release/2.5", Delete: true},
			want:   ScreenshotDiffUploadOptions{Project: "admin", Rev: "release/2.5", Delete: true, Dir: "web/output/screenshots", Dest: "s3://my-bucket/baselines/admin/release-2.5/"},
		},
		{
			name: "explicit flags win",
			opts: ScreenshotDiffUploadOptions{Project: "admin", Dir: "shots", Dest: "s3://b/k/"},
			want: ScreenshotDiffUploadOptions{Project: "admin", Dir: "shots", Dest: "s3://b/k/"},
		},
		{
			name: "no project leaves everything unset",
			opts: ScreenshotDiffUploadOptions{Rev: "main"},
			want: ScreenshotDiffUploadOptions{Rev: "main"},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Setenv("PLAYWRIGHT_S3_BUCKET", tt.bucket)
			got := tt.opts

			resolveUploadDefaults(&got)

			if got != tt.want {
				t.Fatalf("expected %+v, got %+v", tt.want, got)
			}
		})
	}
}

func shotReadSummary(t *testing.T, path string) imgdiff.Summary {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("failed to read the summary: %v", err)
	}
	var summary imgdiff.Summary
	if err := json.Unmarshal(data, &summary); err != nil {
		t.Fatalf("invalid summary JSON: %v", err)
	}
	return summary
}

func shotAssertMissing(t *testing.T, path string) {
	t.Helper()
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("expected %s not to exist, got %v", path, err)
	}
}

func TestRunCompare_rejectsIncompleteFlags(t *testing.T) {
	tests := []struct {
		name string
		opts ScreenshotDiffCompareOptions
		want string
	}{
		{"from-rev alone", ScreenshotDiffCompareOptions{Project: "admin", FromRev: "v1"}, "--from-rev and --to-rev must be used together"},
		{"to-rev alone", ScreenshotDiffCompareOptions{Project: "admin", ToRev: "v2"}, "--from-rev and --to-rev must be used together"},
		{"no baseline", ScreenshotDiffCompareOptions{Current: "cur"}, "--baseline is required (or use --project to set defaults)"},
		{"no current", ScreenshotDiffCompareOptions{Baseline: "base"}, "--current is required (or use --project to set defaults)"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			callLog := shotFakeAWS(t, "exit 0\n")
			opts := tt.opts

			err := runCompare(&opts, io.Discard)

			if err == nil || err.Error() != tt.want {
				t.Fatalf("expected %q, got %v", tt.want, err)
			}
			if calls := shotAWSCalls(t, callLog); calls != nil {
				t.Fatalf("expected no aws calls, got %q", calls)
			}
		})
	}
}

func TestRunCompare_writesSummaryAndReportForDifferences(t *testing.T) {
	dir := t.TempDir()
	baseline := filepath.Join(dir, "baseline")
	current := filepath.Join(dir, "current")
	shotWritePNG(t, filepath.Join(baseline, "page.png"), 4, 4, shotWhite)
	shotWritePNG(t, filepath.Join(current, "page.png"), 4, 4, shotRed)
	shotWritePNG(t, filepath.Join(baseline, "same.png"), 4, 4, shotWhite)
	shotWritePNG(t, filepath.Join(current, "same.png"), 4, 4, shotWhite)
	output := filepath.Join(dir, "out", "index.html")

	var out bytes.Buffer
	err := runCompare(&ScreenshotDiffCompareOptions{Baseline: baseline, Current: current, Output: output, Threshold: 0.2}, &out)
	if err != nil {
		t.Fatalf("runCompare failed: %v", err)
	}

	want := imgdiff.Summary{Project: "default", Changed: 1, Unchanged: 1, Total: 2, HasDifferences: true}
	if got := shotReadSummary(t, filepath.Join(dir, "out", "summary.json")); got != want {
		t.Fatalf("expected summary %+v, got %+v", want, got)
	}
	for _, line := range []string{"Changed:   1", "Unchanged: 1", "Total:     2"} {
		if !strings.Contains(out.String(), line) {
			t.Fatalf("expected the summary to show %q, got %q", line, out.String())
		}
	}
	report, err := os.ReadFile(output)
	if err != nil {
		t.Fatalf("expected a report: %v", err)
	}
	if !strings.Contains(string(report), "page.png") {
		t.Fatalf("expected the report to name page.png")
	}
}

func TestRunCompare_skipsTheReportWithoutDifferences(t *testing.T) {
	dir := t.TempDir()
	baseline := filepath.Join(dir, "baseline")
	current := filepath.Join(dir, "current")
	shotWritePNG(t, filepath.Join(baseline, "page.png"), 4, 4, shotWhite)
	shotWritePNG(t, filepath.Join(current, "page.png"), 4, 4, shotWhite)
	output := filepath.Join(dir, "out", "index.html")

	err := runCompare(&ScreenshotDiffCompareOptions{Project: "admin", Baseline: baseline, Current: current, Output: output, Threshold: 0.2}, io.Discard)
	if err != nil {
		t.Fatalf("runCompare failed: %v", err)
	}

	want := imgdiff.Summary{Project: "admin", Unchanged: 1, Total: 1}
	if got := shotReadSummary(t, filepath.Join(dir, "out", "summary.json")); got != want {
		t.Fatalf("expected summary %+v, got %+v", want, got)
	}
	shotAssertMissing(t, output)
}

// On a first run there is no baseline yet, so every screenshot is new.
func TestRunCompare_createsAMissingBaseline(t *testing.T) {
	dir := t.TempDir()
	baseline := filepath.Join(dir, "baseline")
	current := filepath.Join(dir, "current")
	shotWritePNG(t, filepath.Join(current, "page.png"), 4, 4, shotWhite)
	output := filepath.Join(dir, "index.html")

	if err := runCompare(&ScreenshotDiffCompareOptions{Baseline: baseline, Current: current, Output: output}, io.Discard); err != nil {
		t.Fatalf("runCompare failed: %v", err)
	}

	if info, err := os.Stat(baseline); err != nil || !info.IsDir() {
		t.Fatalf("expected the baseline directory to be created, got %v", err)
	}
	want := imgdiff.Summary{Project: "default", Added: 1, Total: 1, HasDifferences: true}
	if got := shotReadSummary(t, filepath.Join(dir, "summary.json")); got != want {
		t.Fatalf("expected summary %+v, got %+v", want, got)
	}
	if _, err := os.Stat(output); err != nil {
		t.Fatalf("expected a report: %v", err)
	}
}

// A project that captured nothing still gets a summary, resolved against the
// working directory, so CI can read it.
func TestRunCompare_writesAnEmptySummaryWithoutScreenshots(t *testing.T) {
	cwd := t.TempDir()
	t.Chdir(cwd)
	baseline := filepath.Join(t.TempDir(), "baseline")
	shotWritePNG(t, filepath.Join(baseline, "page.png"), 4, 4, shotWhite)

	err := runCompare(&ScreenshotDiffCompareOptions{Project: "admin", Baseline: baseline}, io.Discard)
	if err != nil {
		t.Fatalf("runCompare failed: %v", err)
	}

	outDir := filepath.Join(cwd, "web", "output", "screenshot-diff", "admin")
	if got, want := shotReadSummary(t, filepath.Join(outDir, "summary.json")), (imgdiff.Summary{Project: "admin"}); got != want {
		t.Fatalf("expected summary %+v, got %+v", want, got)
	}
	shotAssertMissing(t, filepath.Join(outDir, "index.html"))
}

func TestRunCompare_downloadsBothRevisionsAndCleansUp(t *testing.T) {
	fixtures := t.TempDir()
	shotWritePNG(t, filepath.Join(fixtures, "v1", "page.png"), 4, 4, shotWhite)
	shotWritePNG(t, filepath.Join(fixtures, "v2", "page.png"), 4, 4, shotRed)
	shotWritePNG(t, filepath.Join(fixtures, "v2", "new.png"), 4, 4, shotRed)
	t.Setenv("ODS_TEST_FIXTURES", fixtures)
	callLog := shotFakeAWS(t, `case "$3" in
  */v1/) cp "$ODS_TEST_FIXTURES"/v1/* "$4" ;;
  */v2/) cp "$ODS_TEST_FIXTURES"/v2/* "$4" ;;
  *) exit 7 ;;
esac
`)
	tmp := t.TempDir()
	t.Setenv("TMPDIR", tmp)
	t.Setenv("PLAYWRIGHT_S3_BUCKET", "shots")
	output := filepath.Join(t.TempDir(), "index.html")

	err := runCompare(&ScreenshotDiffCompareOptions{Project: "admin", FromRev: "v1", ToRev: "v2", Output: output, Threshold: 0.2}, io.Discard)
	if err != nil {
		t.Fatalf("runCompare failed: %v", err)
	}

	calls := shotAWSCalls(t, callLog)
	if len(calls) != 2 ||
		!strings.HasPrefix(calls[0], "s3 sync s3://shots/baselines/admin/v1/ "+filepath.Join(tmp, "screenshot-baseline-")) ||
		!strings.HasPrefix(calls[1], "s3 sync s3://shots/baselines/admin/v2/ "+filepath.Join(tmp, "screenshot-current-")) {
		t.Fatalf("expected a baseline then a current sync into temp dirs, got %q", calls)
	}
	want := imgdiff.Summary{Project: "admin", Changed: 1, Added: 1, Total: 2, HasDifferences: true}
	if got := shotReadSummary(t, filepath.Join(filepath.Dir(output), "summary.json")); got != want {
		t.Fatalf("expected summary %+v, got %+v", want, got)
	}
	if entries, _ := os.ReadDir(tmp); len(entries) != 0 {
		t.Fatalf("expected the downloads to be removed, found %d entries", len(entries))
	}
}

func TestRunCompare_reportsFailedDownloads(t *testing.T) {
	tests := []struct {
		name     string
		baseline string
		current  string
		want     string
	}{
		{
			name:     "baseline",
			baseline: "s3://shots/broken/",
			current:  "unused",
			want:     "Failed to download baselines: failed to download from S3 (s3://shots/broken/): aws s3 sync failed: exit status 1",
		},
		{
			name:     "current",
			baseline: "s3://shots/ok/",
			current:  "s3://shots/broken/",
			want:     "Failed to download current screenshots: failed to download from S3 (s3://shots/broken/): aws s3 sync failed: exit status 1",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			shotFakeAWS(t, "case \"$3\" in */broken/) exit 1 ;; esac\n")
			tmp := t.TempDir()
			t.Setenv("TMPDIR", tmp)

			err := runCompare(&ScreenshotDiffCompareOptions{Baseline: tt.baseline, Current: tt.current, Output: filepath.Join(t.TempDir(), "index.html")}, io.Discard)

			if err == nil || !strings.HasPrefix(err.Error(), tt.want) {
				t.Fatalf("expected %q, got %v", tt.want, err)
			}
			if entries, _ := os.ReadDir(tmp); len(entries) != 0 {
				t.Fatalf("expected every download to be removed, found %d entries", len(entries))
			}
		})
	}
}

func TestRunCompare_reportsFailures(t *testing.T) {
	dir := t.TempDir()
	good := filepath.Join(dir, "good")
	shotWritePNG(t, filepath.Join(good, "page.png"), 4, 4, shotWhite)
	changed := filepath.Join(dir, "changed")
	shotWritePNG(t, filepath.Join(changed, "page.png"), 4, 4, shotRed)
	corrupt := filepath.Join(dir, "corrupt")
	shotWriteFiles(t, corrupt, map[string]string{"page.png": "not a png"})
	file := filepath.Join(dir, "file")
	shotWriteFiles(t, dir, map[string]string{"file": ""})
	// A directory where the report file should go.
	reportDir := filepath.Join(dir, "blocked")
	if err := os.MkdirAll(filepath.Join(reportDir, "index.html"), 0o755); err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name string
		opts ScreenshotDiffCompareOptions
		want string
	}{
		{
			name: "undecodable screenshot",
			opts: ScreenshotDiffCompareOptions{Baseline: good, Current: corrupt, Output: filepath.Join(t.TempDir(), "index.html")},
			want: "Comparison failed: failed to compare page.png",
		},
		{
			name: "unwritable summary",
			opts: ScreenshotDiffCompareOptions{Baseline: good, Current: good, Output: filepath.Join(file, "index.html")},
			want: "Failed to write summary: failed to create directory for summary",
		},
		{
			name: "unwritable empty summary",
			opts: ScreenshotDiffCompareOptions{Baseline: good, Current: filepath.Join(dir, "missing"), Output: filepath.Join(file, "index.html")},
			want: "Failed to write summary: failed to create directory for summary",
		},
		{
			name: "unwritable report",
			opts: ScreenshotDiffCompareOptions{Baseline: good, Current: changed, Output: filepath.Join(reportDir, "index.html")},
			want: "Failed to generate report: failed to create output file",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			opts := tt.opts

			err := runCompare(&opts, io.Discard)

			if err == nil || !strings.HasPrefix(err.Error(), tt.want) {
				t.Fatalf("expected %q, got %v", tt.want, err)
			}
		})
	}
}

func TestRunUploadBaselines_syncsTheProjectBaseline(t *testing.T) {
	cwd := t.TempDir()
	t.Chdir(cwd)
	if err := os.MkdirAll(filepath.Join("web", "output", "screenshots"), 0o755); err != nil {
		t.Fatal(err)
	}
	callLog := shotFakeAWS(t, "exit 0\n")
	t.Setenv("PLAYWRIGHT_S3_BUCKET", "")

	err := runUploadBaselines(&ScreenshotDiffUploadOptions{Project: "admin", Rev: "release/2.5", Delete: true})
	if err != nil {
		t.Fatalf("runUploadBaselines failed: %v", err)
	}

	want := []string{"s3 sync web/output/screenshots s3://onyx-playwright-artifacts/baselines/admin/release-2.5/ --delete"}
	if got := shotAWSCalls(t, callLog); strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestRunUploadBaselines_reportsFailures(t *testing.T) {
	dir := t.TempDir()
	tests := []struct {
		name   string
		opts   ScreenshotDiffUploadOptions
		script string
		want   string
		synced bool
	}{
		{"no dir", ScreenshotDiffUploadOptions{Dest: "s3://b/k/"}, "exit 0\n", "--dir is required (or use --project to set defaults)", false},
		{"no dest", ScreenshotDiffUploadOptions{Dir: dir}, "exit 0\n", "--dest is required (or use --project to set defaults)", false},
		{"missing dir", ScreenshotDiffUploadOptions{Dir: filepath.Join(dir, "missing"), Dest: "s3://b/k/"}, "exit 0\n", "Screenshots directory does not exist: " + filepath.Join(dir, "missing"), false},
		{"local dest", ScreenshotDiffUploadOptions{Dir: dir, Dest: "/tmp/baselines"}, "exit 0\n", "Destination must be an S3 URL (s3://...): /tmp/baselines", false},
		{"failed sync", ScreenshotDiffUploadOptions{Dir: dir, Dest: "s3://b/k/"}, "exit 3\n", "Failed to upload baselines: aws s3 sync failed: exit status 3", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			callLog := shotFakeAWS(t, tt.script)
			opts := tt.opts

			err := runUploadBaselines(&opts)

			if err == nil || !strings.HasPrefix(err.Error(), tt.want) {
				t.Fatalf("expected %q, got %v", tt.want, err)
			}
			if synced := shotAWSCalls(t, callLog) != nil; synced != tt.synced {
				t.Fatalf("expected aws to run: %v, got %v", tt.synced, synced)
			}
		})
	}
}

func TestSummaryText(t *testing.T) {
	results := []imgdiff.Result{
		{Name: "big.png", Status: imgdiff.StatusChanged, DiffPercent: 12.345},
		{Name: "new.png", Status: imgdiff.StatusAdded},
		{Name: "gone.png", Status: imgdiff.StatusRemoved},
		{Name: "same.png", Status: imgdiff.StatusUnchanged},
		{Name: "same2.png", Status: imgdiff.StatusUnchanged},
	}

	want := `
╔══════════════════════════════════════════════╗
║          Visual Regression Summary           ║
╠══════════════════════════════════════════════╣
║  Changed:   1                                ║
║  Added:     1                                ║
║  Removed:   1                                ║
║  Unchanged: 2                                ║
║  Total:     5                                ║
╚══════════════════════════════════════════════╝

  ⚠ CHANGED  big.png (12.35% diff)
  ✚ ADDED    new.png
  ✖ REMOVED  gone.png

`
	if got := summaryText(results); got != want {
		t.Fatalf("expected:\n%s\ngot:\n%s", want, got)
	}
}

func TestSummaryText_listsNothingWithoutDifferences(t *testing.T) {
	got := summaryText([]imgdiff.Result{{Name: "same.png", Status: imgdiff.StatusUnchanged}})

	if strings.Contains(got, "same.png") {
		t.Fatalf("expected unchanged screenshots not to be listed, got:\n%s", got)
	}
	if !strings.HasSuffix(got, "║  Total:     1                                ║\n╚══════════════════════════════════════════════╝\n\n") {
		t.Fatalf("expected the output to end after the box, got:\n%s", got)
	}
}
