package cmd

import (
	"errors"
	"os"
	"path/filepath"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
)

// coverageGate is one measurement and how to hold it against its baseline.
// `ods coverage` and `ods type-coverage` share it.
type coverageGate struct {
	Kind    coverage.Kind
	Profile *coverage.Profile
	// BaselinePath is the committed baseline for this measurement.
	BaselinePath string
	// Name heads the markdown section, e.g. "tools/ods".
	Name string
	// Command runs this measurement again, e.g. "ods coverage ods". Hints add
	// --update to it.
	Command   string
	Check     bool
	Update    bool
	Markdown  string
	Tolerance float64
}

// runCoverageGate writes the baseline, or compares against it, and returns the
// process exit code.
func runCoverageGate(g coverageGate) int {
	if g.Update {
		return writeBaseline(g)
	}

	// A measurement opts into the gate by committing a baseline. Without one
	// the report still prints, but nothing can regress.
	baseline, err := coverage.LoadBaseline(g.BaselinePath)
	if errors.Is(err, os.ErrNotExist) {
		log.Warnf("No baseline at %s, so nothing is gated. Opt in with: %s --update", g.BaselinePath, g.Command)
		baseline = nil
	} else if err != nil {
		log.Errorf("Failed to read the baseline: %v", err)
		return 1
	}

	report := coverage.Compare(g.Profile, baseline, g.Tolerance)
	if err := coverage.WriteReport(os.Stdout, report, g.Kind); err != nil {
		log.Errorf("Failed to write the report: %v", err)
		return 1
	}

	if g.Markdown != "" {
		if err := writeMarkdown(g.Markdown, g.Name, report, g.Kind); err != nil {
			log.Errorf("Failed to write the markdown report: %v", err)
			return 1
		}
		log.Infof("Markdown report written to %s", g.Markdown)
	}

	if improvements := report.Improvements(); len(improvements) > 0 {
		log.Infof("%s rose above the baseline. Lock the gain in with: %s --update",
			g.Kind.Count(len(improvements)), g.Command)
	}

	if !g.Check || baseline == nil {
		return 0
	}
	regressions := report.Regressions()
	if len(regressions) == 0 {
		log.Infof("%s holds at or above the baseline in %s", g.Kind.Title(), g.BaselinePath)
		return 0
	}
	for _, regression := range regressions {
		log.Errorf("%s fell to %.1f%%, below its %.1f%% floor", regression.Package, regression.Percent, regression.Floor)
	}
	log.Errorf("%s regressed in %s. %s, or justify the drop and run: %s --update",
		g.Kind.Title(), g.Kind.Count(len(regressions)), g.Kind.Remedy, g.Command)
	return 1
}

func writeBaseline(g coverageGate) int {
	baseline := coverage.NewBaseline(g.Profile)
	if err := baseline.Save(g.BaselinePath, g.Kind); err != nil {
		log.Errorf("Failed to write the baseline: %v", err)
		return 1
	}
	// Report the floor that was recorded, not the raw measurement, so the
	// number here matches the file.
	log.Infof("Wrote %s with a %.1f%% total %s floor across %s",
		g.BaselinePath, baseline.Total, g.Kind.Name, g.Kind.Count(len(baseline.Packages)))
	return 0
}

func writeMarkdown(path, name string, report *coverage.Report, kind coverage.Kind) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer func() { _ = f.Close() }()
	return coverage.WriteMarkdown(f, name, report, kind)
}

// outputTarget resolves where a measurement file is written. Without an
// explicit path it goes to a temporary file that is removed afterwards. A
// requested path is made absolute, since the measuring tool runs in another
// directory than the caller.
func outputTarget(requested, name string) (string, func()) {
	if requested != "" {
		absolute, err := filepath.Abs(requested)
		if err != nil {
			log.Fatalf("Failed to resolve the output path %q: %v", requested, err)
		}
		return absolute, func() {}
	}
	dir, err := os.MkdirTemp("", "ods-coverage")
	if err != nil {
		log.Fatalf("Failed to create a temporary directory: %v", err)
	}
	return filepath.Join(dir, name), func() { _ = os.RemoveAll(dir) }
}
