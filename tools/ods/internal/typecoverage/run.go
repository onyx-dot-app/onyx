package typecoverage

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/coverage"
)

// RunOptions configures a measurement.
type RunOptions struct {
	// WebDir is the web/ directory, where the bun script runs.
	WebDir string
	// OutputPath is where the script writes its JSON. It must be absolute,
	// since the script runs in WebDir.
	OutputPath string
	// Stdout and Stderr receive the script output. A nil value discards it.
	Stdout io.Writer
	Stderr io.Writer
}

// Run measures web/ with `bun run types:coverage` and parses the result. When
// the script fails, the error is a *coverage.ExitError with its exit code.
func Run(opts RunOptions) ([]FileCount, error) {
	if !filepath.IsAbs(opts.OutputPath) {
		return nil, fmt.Errorf("output path %q is not absolute", opts.OutputPath)
	}
	if err := os.MkdirAll(filepath.Dir(opts.OutputPath), 0755); err != nil {
		return nil, fmt.Errorf("create output directory: %w", err)
	}

	cmd := exec.Command("bun", "run", "types:coverage", "--", "--output", opts.OutputPath)
	cmd.Dir = opts.WebDir
	cmd.Stdout = opts.Stdout
	cmd.Stderr = opts.Stderr

	if err := cmd.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) && exitErr.ExitCode() != -1 {
			return nil, &coverage.ExitError{Code: exitErr.ExitCode()}
		}
		return nil, fmt.Errorf("run bun: %w", err)
	}

	return ParseFile(opts.OutputPath)
}
