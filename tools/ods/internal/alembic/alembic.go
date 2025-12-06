package alembic

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// Schema represents an Alembic schema configuration.
type Schema string

const (
	SchemaDefault Schema = "default"
	SchemaPrivate Schema = "private"
)

// FindAlembicBinary locates the alembic binary, preferring the venv version.
func FindAlembicBinary() (string, error) {
	// Try to find venv alembic first
	root, err := paths.GitRoot()
	if err == nil {
		var venvAlembic string
		if runtime.GOOS == "windows" {
			venvAlembic = filepath.Join(root, ".venv", "Scripts", "alembic.exe")
		} else {
			venvAlembic = filepath.Join(root, ".venv", "bin", "alembic")
		}

		if _, err := os.Stat(venvAlembic); err == nil {
			return venvAlembic, nil
		}
	}

	// Fall back to system alembic
	alembic, err := exec.LookPath("alembic")
	if err != nil {
		return "", fmt.Errorf("alembic not found. Ensure you have activated the venv or installed alembic globally")
	}
	return alembic, nil
}

// Run executes an alembic command with the given arguments.
func Run(args []string, schema Schema) error {
	backendDir, err := paths.BackendDir()
	if err != nil {
		return fmt.Errorf("failed to find backend directory: %w", err)
	}

	alembic, err := FindAlembicBinary()
	if err != nil {
		return err
	}

	// Build the full command
	var cmdArgs []string
	if schema == SchemaPrivate {
		cmdArgs = append(cmdArgs, "-n", "schema_private")
	}
	cmdArgs = append(cmdArgs, args...)

	cmd := exec.Command(alembic, cmdArgs...)
	cmd.Dir = backendDir
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin

	return cmd.Run()
}

// Upgrade runs alembic upgrade to the specified revision.
func Upgrade(revision string, schema Schema) error {
	if revision == "" {
		revision = "head"
	}
	return Run([]string{"upgrade", revision}, schema)
}

// Downgrade runs alembic downgrade to the specified revision.
func Downgrade(revision string, schema Schema) error {
	return Run([]string{"downgrade", revision}, schema)
}

// Current shows the current alembic revision.
func Current(schema Schema) error {
	return Run([]string{"current"}, schema)
}

// History shows the alembic migration history.
func History(schema Schema, verbose bool) error {
	args := []string{"history"}
	if verbose {
		args = append(args, "-v")
	}
	return Run(args, schema)
}
