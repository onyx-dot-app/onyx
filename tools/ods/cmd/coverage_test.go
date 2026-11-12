package cmd

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestLoadProfile(t *testing.T) {
	moduleDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(moduleDir, "go.mod"), []byte("module example.com/m\n"), 0644); err != nil {
		t.Fatal(err)
	}
	profilePath := filepath.Join(t.TempDir(), "coverage.out")
	profileText := "mode: set\nexample.com/m/pkg/a.go:1.1,2.2 1 1\nexample.com/m/pkg/a.go:3.1,4.2 1 0\n"
	if err := os.WriteFile(profilePath, []byte(profileText), 0644); err != nil {
		t.Fatal(err)
	}

	profile, gotPath, code := loadProfile(moduleDir, profilePath)
	if code != 0 {
		t.Fatalf("loadProfile exited %d", code)
	}
	if gotPath != profilePath {
		t.Errorf("path = %q, want %q", gotPath, profilePath)
	}
	want := coverage.PackageCoverage{Package: "pkg", Covered: 1, Total: 2}
	if len(profile.Packages) != 1 || profile.Packages[0] != want {
		t.Errorf("packages = %+v, want [%+v]", profile.Packages, want)
	}

	if _, _, code := loadProfile(moduleDir, filepath.Join(moduleDir, "missing.out")); code != 1 {
		t.Errorf("a missing profile exited %d, want 1", code)
	}
	if _, _, code := loadProfile(t.TempDir(), profilePath); code != 1 {
		t.Errorf("a directory without go.mod exited %d, want 1", code)
	}
}

// gateFakeGo puts a go on PATH that records its directory and arguments in
// record, one per line. `go test` writes gateProfile to its -coverprofile and
// `go tool cover` writes its -o file; both then exit with exitCode.
func gateFakeGo(t *testing.T, record string, exitCode int) {
	t.Helper()
	source := filepath.Join(t.TempDir(), "profile")
	gateWriteFile(t, source, gateProfile)
	gateFakeBin(t, "go", fmt.Sprintf(`pwd > %[1]q
for a in "$@"; do
  echo "$a" >> %[1]q
  case "$a" in -coverprofile=*) cp %[2]q "${a#-coverprofile=}";; esac
done
if [ "$1" = tool ]; then echo html > "$5"; fi
exit %[3]d
`, record, source, exitCode))
}

// gateSaveFloors writes a baseline holding pkg at floor into the module.
func gateSaveFloors(t *testing.T, root string, floor float64) {
	t.Helper()
	baseline := &coverage.Baseline{Total: floor, Packages: map[string]float64{"pkg": floor}}
	if err := baseline.Save(gateBaselinePath(root), coverage.GoTests); err != nil {
		t.Fatal(err)
	}
}

func gateBaselinePath(root string) string {
	return coverage.GoTests.BaselinePath(filepath.Join(root, "tools", "ods"))
}

// gateSameDir compares directories after resolving symlinks, since a
// temporary directory can sit behind one.
func gateSameDir(a, b string) bool {
	ra, errA := filepath.EvalSymlinks(a)
	rb, errB := filepath.EvalSymlinks(b)
	return errA == nil && errB == nil && ra == rb
}

func TestRunCoverage_measuresWithGoTestAndRemovesTheTemporaryProfile(t *testing.T) {
	root := gateRepo(t)
	record := filepath.Join(t.TempDir(), "go-args")
	gateFakeGo(t, record, 0)
	tmp := gateTempDir(t)

	if code := runCoverage("ods", &CoverageOptions{Update: true, Tolerance: coverage.DefaultTolerance}); code != 0 {
		t.Fatalf("expected exit code 0, got %d", code)
	}

	lines := gateLines(t, record)
	if want := filepath.Join(root, "tools", "ods"); !gateSameDir(lines[0], want) {
		t.Fatalf("expected go test to run in %q, got %q", want, lines[0])
	}
	args := lines[1:]
	if len(args) != 4 || args[0] != "test" || args[1] != "-race" || args[3] != "./..." {
		t.Fatalf("expected [test -race -coverprofile=... ./...], got %q", args)
	}
	profilePath := strings.TrimPrefix(args[2], "-coverprofile=")
	if !filepath.IsAbs(profilePath) || !strings.HasPrefix(profilePath, tmp) {
		t.Fatalf("expected an absolute temporary profile under %q, got %q", tmp, args[2])
	}
	if _, err := os.Stat(filepath.Dir(profilePath)); !os.IsNotExist(err) {
		t.Fatalf("expected the temporary profile directory to be removed, got %v", err)
	}
	baseline, err := coverage.LoadBaseline(gateBaselinePath(root))
	if err != nil {
		t.Fatal(err)
	}
	if baseline.Packages["pkg"] != 50 {
		t.Fatalf("expected a 50%% floor for pkg, got %v", baseline.Packages)
	}
}

func TestRunCoverage_keepsTheProfileAndRendersHTML(t *testing.T) {
	gateRepo(t)
	record := filepath.Join(t.TempDir(), "go-args")
	gateFakeGo(t, record, 0)
	out := t.TempDir()
	profilePath := filepath.Join(out, "cover.out")
	htmlPath := filepath.Join(out, "html", "cover.html")

	if code := runCoverage("tools/ods", &CoverageOptions{Profile: profilePath, HTML: htmlPath}); code != 0 {
		t.Fatalf("expected exit code 0, got %d", code)
	}

	if got := gateReadFile(t, profilePath); got != gateProfile {
		t.Fatalf("expected the kept profile %q, got %q", gateProfile, got)
	}
	// The recorder keeps only the last call, which renders the html.
	args := gateLines(t, record)[1:]
	want := []string{"tool", "cover", "-html=" + profilePath, "-o", htmlPath}
	if !slices.Equal(args, want) {
		t.Fatalf("expected %q, got %q", want, args)
	}
	if _, err := os.Stat(htmlPath); err != nil {
		t.Fatalf("expected the html report: %v", err)
	}
}

func TestRunCoverage_htmlFailureExitsOne(t *testing.T) {
	gateRepo(t)
	profilePath := filepath.Join(t.TempDir(), "cover.out")
	gateWriteFile(t, profilePath, gateProfile)
	gateFakeGo(t, filepath.Join(t.TempDir(), "go-args"), 2)

	code := runCoverage("ods", &CoverageOptions{FromProfile: profilePath, HTML: filepath.Join(t.TempDir(), "c.html")})
	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
}

func TestRunCoverage_failedTestsPassTheirExitCodeThrough(t *testing.T) {
	root := gateRepo(t)
	gateFakeGo(t, filepath.Join(t.TempDir(), "go-args"), 3)

	if code := runCoverage("ods", &CoverageOptions{Update: true}); code != 3 {
		t.Fatalf("expected exit code 3, got %d", code)
	}
	if _, err := os.Stat(gateBaselinePath(root)); !os.IsNotExist(err) {
		t.Fatalf("expected no baseline from a failed run, got %v", err)
	}
}

func TestRunCoverage_measureErrorExitsOne(t *testing.T) {
	root := gateRepo(t)
	record := filepath.Join(t.TempDir(), "go-args")
	gateFakeGo(t, record, 0)
	if err := os.Remove(filepath.Join(root, "tools", "ods", "go.mod")); err != nil {
		t.Fatal(err)
	}

	if code := runCoverage("ods", &CoverageOptions{}); code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
	if _, err := os.Stat(record); !os.IsNotExist(err) {
		t.Fatalf("expected go not to run without a go.mod, got %v", err)
	}
}

func TestRunCoverage_gatesAProfileAgainstTheFloors(t *testing.T) {
	for name, tc := range map[string]struct {
		floor float64
		want  int
	}{
		"below the floor fails": {80, 1},
		"above the floor holds": {40, 0},
	} {
		t.Run(name, func(t *testing.T) {
			root := gateRepo(t)
			gateSaveFloors(t, root, tc.floor)
			profilePath := filepath.Join(t.TempDir(), "cover.out")
			gateWriteFile(t, profilePath, gateProfile)
			markdown := filepath.Join(t.TempDir(), "report.md")

			code := runCoverage("ods", &CoverageOptions{
				FromProfile: profilePath, Check: true, Markdown: markdown, Tolerance: coverage.DefaultTolerance,
			})
			if code != tc.want {
				t.Fatalf("expected exit code %d, got %d", tc.want, code)
			}
			if got := gateReadFile(t, markdown); !strings.Contains(got, "tools/ods") {
				t.Fatalf("expected the markdown to name tools/ods, got %q", got)
			}
		})
	}
}

// A base that cannot be resolved or fetched only warns: the report falls back
// to the floors. The repository has no remote, so nothing leaves the machine.
func TestRunCoverage_unavailableBaseFallsBackToTheFloors(t *testing.T) {
	root := gateRepo(t)
	gateSaveFloors(t, root, 50)
	profilePath := filepath.Join(t.TempDir(), "cover.out")
	gateWriteFile(t, profilePath, gateProfile)
	markdown := filepath.Join(t.TempDir(), "report.md")

	code := runCoverage("ods", &CoverageOptions{
		FromProfile: profilePath, Base: "no-such-rev", Check: true, Markdown: markdown,
	})
	if code != 0 {
		t.Fatalf("expected exit code 0, got %d", code)
	}
	got := gateReadFile(t, markdown)
	if !strings.Contains(got, "the baseline") || strings.Contains(got, "base `") {
		t.Fatalf("expected a report against the floors, got %q", got)
	}
}

// A base snapshot that exists but does not parse means the bucket is wrong, so
// the run fails instead of reporting against the floors.
func TestRunCoverage_unreadableBaseExitsOne(t *testing.T) {
	root := gateRepo(t)
	gateSaveFloors(t, root, 50)
	realStore := newSnapshotStore
	newSnapshotStore = func(bucket, module string) *coverage.S3SnapshotStore {
		store := realStore(bucket, module)
		store.FetchObject = func(_, destPath string) error {
			return os.WriteFile(destPath, []byte("commit: [\n"), 0o644)
		}
		return store
	}
	t.Cleanup(func() { newSnapshotStore = realStore })
	profilePath := filepath.Join(t.TempDir(), "cover.out")
	gateWriteFile(t, profilePath, gateProfile)
	markdown := filepath.Join(t.TempDir(), "report.md")

	code := runCoverage("ods", &CoverageOptions{
		FromProfile: profilePath, Base: "HEAD", Check: true, Markdown: markdown, SnapshotBucket: "test-bucket",
	})
	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
	if _, err := os.Stat(markdown); !os.IsNotExist(err) {
		t.Fatalf("expected no report, got %v", err)
	}
}

func TestRunCoverage_publish(t *testing.T) {
	for name, tc := range map[string]struct {
		dirty    bool
		floor    float64
		awsExit  int
		want     int
		uploaded bool
	}{
		"clean tree publishes":    {want: 0, uploaded: true},
		"dirty tree refuses":      {dirty: true, want: 1},
		"failed gate skips":       {floor: 80, want: 1},
		"failed upload exits one": {awsExit: 5, want: 1, uploaded: true},
	} {
		t.Run(name, func(t *testing.T) {
			root := gateRepo(t)
			if tc.floor > 0 {
				gateSaveFloors(t, root, tc.floor)
				gittest.Git(t, root, "add", ".")
				gittest.Git(t, root, "commit", "-q", "-m", "floors")
			}
			if tc.dirty {
				gateWriteFile(t, filepath.Join(root, "stray.txt"), "x")
			}
			out := t.TempDir()
			record, uploaded := filepath.Join(out, "aws-args"), filepath.Join(out, "snapshot.yaml")
			t.Setenv("ODS_TEST_AWS_ARGS", record)
			t.Setenv("ODS_TEST_UPLOADED", uploaded)
			gateFakeBin(t, "aws", fmt.Sprintf("printf '%%s\\0' \"$@\" > \"$ODS_TEST_AWS_ARGS\"\ncp \"$3\" \"$ODS_TEST_UPLOADED\"\nexit %d\n", tc.awsExit))
			profilePath := filepath.Join(out, "cover.out")
			gateWriteFile(t, profilePath, gateProfile)

			code := runCoverage("ods", &CoverageOptions{
				FromProfile: profilePath, Publish: true, Check: true, SnapshotBucket: "test-bucket",
			})
			if code != tc.want {
				t.Fatalf("expected exit code %d, got %d", tc.want, code)
			}
			if !tc.uploaded {
				if _, err := os.Stat(record); !os.IsNotExist(err) {
					t.Fatalf("expected aws not to run, got %v", err)
				}
				return
			}

			head := gittest.Git(t, root, "rev-parse", "HEAD")
			args := strings.Split(strings.TrimSuffix(gateReadFile(t, record), "\x00"), "\x00")
			wantURL := "s3://test-bucket/" + coverage.SnapshotObjectKey("tools/ods", head)
			if len(args) != 4 || args[0] != "s3" || args[1] != "cp" || args[3] != wantURL {
				t.Fatalf("expected s3 cp <file> %q, got %q", wantURL, args)
			}
			snapshot, err := coverage.LoadSnapshotFile(uploaded)
			if err != nil {
				t.Fatal(err)
			}
			if snapshot.Commit != head || snapshot.Module != "tools/ods" || snapshot.Packages["pkg"].Covered != 1 {
				t.Fatalf("expected the snapshot of %s for tools/ods, got %+v", head, snapshot)
			}
		})
	}
}

// A repository without commits has no HEAD to key a snapshot by.
func TestRunCoverage_publishWithoutACommitExitsOne(t *testing.T) {
	root := t.TempDir()
	gittest.Git(t, root, "init", "-q")
	// Exclude everything, so the tree is clean but HEAD is unborn.
	gateWriteFile(t, filepath.Join(root, ".git", "info", "exclude"), "*\n")
	gateWriteFile(t, filepath.Join(root, "tools", "ods", "go.mod"), "module example.com/m\n")
	t.Chdir(root)
	record := filepath.Join(t.TempDir(), "aws-args")
	t.Setenv("ODS_TEST_AWS_ARGS", record)
	gateFakeBin(t, "aws", "echo \"$@\" > \"$ODS_TEST_AWS_ARGS\"\n")
	profilePath := filepath.Join(t.TempDir(), "cover.out")
	gateWriteFile(t, profilePath, gateProfile)

	if code := runCoverage("ods", &CoverageOptions{FromProfile: profilePath, Publish: true}); code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
	if _, err := os.Stat(record); !os.IsNotExist(err) {
		t.Fatalf("expected aws not to run, got %v", err)
	}
}

func TestCoverageOptionConflict(t *testing.T) {
	for name, tc := range map[string]struct {
		opts CoverageOptions
		want string
	}{
		"check and update":           {CoverageOptions{Check: true, Update: true}, "--check and --update"},
		"base and update":            {CoverageOptions{Base: "main", Update: true}, "--base reports"},
		"publish and update":         {CoverageOptions{Publish: true, Update: true}, "--publish records"},
		"from-profile and profile":   {CoverageOptions{FromProfile: "a", Profile: "b"}, "--from-profile reads"},
		"check, base and publish ok": {CoverageOptions{Check: true, Base: "main", Publish: true}, ""},
	} {
		t.Run(name, func(t *testing.T) {
			err := coverageOptionConflict(&tc.opts)
			if tc.want == "" {
				if err != nil {
					t.Fatalf("expected no conflict, got %v", err)
				}
				return
			}
			if err == nil || !strings.HasPrefix(err.Error(), tc.want) {
				t.Fatalf("expected %q, got %v", tc.want, err)
			}
		})
	}
}

// gateStore is a SnapshotStore holding the snapshots of a few commits.
type gateStore struct {
	snapshots map[string]*coverage.Snapshot
	err       error
}

func (s gateStore) Fetch(commit string) (*coverage.Snapshot, error) {
	if s.err != nil {
		return nil, s.err
	}
	if snapshot, ok := s.snapshots[commit]; ok {
		return snapshot, nil
	}
	return nil, coverage.ErrSnapshotUnavailable
}

func (gateStore) Publish(*coverage.Snapshot) error { return nil }

func TestLocateBaseReference(t *testing.T) {
	root := gateRepo(t)
	parent := gittest.Git(t, root, "rev-parse", "HEAD")
	gittest.Commit(t, root, "second.txt")
	profile := &coverage.Profile{Packages: []coverage.PackageCoverage{{Package: "pkg", Covered: 3, Total: 4}}}

	t.Run("nearest recorded ancestor", func(t *testing.T) {
		store := gateStore{snapshots: map[string]*coverage.Snapshot{
			parent: coverage.NewSnapshot(profile, parent, "tools/ods"),
		}}
		reference, code := locateBaseReference("HEAD", store)
		if code != 0 || reference == nil {
			t.Fatalf("expected a reference, got %v with exit code %d", reference, code)
		}
		if reference.Label != coverage.ShortCommit(parent) || reference.Packages["pkg"] != 75 {
			t.Fatalf("expected pkg at 75%% from %s, got %+v", coverage.ShortCommit(parent), reference)
		}
	})

	t.Run("no snapshot keeps the floors", func(t *testing.T) {
		reference, code := locateBaseReference("HEAD", gateStore{})
		if code != 0 || reference != nil {
			t.Fatalf("expected no reference and exit code 0, got %v and %d", reference, code)
		}
	})

	t.Run("store error exits one", func(t *testing.T) {
		reference, code := locateBaseReference("HEAD", gateStore{err: errors.New("access denied")})
		if code != 1 || reference != nil {
			t.Fatalf("expected no reference and exit code 1, got %v and %d", reference, code)
		}
	})
}
