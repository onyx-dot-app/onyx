package coverage

import (
	"fmt"
	"path/filepath"
	"strings"
)

// Kind describes what a baseline measures, so the gate, the reports, and the
// baseline header use the right words for it.
type Kind struct {
	// Name is the metric as it reads in a sentence, e.g. "type coverage".
	Name string
	// Unit and Units name one report row and several, e.g. "package".
	Unit  string
	Units string
	// Remedy is the first step to fix a regression, as an instruction.
	Remedy string
	// BaselineFile is the name of the committed baseline.
	BaselineFile string
	// BaselineHeader is written above the generated baseline content.
	BaselineHeader string
	// DefaultTolerance is the --tolerance default, in percentage points.
	DefaultTolerance float64
	// RequireBaseline makes --check fail when the baseline is missing. Without
	// it, a missing baseline means the measurement has not opted in yet.
	RequireBaseline bool
}

// GoTests is Go statement coverage, measured per package.
var GoTests = Kind{
	Name:             "coverage",
	Unit:             "package",
	Units:            "packages",
	Remedy:           "Add tests",
	BaselineFile:     BaselineFile,
	BaselineHeader:   baselineHeader,
	DefaultTolerance: DefaultTolerance,
}

// TypeBaselineFile is the name of the committed TypeScript type coverage
// baseline, kept in web/.
const TypeBaselineFile = ".type-coverage-baseline.yaml"

// TypeScript is TypeScript type coverage, measured per directory.
var TypeScript = Kind{
	Name:           "type coverage",
	Unit:           "directory",
	Units:          "directories",
	Remedy:         "Replace the new `any` types, casts and non-null assertions with real types",
	BaselineFile:   TypeBaselineFile,
	BaselineHeader: typeScriptBaselineHeader,
	// Type counts do not depend on ports or timing, so every drop is real.
	DefaultTolerance: 0,
	// web/ always has a baseline, so a missing file must not turn the gate off.
	RequireBaseline: true,
}

const typeScriptBaselineHeader = `# Minimum TypeScript type coverage per directory, in percent. Type coverage is
# the share of identifiers whose type is not ` + "`any`" + `. Each type cast and each
# non-null assertion also counts as uncovered.
#
# ` + "`ods type-coverage typescript --check`" + ` fails when a directory drops below
# its floor, which is how CI keeps ` + "`any`" + ` from spreading. Raise the floors after
# removing ` + "`any`" + ` types, casts or non-null assertions with
# ` + "`ods type-coverage typescript --update`" + `.
#
# Generated file: do not edit by hand.
`

// BaselinePath returns the baseline path in dir.
func (k Kind) BaselinePath(dir string) string {
	return filepath.Join(dir, k.BaselineFile)
}

// Count returns n with the unit, e.g. "1 package" or "3 packages".
func (k Kind) Count(n int) string {
	if n == 1 {
		return fmt.Sprintf("%d %s", n, k.Unit)
	}
	return fmt.Sprintf("%d %s", n, k.Units)
}

// Title returns the metric name for the start of a sentence.
func (k Kind) Title() string {
	return capitalize(k.Name)
}

func capitalize(s string) string {
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + s[1:]
}
