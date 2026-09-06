package coverage

import (
	"bytes"
	"fmt"
	"math"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// BaselineFile is the name of the committed baseline, kept at the root of the
// module it describes.
const BaselineFile = ".coverage-baseline.yaml"

// baselineHeader is written above the generated content so a reader of the file
// knows how it is maintained.
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
	// Packages maps a module-relative package path to its floor.
	Packages map[string]float64 `yaml:"packages"`
}

// BaselinePath returns the baseline path for a module directory.
func BaselinePath(moduleDir string) string {
	return filepath.Join(moduleDir, BaselineFile)
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
// rounded down to one decimal, so a floor is never above what the run actually
// achieved and re-running the same tests cannot fail the check.
func NewBaseline(profile *Profile) *Baseline {
	baseline := &Baseline{
		Total:    floorPercent(profile.Total()),
		Packages: make(map[string]float64, len(profile.Packages)),
	}
	for _, pkg := range profile.Packages {
		baseline.Packages[pkg.Package] = floorPercent(pkg.Percent())
	}
	return baseline
}

// Save writes the baseline to disk. yaml.v3 sorts map keys, so the output is
// stable across runs and diffs stay readable.
func (b *Baseline) Save(path string) error {
	var body bytes.Buffer
	body.WriteString(baselineHeader)

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

// floorPercent rounds a percentage down to one decimal place.
func floorPercent(percent float64) float64 {
	return math.Floor(percent*10) / 10
}
