package coverage

import "sort"

// DefaultTolerance is how far below its floor a package may sit without failing
// the check, in percentage points. Statement coverage is deterministic for
// deterministic tests, but a few suites depend on ports or timing, so a small
// allowance keeps the gate from flagging noise as a regression.
const DefaultTolerance = 0.1

// Status is the verdict for one package.
type Status string

const (
	// StatusOK means coverage held at or above the floor.
	StatusOK Status = "ok"
	// StatusImproved means coverage rose above the floor, so the baseline is
	// now stale and can be raised.
	StatusImproved Status = "improved"
	// StatusRegressed means coverage fell below the floor. This fails the check.
	StatusRegressed Status = "regressed"
	// StatusNew means the package has no floor yet.
	StatusNew Status = "new"
	// StatusRemoved means the baseline names a package the run did not report.
	StatusRemoved Status = "removed"
)

// Result is the comparison of one package against its floor.
type Result struct {
	// Package is the module-relative package path, or "total" for the module.
	Package string
	// Percent is the coverage measured by this run. It is meaningless when
	// Status is StatusRemoved.
	Percent float64
	// Floor is the baseline value. It is meaningless when Status is StatusNew.
	Floor  float64
	Status Status
}

// Report is the outcome of comparing a profile against a baseline.
type Report struct {
	// Total compares the module as a whole.
	Total Result
	// Packages compares each package, sorted by package path.
	Packages []Result
	// Tolerance is the allowance the comparison used, in percentage points.
	Tolerance float64
}

// Compare checks a measured profile against a baseline. A nil baseline reports
// every package as new, which is what a first run sees.
func Compare(profile *Profile, baseline *Baseline, tolerance float64) *Report {
	report := &Report{
		Packages:  make([]Result, 0, len(profile.Packages)),
		Tolerance: tolerance,
	}

	if baseline == nil {
		baseline = &Baseline{Packages: map[string]float64{}}
		report.Total = Result{Package: "total", Percent: profile.Total(), Status: StatusNew}
	} else {
		report.Total = compareOne("total", profile.Total(), baseline.Total, true, tolerance)
	}

	seen := make(map[string]bool, len(profile.Packages))
	for _, pkg := range profile.Packages {
		seen[pkg.Package] = true
		floor, hasFloor := baseline.Packages[pkg.Package]
		report.Packages = append(report.Packages, compareOne(pkg.Package, pkg.Percent(), floor, hasFloor, tolerance))
	}

	// A package in the baseline but not in the run was deleted or renamed.
	// Report it so the stale row gets cleaned up, but do not fail on it.
	for name, floor := range baseline.Packages {
		if !seen[name] {
			report.Packages = append(report.Packages, Result{
				Package: name,
				Floor:   floor,
				Status:  StatusRemoved,
			})
		}
	}

	sort.Slice(report.Packages, func(i, j int) bool {
		return report.Packages[i].Package < report.Packages[j].Package
	})
	return report
}

func compareOne(name string, percent, floor float64, hasFloor bool, tolerance float64) Result {
	result := Result{Package: name, Percent: percent, Floor: floor}
	switch {
	case !hasFloor:
		result.Status = StatusNew
	case percent < floor-tolerance:
		result.Status = StatusRegressed
	case percent > floor+tolerance:
		result.Status = StatusImproved
	default:
		result.Status = StatusOK
	}
	return result
}

// Regressions returns the packages that fell below their floor, plus the module
// total when it regressed. An empty result means the check passes.
func (r *Report) Regressions() []Result {
	var out []Result
	if r.Total.Status == StatusRegressed {
		out = append(out, r.Total)
	}
	for _, pkg := range r.Packages {
		if pkg.Status == StatusRegressed {
			out = append(out, pkg)
		}
	}
	return out
}

// Improvements returns the packages that rose above their floor, plus the
// module total when it improved. These are what `--update` would record.
func (r *Report) Improvements() []Result {
	var out []Result
	if r.Total.Status == StatusImproved {
		out = append(out, r.Total)
	}
	for _, pkg := range r.Packages {
		if pkg.Status == StatusImproved {
			out = append(out, pkg)
		}
	}
	return out
}
