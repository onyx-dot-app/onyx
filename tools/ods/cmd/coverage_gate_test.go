package cmd

import (
	"path/filepath"
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
