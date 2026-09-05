package coverage

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// ExitError reports that the test run itself failed, carrying the exit code so
// the caller can hand the underlying tool's result back to the shell.
type ExitError struct {
	Code int
}

func (e *ExitError) Error() string {
	return fmt.Sprintf("go test exited with code %d", e.Code)
}

// RunOptions configures a coverage run.
type RunOptions struct {
	// ModuleDir is the directory holding the module's go.mod. go test runs
	// here, which is where its "./..." pattern resolves.
	ModuleDir string
	// ProfilePath is where the coverage profile is written.
	ProfilePath string
	// Args are extra arguments for go test, such as "-race".
	Args []string
	// Stdout and Stderr receive the test output. A nil value discards it.
	Stdout io.Writer
	Stderr io.Writer
}

// Run executes the module's tests with coverage enabled and parses the profile.
//
// Coverage is measured per package with `go test -coverprofile`, so a package's
// number counts only its own tests. That is the number a package owner can act
// on; a cross-package `-coverpkg` total would credit a package for statements
// its own tests never assert on.
func Run(opts RunOptions) (*Profile, error) {
	modulePath, err := ModulePath(opts.ModuleDir)
	if err != nil {
		return nil, err
	}

	if err := os.MkdirAll(filepath.Dir(opts.ProfilePath), 0755); err != nil {
		return nil, fmt.Errorf("create profile directory: %w", err)
	}

	args := []string{"test"}
	args = append(args, opts.Args...)
	args = append(args, "-coverprofile="+opts.ProfilePath, "./...")

	cmd := exec.Command("go", args...)
	cmd.Dir = opts.ModuleDir
	cmd.Stdout = opts.Stdout
	cmd.Stderr = opts.Stderr

	runErr := cmd.Run()
	if runErr != nil {
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) && exitErr.ExitCode() != -1 {
			return nil, &ExitError{Code: exitErr.ExitCode()}
		}
		return nil, fmt.Errorf("run go test: %w", runErr)
	}

	return ParseProfileFile(opts.ProfilePath, modulePath)
}

// ModulePath reads the module path from the go.mod in dir. Coverage profiles
// name packages by full import path; the module path is what turns those into
// the short, module-relative names used in the baseline.
func ModulePath(dir string) (string, error) {
	goMod := filepath.Join(dir, "go.mod")
	f, err := os.Open(goMod)
	if err != nil {
		return "", fmt.Errorf("open %s: %w", goMod, err)
	}
	defer func() { _ = f.Close() }()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if path, ok := strings.CutPrefix(line, "module "); ok {
			return strings.TrimSpace(path), nil
		}
	}
	if err := scanner.Err(); err != nil {
		return "", fmt.Errorf("read %s: %w", goMod, err)
	}
	return "", fmt.Errorf("no module declaration in %s", goMod)
}
