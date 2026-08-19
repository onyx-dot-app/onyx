package coverage

import "testing"

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

	report := Compare(profile, baseline, DefaultTolerance)

	if got := statusOf(t, report, "cmd"); got != StatusRegressed {
		t.Fatalf("expected a regression, got %q", got)
	}
	if got := len(report.Regressions()); got != 2 {
		t.Fatalf("expected the package and the total to regress, got %d", got)
	}
}

func TestCompare_holdingAtTheFloorPasses(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}}) // 50%
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}

	report := Compare(profile, baseline, DefaultTolerance)

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

	report := Compare(profile, baseline, DefaultTolerance)

	if got := statusOf(t, report, "cmd"); got != StatusOK {
		t.Fatalf("expected the 0.1 drop tolerated, got %q", got)
	}
}

func TestCompare_improvementIsReported(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {3, 4}}) // 75%
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}}

	report := Compare(profile, baseline, DefaultTolerance)

	if got := statusOf(t, report, "cmd"); got != StatusImproved {
		t.Fatalf("expected an improvement, got %q", got)
	}
	if got := len(report.Improvements()); got != 2 {
		t.Fatalf("expected the package and the total to improve, got %d", got)
	}
	if got := len(report.Regressions()); got != 0 {
		t.Fatalf("an improvement must not fail the check, got %d regressions", got)
	}
}

// A package added without tests has no floor. It is reported so it gets a floor,
// but it cannot fail a check it was never measured for.
func TestCompare_newPackageDoesNotFail(t *testing.T) {
	profile := profileOf(map[string][2]int{"internal/new": {0, 10}})
	baseline := &Baseline{Total: 0, Packages: map[string]float64{}}

	report := Compare(profile, baseline, DefaultTolerance)

	if got := statusOf(t, report, "internal/new"); got != StatusNew {
		t.Fatalf("expected new, got %q", got)
	}
	if got := len(report.Regressions()); got != 0 {
		t.Fatalf("expected no regressions, got %d", got)
	}
}

func TestCompare_removedPackageIsReportedNotFailed(t *testing.T) {
	profile := profileOf(map[string][2]int{"cmd": {1, 2}})
	baseline := &Baseline{Total: 50, Packages: map[string]float64{"cmd": 50, "internal/gone": 90}}

	report := Compare(profile, baseline, DefaultTolerance)

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
