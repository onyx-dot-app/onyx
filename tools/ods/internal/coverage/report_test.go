package coverage

import (
	"strings"
	"testing"
)

func TestWriteReport_showsEachStatus(t *testing.T) {
	profile := profileOf(map[string][2]int{
		"cmd":            {1, 4}, // 25%, below its 50 floor
		"internal/audit": {3, 4}, // 75%, above its 50 floor
		"internal/new":   {1, 2}, // no floor
	})
	baseline := &Baseline{
		Total:    50,
		Packages: map[string]float64{"cmd": 50, "internal/audit": 50, "internal/gone": 90},
	}

	var out strings.Builder
	if err := WriteReport(&out, Compare(profile, baseline, DefaultTolerance)); err != nil {
		t.Fatalf("failed to write the report: %v", err)
	}
	report := out.String()

	for _, want := range []string{
		"PACKAGE", "COVERAGE", "FLOOR",
		"REGRESSED by 25.0", // cmd
		"+25.0",             // internal/audit
		"new",               // internal/new
		"removed",           // internal/gone
		"total",
	} {
		if !strings.Contains(report, want) {
			t.Fatalf("expected %q in the report:\n%s", want, report)
		}
	}
}

// The total is not gated, so a drop there reads as a delta, not a regression.
func TestWriteReport_totalDropIsNotLabelledARegression(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}, "internal/new": {0, 10}})
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}

	var out strings.Builder
	if err := WriteReport(&out, Compare(profile, baseline, DefaultTolerance)); err != nil {
		t.Fatalf("failed to write the report: %v", err)
	}

	if strings.Contains(out.String(), "REGRESSED") {
		t.Fatalf("expected no regression label:\n%s", out.String())
	}
	if !strings.Contains(out.String(), "-41.7") {
		t.Fatalf("expected the total's delta:\n%s", out.String())
	}
}

// A package with no floor must not show a 0.0% floor, which would read as a
// real threshold rather than an absent one.
func TestWriteReport_newPackageHasNoFloorValue(t *testing.T) {
	var out strings.Builder
	report := Compare(profileOf(map[string][2]int{"internal/new": {1, 3}}), nil, DefaultTolerance)
	if err := WriteReport(&out, report); err != nil {
		t.Fatalf("failed to write the report: %v", err)
	}

	// The only percentage on the row is the measured one; the floor is "-".
	if got := strings.Count(out.String(), "%"); got != 2 {
		t.Fatalf("expected one percentage per row, got %d:\n%s", got, out.String())
	}
	if !strings.Contains(out.String(), "33.3%") {
		t.Fatalf("expected the measured coverage:\n%s", out.String())
	}
}
