package coverage

import (
	"strings"
	"testing"
)

const modulePath = "example.com/m"

func TestParseProfile_aggregatesPerPackage(t *testing.T) {
	profile := mustParse(t, `mode: set
example.com/m/internal/audit/osv.go:1.1,2.2 3 1
example.com/m/internal/audit/report.go:1.1,2.2 1 0
example.com/m/cmd/root.go:1.1,2.2 4 1
`)

	if len(profile.Packages) != 2 {
		t.Fatalf("expected 2 packages, got %d", len(profile.Packages))
	}
	// Sorted by package path, so cmd comes first.
	if got := profile.Packages[0].Package; got != "cmd" {
		t.Fatalf("expected cmd first, got %q", got)
	}
	if got := profile.Packages[1].Package; got != "internal/audit" {
		t.Fatalf("expected internal/audit second, got %q", got)
	}

	audit := profile.Packages[1]
	if audit.Covered != 3 || audit.Total != 4 {
		t.Fatalf("expected 3/4 statements, got %d/%d", audit.Covered, audit.Total)
	}
	if got := audit.Percent(); got != 75 {
		t.Fatalf("expected 75%%, got %v", got)
	}
}

func TestParseProfile_totalSpansPackages(t *testing.T) {
	profile := mustParse(t, `mode: set
example.com/m/cmd/root.go:1.1,2.2 1 1
example.com/m/internal/audit/osv.go:1.1,2.2 3 0
`)

	if got := profile.Total(); got != 25 {
		t.Fatalf("expected 25%%, got %v", got)
	}
}

// A block can appear more than once when several test binaries cover the same
// package. Counting it twice would inflate the total, so blocks merge by span.
func TestParseProfile_mergesRepeatedBlocks(t *testing.T) {
	profile := mustParse(t, `mode: set
example.com/m/cmd/root.go:1.1,2.2 2 0
example.com/m/cmd/root.go:1.1,2.2 2 1
`)

	pkg := profile.Packages[0]
	if pkg.Total != 2 {
		t.Fatalf("expected the repeated block counted once, got %d statements", pkg.Total)
	}
	if pkg.Covered != 2 {
		t.Fatalf("expected the block covered by the second run, got %d", pkg.Covered)
	}
}

func TestParseProfile_moduleRootIsDot(t *testing.T) {
	profile := mustParse(t, `mode: set
example.com/m/main.go:1.1,2.2 1 1
`)

	if got := profile.Packages[0].Package; got != "." {
		t.Fatalf("expected the module root as %q, got %q", ".", got)
	}
}

func TestParseProfile_rejectsMalformedLine(t *testing.T) {
	_, err := ParseProfile(strings.NewReader("mode: set\nexample.com/m/cmd/root.go:1.1,2.2 2\n"), modulePath)
	if err == nil {
		t.Fatal("expected an error for a line with too few fields")
	}
	if !strings.Contains(err.Error(), "line 2") {
		t.Fatalf("expected the line number in the error, got %v", err)
	}
}

func TestParseProfile_emptyProfileIsFullyCovered(t *testing.T) {
	profile := mustParse(t, "mode: set\n")

	if len(profile.Packages) != 0 {
		t.Fatalf("expected no packages, got %d", len(profile.Packages))
	}
	// Matches `go tool cover`, which reports a package with no statements as
	// covered rather than as a 0% failure.
	if got := profile.Total(); got != 100 {
		t.Fatalf("expected 100%%, got %v", got)
	}
}

func TestPackageCoverage_percentOfNoStatements(t *testing.T) {
	if got := (PackageCoverage{}).Percent(); got != 100 {
		t.Fatalf("expected 100%%, got %v", got)
	}
}

func mustParse(t *testing.T, profile string) *Profile {
	t.Helper()
	parsed, err := ParseProfile(strings.NewReader(profile), modulePath)
	if err != nil {
		t.Fatalf("failed to parse the profile: %v", err)
	}
	return parsed
}
