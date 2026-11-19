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

// Each package gets a status against its floor or base, and only a drop past
// the tolerance fails the check.
func TestCompare_packageStatus(t *testing.T) {
	floor50 := floorReference(&Baseline{Total: 50, Packages: map[string]float64{"cmd": 50}})
	cases := []struct {
		name             string
		counts           map[string][2]int
		reference        *Reference
		pkg              string
		want             Status
		wantRegressions  int
		wantImprovements int
	}{
		{"below the floor", map[string][2]int{"cmd": {1, 4}}, floor50, "cmd", StatusRegressed, 1, 0},
		{"at the floor", map[string][2]int{"cmd": {1, 2}}, floor50, "cmd", StatusOK, 0, 0},
		{"above the floor", map[string][2]int{"cmd": {3, 4}}, floor50, "cmd", StatusImproved, 0, 1},
		{
			"drop inside the tolerance", map[string][2]int{"cmd": {999, 1000}},
			floorReference(&Baseline{Total: 99.9, Packages: map[string]float64{"cmd": 100}}), "cmd", StatusOK, 0, 0,
		},
		{
			"drop inside the tolerance against a base", map[string][2]int{"cmd": {1999, 2000}},
			baseReference(map[string][2]int{"cmd": {2000, 2000}}), "cmd", StatusOK, 0, 0,
		},
		// A package without a floor cannot fail a check it was never measured for.
		{"new package", map[string][2]int{"cmd": {1, 2}, "internal/new": {0, 10}}, floor50, "internal/new", StatusNew, 0, 0},
		{
			"removed package", map[string][2]int{"cmd": {1, 2}},
			floorReference(&Baseline{Total: 50, Packages: map[string]float64{"cmd": 50, "internal/gone": 90}}),
			"internal/gone", StatusRemoved, 0, 0,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			report := Compare(profileOf(tc.counts), tc.reference, DefaultTolerance)

			if got := statusOf(t, report, tc.pkg); got != tc.want {
				t.Fatalf("expected %q, got %q", tc.want, got)
			}
			if got := len(report.Regressions()); got != tc.wantRegressions {
				t.Fatalf("expected %d regressions, got %d", tc.wantRegressions, got)
			}
			if got := len(report.Improvements()); got != tc.wantImprovements {
				t.Fatalf("expected %d improvements, got %d", tc.wantImprovements, got)
			}
		})
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
