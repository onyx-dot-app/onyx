package coverage

import (
	"bytes"
	"fmt"
	"math"
	"os"

	"gopkg.in/yaml.v3"
)

// BaselineFile is the name of the committed Go coverage baseline, kept at the
// root of the module it describes.
const BaselineFile = ".coverage-baseline.yaml"

// baselineHeader is written above a generated Go baseline so a reader of the
// file knows how it is maintained.
const baselineHeader = `# Minimum statement coverage per package, in percent.
#
# ` + "`ods coverage <suite> --check`" + ` fails when a package drops below its floor,
# which is how CI keeps coverage from regressing. Raise the floors after adding
# tests with ` + "`ods coverage <suite> --update`" + `.
#
# Generated file: do not edit by hand.
`

// Baseline is the committed coverage floor for a module.
type Baseline struct {
	// Total is the floor for the module as a whole.
	Total float64 `yaml:"total"`
	// Step is the rounding step of the floors, in percentage points. Zero
	// means the finest step, 0.1.
	Step float64 `yaml:"step,omitempty"`
	// Packages maps a module-relative package path to its floor. A package
	// whose floor rounds down to zero is left out.
	Packages map[string]float64 `yaml:"packages"`
}

// LoadBaseline reads a baseline from disk.
func LoadBaseline(path string) (*Baseline, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var baseline Baseline
	if err := yaml.Unmarshal(data, &baseline); err != nil {
		return nil, fmt.Errorf("parse %s: %w", path, err)
	}
	if baseline.Packages == nil {
		baseline.Packages = map[string]float64{}
	}
	if err := baseline.validate(); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return &baseline, nil
}

// validate rejects floors that cannot be a percentage. A NaN or negative floor
// passes every comparison, so a hand-edited baseline must fail loudly rather
// than silently turn the gate off.
func (b *Baseline) validate() error {
	if math.IsNaN(b.Step) || b.Step < 0 || b.Step > 100 {
		return fmt.Errorf("step must be between 0 and 100, got %v", b.Step)
	}
	if err := validateFloor("total", b.Total); err != nil {
		return err
	}
	for name, floor := range b.Packages {
		if err := validateFloor(name, floor); err != nil {
			return err
		}
	}
	return nil
}

func validateFloor(name string, floor float64) error {
	if math.IsNaN(floor) || floor < 0 || floor > 100 {
		return fmt.Errorf("floor for %s must be between 0 and 100, got %v", name, floor)
	}
	return nil
}

// NewBaseline builds a baseline from a measured profile. Every percentage is
// rounded down to the kind's floor step, so a floor is never above what the
// run actually achieved and re-running the same tests cannot fail the check.
// A coarse step keeps a floor from tracking each small change in coverage.
func NewBaseline(profile *Profile, kind Kind) *Baseline {
	baseline := &Baseline{
		Total:    floorPercent(profile.Total(), kind.FloorStep),
		Step:     kind.FloorStep,
		Packages: make(map[string]float64, len(profile.Packages)),
	}
	for _, pkg := range profile.Packages {
		if floor := floorPercent(pkg.Percent(), kind.FloorStep); floor > 0 {
			baseline.Packages[pkg.Package] = floor
		}
	}
	return baseline
}

// Reference makes the committed floors the target of a comparison. A nil
// baseline, a module that has not opted in, gives a nil reference.
func (b *Baseline) Reference() *Reference {
	if b == nil {
		return nil
	}
	return &Reference{
		Kind:     ReferenceFloor,
		Label:    "floor",
		Total:    b.Total,
		Packages: b.Packages,
		Step:     b.Step,
	}
}

// Save writes the baseline to disk below the kind's header. yaml.v3 sorts map
// keys, so the output is stable across runs and diffs stay readable.
func (b *Baseline) Save(path string, kind Kind) error {
	var body bytes.Buffer
	body.WriteString(kind.BaselineHeader)

	encoder := yaml.NewEncoder(&body)
	encoder.SetIndent(2)
	if err := encoder.Encode(b); err != nil {
		return fmt.Errorf("encode baseline: %w", err)
	}
	if err := encoder.Close(); err != nil {
		return fmt.Errorf("encode baseline: %w", err)
	}

	if err := os.WriteFile(path, body.Bytes(), 0644); err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	return nil
}

// floorPercent rounds a percentage down to a multiple of step. A step of zero
// or below 0.1 rounds down to one decimal place.
func floorPercent(percent, step float64) float64 {
	if step < 0.1 {
		step = 0.1
	}
	// Work in tenths so a step such as 0.1 has no binary rounding error.
	tenths := math.Round(step * 10)
	return math.Floor(math.Round(percent*1e6)/1e6*10/tenths) * tenths / 10
}
