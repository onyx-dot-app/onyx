package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
)

// gateTypeMeasurement is a measurement with src/app at 50%.
const gateTypeMeasurement = `{"files":[{"file":"src/app/a.ts","correct":1,"total":2}]}`

// gateWebRepo creates a repository whose web/ has installed node_modules, and
// a bun on PATH that records its arguments in record. `bun run types:check`
// writes gateTypeMeasurement to its --output when measure is set, then exits
// with exitCode. It returns the web directory.
func gateWebRepo(t *testing.T, record string, measure bool, exitCode int) string {
	t.Helper()
	web := filepath.Join(gateRepo(t), "web")
	gateWriteFile(t, filepath.Join(web, "node_modules", "pkg", "index.js"), "")
	source := filepath.Join(t.TempDir(), "measurement.json")
	gateWriteFile(t, source, gateTypeMeasurement)
	write := ""
	if measure {
		write = fmt.Sprintf("cp %q \"$5\"\n", source)
	}
	gateFakeBin(t, "bun", fmt.Sprintf("echo \"$@\" > %q\n%sexit %d\n", record, write, exitCode))
	return web
}

func TestRunTypeCoverage_updateWritesTheBaselineAndKeepsTheOutput(t *testing.T) {
	record := filepath.Join(t.TempDir(), "bun-args")
	web := gateWebRepo(t, record, true, 0)
	output := filepath.Join(t.TempDir(), "out", "types.json")

	if code := runTypeCoverage("ts", &TypeCoverageOptions{Update: true, Output: output}); code != 0 {
		t.Fatalf("expected exit code 0, got %d", code)
	}

	if want := "run types:check -- --output " + output; strings.TrimSpace(gateReadFile(t, record)) != want {
		t.Fatalf("expected %q, got %q", want, gateReadFile(t, record))
	}
	if got := gateReadFile(t, output); got != gateTypeMeasurement {
		t.Fatalf("expected the kept measurement %q, got %q", gateTypeMeasurement, got)
	}
	baseline, err := coverage.LoadBaseline(coverage.TypeScript.BaselinePath(web))
	if err != nil {
		t.Fatal(err)
	}
	if baseline.Packages["src/app"] != 50 {
		t.Fatalf("expected a 50%% floor for src/app, got %v", baseline.Packages)
	}
}

func TestRunTypeCoverage_checksAgainstTheFloors(t *testing.T) {
	for name, tc := range map[string]struct {
		floor float64
		want  int
	}{
		"below the floor fails": {80, 1},
		"above the floor holds": {40, 0},
	} {
		t.Run(name, func(t *testing.T) {
			web := gateWebRepo(t, filepath.Join(t.TempDir(), "bun-args"), true, 0)
			floors := &coverage.Baseline{Total: tc.floor, Packages: map[string]float64{"src/app": tc.floor}}
			if err := floors.Save(coverage.TypeScript.BaselinePath(web), coverage.TypeScript); err != nil {
				t.Fatal(err)
			}
			markdown := filepath.Join(t.TempDir(), "types.md")
			tmp := gateTempDir(t)

			code := runTypeCoverage("typescript", &TypeCoverageOptions{
				Check: true, Markdown: markdown, Tolerance: coverage.TypeScript.DefaultTolerance,
			})
			if code != tc.want {
				t.Fatalf("expected exit code %d, got %d", tc.want, code)
			}
			if got := gateReadFile(t, markdown); !strings.Contains(got, "web") {
				t.Fatalf("expected the markdown to name web, got %q", got)
			}
			// The measurement went to a temporary directory that is gone.
			if entries, err := os.ReadDir(tmp); err != nil || len(entries) != 0 {
				t.Fatalf("expected no temporary files left, got %v (%v)", entries, err)
			}
		})
	}
}

func TestRunTypeCoverage_measurementFailures(t *testing.T) {
	for name, tc := range map[string]struct {
		measure  bool
		exitCode int
		want     int
	}{
		"type errors pass the exit code through": {false, 2, 2},
		"missing measurement exits one":          {false, 0, 1},
	} {
		t.Run(name, func(t *testing.T) {
			web := gateWebRepo(t, filepath.Join(t.TempDir(), "bun-args"), tc.measure, tc.exitCode)
			tmp := gateTempDir(t)

			if code := runTypeCoverage("ts", &TypeCoverageOptions{Update: true}); code != tc.want {
				t.Fatalf("expected exit code %d, got %d", tc.want, code)
			}
			if entries, err := os.ReadDir(tmp); err != nil || len(entries) != 0 {
				t.Fatalf("expected no temporary files left, got %v (%v)", entries, err)
			}
			if _, err := os.Stat(coverage.TypeScript.BaselinePath(web)); !os.IsNotExist(err) {
				t.Fatalf("expected no baseline from a failed measurement, got %v", err)
			}
		})
	}
}
