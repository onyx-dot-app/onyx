package cmd

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
)

func TestRunCoverageGate_missingBaseline(t *testing.T) {
	profile := &coverage.Profile{Packages: []coverage.PackageCoverage{
		{Package: "src/app", Covered: 1, Total: 2},
	}}
	for name, tc := range map[string]struct {
		kind  coverage.Kind
		check bool
		want  int
	}{
		"required baseline fails the check":  {coverage.TypeScript, true, 1},
		"required baseline without --check":  {coverage.TypeScript, false, 0},
		"optional baseline passes the check": {coverage.GoTests, true, 0},
	} {
		t.Run(name, func(t *testing.T) {
			got := runCoverageGate(coverageGate{
				Kind:         tc.kind,
				Profile:      profile,
				BaselinePath: filepath.Join(t.TempDir(), tc.kind.BaselineFile),
				Name:         "web",
				Command:      "ods type-coverage typescript",
				Check:        tc.check,
			})
			if got != tc.want {
				t.Fatalf("expected exit code %d, got %d", tc.want, got)
			}
		})
	}
}

// The gate holds the floors; ReportReference only changes what the report
// shows. A package below its floor fails the check even when it did not move
// against the base, and the report says so against the base.
func TestRunCoverageGate_reportsAgainstTheBaseAndGatesOnTheFloors(t *testing.T) {
	profile := &coverage.Profile{Packages: []coverage.PackageCoverage{
		{Package: "cmd", Covered: 1, Total: 4}, // 25%, below its 50 floor
	}}
	baselinePath := filepath.Join(t.TempDir(), coverage.GoTests.BaselineFile)
	floors := &coverage.Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}
	if err := floors.Save(baselinePath, coverage.GoTests); err != nil {
		t.Fatal(err)
	}
	base := &coverage.Reference{
		Kind: coverage.ReferenceBase, Label: "abc1234", Total: 25, Packages: map[string]float64{"cmd": 25},
	}
	markdown := filepath.Join(t.TempDir(), "report.md")

	code := runCoverageGate(coverageGate{
		Kind:            coverage.GoTests,
		Profile:         profile,
		BaselinePath:    baselinePath,
		Name:            "tools/ods",
		Command:         "ods coverage ods",
		Check:           true,
		Markdown:        markdown,
		ReportReference: base,
	})

	if code != 1 {
		t.Fatalf("expected the floor regression to fail the check, got exit code %d", code)
	}
	got, err := os.ReadFile(markdown)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(string(got), coverage.MarkerUnchanged) {
		t.Errorf("expected the report unchanged against the base:\n%s", got)
	}
	if !strings.Contains(string(got), "base `abc1234`") {
		t.Errorf("expected the report to name the base:\n%s", got)
	}
}

// A baseline or markdown path the gate cannot use fails the run, rather than
// silently turning the gate off.
func TestRunCoverageGate_unusableFilesExitOne(t *testing.T) {
	profile := &coverage.Profile{Packages: []coverage.PackageCoverage{{Package: "cmd", Covered: 1, Total: 2}}}
	dir := t.TempDir()
	blocker := filepath.Join(dir, "file")
	if err := os.WriteFile(blocker, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	malformed := filepath.Join(dir, "malformed.yaml")
	if err := os.WriteFile(malformed, []byte("total: -5\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	for name, g := range map[string]coverageGate{
		"malformed baseline":    {BaselinePath: malformed, Check: true},
		"markdown under a file": {BaselinePath: filepath.Join(dir, "none.yaml"), Markdown: filepath.Join(blocker, "report.md")},
		"baseline under a file": {BaselinePath: filepath.Join(blocker, "baseline.yaml"), Update: true},
	} {
		t.Run(name, func(t *testing.T) {
			g.Kind, g.Profile, g.Name, g.Command = coverage.GoTests, profile, "tools/ods", "ods coverage ods"
			if got := runCoverageGate(g); got != 1 {
				t.Fatalf("expected exit code 1, got %d", got)
			}
		})
	}
}
