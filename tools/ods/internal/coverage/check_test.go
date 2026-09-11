package coverage

import (
	"math"
	"testing"
)

func profileOf(percents map[string][2]int) *Profile {
	profile := &Profile{}
	for name, counts := range percents {
		profile.Packages = append(profile.Packages, PackageCoverage{
			Package: name,
			Covered: counts[0],
			Total:   counts[1],
		})
	}
	return profile
}

// floorReference makes the committed floors the comparison target, which is
// what a check against a baseline uses.
func floorReference(baseline *Baseline) *Reference {
	if baseline == nil {
		return nil
	}
	return baseline.Reference()
}

func statusOf(t *testing.T, report *Report, pkg string) Status {
	t.Helper()
	for _, result := range report.Packages {
		if result.Package == pkg {
			return result.Status
		}
	}
	t.Fatalf("package %q missing from the report", pkg)
	return ""
}

func TestCompare_regressionBelowFloor(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 4}}) // 25%
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}

	report := Compare(profile, floorReference(baseline), DefaultTolerance)

	if got := statusOf(t, report, "cmd"); got != StatusRegressed {
		t.Fatalf("expected a regression, got %q", got)
	}
	if got := len(report.Regressions()); got != 1 {
		t.Fatalf("expected one regression, got %d", got)
	}
}

func TestCompare_holdingAtTheFloorPasses(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}}) // 50%
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}

	report := Compare(profile, floorReference(baseline), DefaultTolerance)

	if got := statusOf(t, report, "cmd"); got != StatusOK {
		t.Fatalf("expected ok, got %q", got)
	}
	if got := len(report.Regressions()); got != 0 {
		t.Fatalf("expected no regressions, got %d", got)
	}
}

// A drop inside the tolerance is noise, not a regression, so it must not fail
// the gate.
func TestCompare_dropInsideToleranceIsNotARegression(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {999, 1000}}) // 99.9%
	baseline := &Baseline{Total: 99.9, Packages: map[string]float64{"cmd": 100}}

	report := Compare(profile, floorReference(baseline), DefaultTolerance)

	if got := statusOf(t, report, "cmd"); got != StatusOK {
		t.Fatalf("expected the 0.1 drop tolerated, got %q", got)
	}
}

func TestCompare_improvementIsReported(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {3, 4}}) // 75%
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}

	report := Compare(profile, floorReference(baseline), DefaultTolerance)

	if got := statusOf(t, report, "cmd"); got != StatusImproved {
		t.Fatalf("expected an improvement, got %q", got)
	}
	if got := len(report.Improvements()); got != 1 {
		t.Fatalf("expected one improvement, got %d", got)
	}
	if got := len(report.Regressions()); got != 0 {
		t.Fatalf("an improvement must not fail the check, got %d regressions", got)
	}
}

// A fresh baseline rounds each floor down. With no tolerance, that rounding
// must not show as an improvement.
func TestCompare_roundingIsNotAnImprovement(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1985, 2000}}) // 99.25%
	baseline := &Baseline{Total: 99.2, Packages: map[string]float64{"cmd": 99.2}}

	report := Compare(profile, floorReference(baseline), 0)

	if got := statusOf(t, report, "cmd"); got != StatusOK {
		t.Fatalf("expected the rounding ignored, got %q", got)
	}
	if report.Changed() {
		t.Fatal("expected no change against a fresh baseline")
	}
}

// A package added without tests has no floor. It is reported so it gets a floor,
// but it cannot fail a check it was never measured for.
func TestCompare_newPackageDoesNotFail(t *testing.T) {
	profile := profileOf(map[string][2]int{"internal/new": {0, 10}})
	baseline := &Baseline{Total: 0, Packages: map[string]float64{}}

	report := Compare(profile, floorReference(baseline), DefaultTolerance)

	if got := statusOf(t, report, "internal/new"); got != StatusNew {
		t.Fatalf("expected new, got %q", got)
	}
	if got := len(report.Regressions()); got != 0 {
		t.Fatalf("expected no regressions, got %d", got)
	}
}

// A new package with no tests lowers the module total. The total is reported
// but not gated, so that cannot fail a check the package was never measured for.
func TestCompare_newPackageLoweringTotalDoesNotFail(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}, "internal/new": {0, 10}})
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}

	report := Compare(profile, floorReference(baseline), DefaultTolerance)

	if report.Total.Status != StatusRegressed {
		t.Fatalf("expected the total reported as regressed, got %q", report.Total.Status)
	}
	if got := len(report.Regressions()); got != 0 {
		t.Fatalf("expected no regressions, got %d", got)
	}
}

func TestReport_Changed(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}, "internal/new": {1, 2}})
	cases := map[string]struct {
		baseline *Baseline
		want     bool
	}{
		"holding":     {&Baseline{Total: 50, Packages: map[string]float64{"cmd": 50, "internal/new": 50}}, false},
		"improved":    {&Baseline{Total: 50, Packages: map[string]float64{"cmd": 10, "internal/new": 50}}, true},
		"new package": {&Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}, true},
		"no baseline": {nil, false},
	}
	for name, tc := range cases {
		if got := Compare(profile, floorReference(tc.baseline), DefaultTolerance).Changed(); got != tc.want {
			t.Errorf("%s: Changed() = %v, want %v", name, got, tc.want)
		}
	}
}

func TestValidateTolerance(t *testing.T) {
	for _, valid := range []float64{0, 0.1, 5} {
		if err := ValidateTolerance(valid); err != nil {
			t.Fatalf("expected %v accepted: %v", valid, err)
		}
	}
	for _, invalid := range []float64{-0.1, math.NaN(), math.Inf(1)} {
		if err := ValidateTolerance(invalid); err == nil {
			t.Fatalf("expected %v rejected", invalid)
		}
	}
}

func TestCompare_removedPackageIsReportedNotFailed(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}})
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50, "internal/gone": 90}}

	report := Compare(profile, floorReference(baseline), DefaultTolerance)

	if got := statusOf(t, report, "internal/gone"); got != StatusRemoved {
		t.Fatalf("expected removed, got %q", got)
	}
	if got := len(report.Regressions()); got != 0 {
		t.Fatalf("a deleted package must not fail the check, got %d", got)
	}
}

func TestCompare_noBaselineMarksEverythingNew(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}})

	report := Compare(profile, nil, DefaultTolerance)

	if got := statusOf(t, report, "cmd"); got != StatusNew {
		t.Fatalf("expected new, got %q", got)
	}
	if report.Total.Status != StatusNew {
		t.Fatalf("expected the total new, got %q", report.Total.Status)
	}
	if got := len(report.Regressions()); got != 0 {
		t.Fatalf("expected no regressions, got %d", got)
	}
}

// baseReference makes the exact coverage of a base commit the comparison
// target, which is what a report against `--base` uses.
func baseReference(counts map[string][2]int) *Reference {
	return NewSnapshot(profileOf(counts), testCommit, "tools/ods").Reference()
}

func TestCompare_stampsTheReference(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}})

	floor := Compare(profile, floorReference(&Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}), DefaultTolerance)
	if floor.Reference == nil || floor.Reference.Kind != ReferenceFloor {
		t.Fatalf("expected a floor reference, got %+v", floor.Reference)
	}

	base := Compare(profile, baseReference(map[string][2]int{"cmd": {1, 2}}), DefaultTolerance)
	if base.Reference == nil || base.Reference.Kind != ReferenceBase || base.Reference.Label != "abc1234" {
		t.Fatalf("expected a base reference, got %+v", base.Reference)
	}

	if Compare(profile, nil, DefaultTolerance).Reference != nil {
		t.Fatalf("expected no reference when there is nothing to compare against")
	}
}

// The tolerance applies the same way to a base comparison, so a tiny move is
// still noise rather than a regression.
func TestCompare_smallDropAgainstABaseIsTolerated(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1999, 2000}}) // 99.95%
	reference := baseReference(map[string][2]int{"cmd": {2000, 2000}})

	report := Compare(profile, reference, DefaultTolerance)

	if got := statusOf(t, report, "cmd"); got != StatusOK {
		t.Fatalf("expected the 0.05 drop tolerated, got %q", got)
	}
}
