package coverage

import (
	"fmt"
	"math"
	"sort"
)

// DefaultTolerance is how far below its floor a package may sit without failing
// the check, in percentage points. Statement coverage is deterministic for
// deterministic tests, but a few suites depend on ports or timing, so a small
// allowance keeps the gate from flagging noise as a regression.
const DefaultTolerance = 0.1

// ReferenceKind says where a Reference came from.
type ReferenceKind string

const (
	// ReferenceFloor is the committed .coverage-baseline.yaml.
	ReferenceFloor ReferenceKind = "floor"
	// ReferenceBase is a recorded snapshot of a base commit.
	ReferenceBase ReferenceKind = "base"
)

// Reference is what a profile is compared against: the committed floors, or
// the exact coverage of a base commit.
type Reference struct {
	Kind ReferenceKind
	// Label names the reference in reports: "floor" for the committed floors,
	// or the short commit SHA for a base snapshot.
	Label string
	// Total is the reference value for the module as a whole.
	Total float64
	// Packages maps a module-relative package path to its reference value.
	Packages map[string]float64
}

// Status is the verdict for one package.
type Status string

const (
	// StatusOK means coverage held at or above the reference.
	StatusOK Status = "ok"
	// StatusImproved means coverage rose above the reference. Against the
	// floors that means the baseline is stale and can be raised.
	StatusImproved Status = "improved"
	// StatusRegressed means coverage fell below the reference. Against the
	// floors this fails the check.
	StatusRegressed Status = "regressed"
	// StatusNew means the reference has no value for the package.
	StatusNew Status = "new"
	// StatusRemoved means the reference names a package the run did not report.
	StatusRemoved Status = "removed"
)

// Result is the comparison of one package against its reference.
type Result struct {
	// Package is the module-relative package path, or "total" for the module.
	Package string
	// Percent is the coverage measured by this run. It is meaningless when
	// Status is StatusRemoved.
	Percent float64
	// Reference is the value compared against. It is meaningless when Status
	// is StatusNew.
	Reference float64
	Status    Status
}

// Report is the outcome of comparing a profile against a reference.
type Report struct {
	// Total compares the module as a whole. It is reported but never gated:
	// the package floors are the gate, and a package added or deleted moves
	// the total without any package regressing.
	Total Result
	// Packages compares each package, sorted by package path.
	Packages []Result
	// Tolerance is the allowance the comparison used, in percentage points.
	Tolerance float64
	// Reference is what the profile was compared against. It is nil when the
	// profile was compared against nothing.
	Reference *Reference
}

// Compare checks a measured profile against a reference. A nil reference
// reports every package as new, which is what a first run sees.
func Compare(profile *Profile, reference *Reference, tolerance float64) *Report {
	report := &Report{
		Packages:  make([]Result, 0, len(profile.Packages)),
		Tolerance: tolerance,
		Reference: reference,
	}

	var kind ReferenceKind
	values := map[string]float64{}
	if reference == nil {
		report.Total = Result{Package: "total", Percent: profile.Total(), Status: StatusNew}
	} else {
		kind = reference.Kind
		values = reference.Packages
		report.Total = compareOne("total", profile.Total(), reference.Total, true, tolerance, kind)
	}

	seen := make(map[string]bool, len(profile.Packages))
	for _, pkg := range profile.Packages {
		seen[pkg.Package] = true
		value, hasValue := values[pkg.Package]
		report.Packages = append(report.Packages, compareOne(pkg.Package, pkg.Percent(), value, hasValue, tolerance, kind))
	}

	// A package in the reference but not in the run was deleted or renamed.
	// Report it so the stale row gets cleaned up, but do not fail on it.
	for name, value := range values {
		if !seen[name] {
			report.Packages = append(report.Packages, Result{
				Package:   name,
				Reference: value,
				Status:    StatusRemoved,
			})
		}
	}

	sort.Slice(report.Packages, func(i, j int) bool {
		return report.Packages[i].Package < report.Packages[j].Package
	})
	return report
}

func compareOne(name string, percent, reference float64, hasReference bool, tolerance float64, kind ReferenceKind) Result {
	result := Result{Package: name, Percent: percent, Reference: reference}
	switch {
	case !hasReference:
		result.Status = StatusNew
	case percent < reference-tolerance:
		result.Status = StatusRegressed
	case kind.recorded(percent) > reference+tolerance:
		result.Status = StatusImproved
	default:
		result.Status = StatusOK
	}
	return result
}

// recorded returns what a reference of this kind would hold for a measured
// percent. Floors are rounded down, so an improvement is judged on what
// `--update` would record; else a zero tolerance reports the rounding as an
// improvement. A base snapshot holds exact counts, so the percent stands.
func (k ReferenceKind) recorded(percent float64) float64 {
	if k == ReferenceFloor {
		return floorPercent(percent)
	}
	return percent
}

// Regressions returns the packages that fell below their reference. An empty
// result means the check passes. The module total is not included: see Report.
func (r *Report) Regressions() []Result {
	var out []Result
	for _, pkg := range r.Packages {
		if pkg.Status == StatusRegressed {
			out = append(out, pkg)
		}
	}
	return out
}

// Improvements returns the packages that rose above their reference. Against
// the floors these are what `--update` would record.
func (r *Report) Improvements() []Result {
	var out []Result
	for _, pkg := range r.Packages {
		if pkg.Status == StatusImproved {
			out = append(out, pkg)
		}
	}
	return out
}

// Changed reports whether any package moved against the reference. A run with
// no reference has nothing to change against.
func (r *Report) Changed() bool {
	if r.Total.Status == StatusNew {
		return false
	}
	for _, pkg := range r.Packages {
		if pkg.Status != StatusOK {
			return true
		}
	}
	return false
}

// ValidateTolerance rejects a tolerance that would make the comparison
// meaningless. NaN and +Inf make every comparison pass, and a negative value
// fails a package that holds exactly at its floor.
func ValidateTolerance(tolerance float64) error {
	if math.IsNaN(tolerance) || math.IsInf(tolerance, 0) || tolerance < 0 {
		return fmt.Errorf("tolerance must be a finite number of at least 0, got %v", tolerance)
	}
	return nil
}
