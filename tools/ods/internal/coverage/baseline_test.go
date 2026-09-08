package coverage

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestNewBaseline_roundsFloorsDown(t *testing.T) {
	// 2/3 is 66.66...%, which must not become a 66.7% floor the same run
	// would then fail against.
	baseline := NewBaseline(profileOf(map[string][2]int{"cmd": {2, 3}}))

	if got := baseline.Packages["cmd"]; got != 66.6 {
		t.Fatalf("expected a 66.6 floor, got %v", got)
	}
}

// The floor a run records must always pass a check of that same run.
func TestNewBaseline_isSelfConsistent(t *testing.T) {
	profile := profileOf(map[string][2]int{
		"cmd":            {2, 3},
		"internal/audit": {1, 7},
		"internal/empty": {0, 0},
	})

	report := Compare(profile, NewBaseline(profile), 0)

	if got := len(report.Regressions()); got != 0 {
		t.Fatalf("a fresh baseline must not fail its own run, got %d regressions", got)
	}
}

func TestBaseline_saveAndLoadRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), BaselineFile)
	original := NewBaseline(profileOf(map[string][2]int{"cmd": {1, 4}, "internal/audit": {1, 2}}))

	if err := original.Save(path); err != nil {
		t.Fatalf("failed to save the baseline: %v", err)
	}
	loaded, err := LoadBaseline(path)
	if err != nil {
		t.Fatalf("failed to load the baseline: %v", err)
	}

	if loaded.Total != original.Total {
		t.Fatalf("expected total %v, got %v", original.Total, loaded.Total)
	}
	if len(loaded.Packages) != len(original.Packages) {
		t.Fatalf("expected %d packages, got %d", len(original.Packages), len(loaded.Packages))
	}
	for name, floor := range original.Packages {
		if loaded.Packages[name] != floor {
			t.Fatalf("expected %s at %v, got %v", name, floor, loaded.Packages[name])
		}
	}
}

func TestBaseline_saveIsDeterministic(t *testing.T) {
	dir := t.TempDir()
	baseline := NewBaseline(profileOf(map[string][2]int{
		"cmd": {1, 4}, "internal/audit": {1, 2}, "internal/tui": {3, 4},
	}))

	first := filepath.Join(dir, "first.yaml")
	second := filepath.Join(dir, "second.yaml")
	if err := baseline.Save(first); err != nil {
		t.Fatalf("failed to save the baseline: %v", err)
	}
	if err := baseline.Save(second); err != nil {
		t.Fatalf("failed to save the baseline: %v", err)
	}

	// A baseline that reorders between runs would show up as a diff on every
	// update, so key order has to be stable.
	firstData := readFile(t, first)
	if firstData != readFile(t, second) {
		t.Fatal("expected two saves of the same baseline to be byte-identical")
	}
	if !strings.Contains(firstData, "# Minimum statement coverage") {
		t.Fatalf("expected the explanatory header, got:\n%s", firstData)
	}
}

func TestLoadBaseline_missingFileReportsNotExist(t *testing.T) {
	_, err := LoadBaseline(filepath.Join(t.TempDir(), BaselineFile))
	if !os.IsNotExist(err) {
		t.Fatalf("expected a not-exist error, got %v", err)
	}
}

func TestLoadBaseline_rejectsMalformedYAML(t *testing.T) {
	path := filepath.Join(t.TempDir(), BaselineFile)
	if err := os.WriteFile(path, []byte("total: [not a number\n"), 0644); err != nil {
		t.Fatalf("failed to write the fixture: %v", err)
	}

	if _, err := LoadBaseline(path); err == nil {
		t.Fatal("expected an error for malformed YAML")
	}
}

// A floor that is not a percentage passes every comparison, which would turn
// the gate off without anyone noticing.
func TestLoadBaseline_rejectsInvalidFloors(t *testing.T) {
	for _, contents := range []string{
		"total: .nan\npackages: {}\n",
		"total: -1\npackages: {}\n",
		"total: 0\npackages:\n  cmd: 101\n",
		"total: 0\npackages:\n  cmd: .inf\n",
	} {
		path := filepath.Join(t.TempDir(), BaselineFile)
		if err := os.WriteFile(path, []byte(contents), 0644); err != nil {
			t.Fatalf("failed to write the fixture: %v", err)
		}
		if _, err := LoadBaseline(path); err == nil {
			t.Fatalf("expected an error for:\n%s", contents)
		}
	}
}

func readFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("failed to read %s: %v", path, err)
	}
	return string(data)
}
