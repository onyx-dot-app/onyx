package openapi

import (
	_ "embed"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

//go:embed openapi_schema.py
var embeddedScript string

// ResolvePath resolves a path to an absolute path.
// If userPath is empty, uses defaultPath relative to git root.
// If userPath is provided, resolves it relative to cwd.
func ResolvePath(userPath string, defaultPath string) (string, error) {
	if userPath == "" {
		// Use default path relative to git root
		root, err := paths.GitRoot()
		if err != nil {
			return "", fmt.Errorf("failed to find git root: %w", err)
		}
		return filepath.Join(root, defaultPath), nil
	}

	// User provided a path - resolve relative to cwd
	if filepath.IsAbs(userPath) {
		return userPath, nil
	}

	cwd, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("failed to get current directory: %w", err)
	}
	return filepath.Join(cwd, userPath), nil
}

// FindPythonBinary locates the Python binary, preferring the venv version.
func FindPythonBinary() (string, error) {
	// Try to find venv python first
	root, err := paths.GitRoot()
	if err == nil {
		var venvPython string
		if runtime.GOOS == "windows" {
			venvPython = filepath.Join(root, ".venv", "Scripts", "python.exe")
		} else {
			venvPython = filepath.Join(root, ".venv", "bin", "python")
		}

		if _, err := os.Stat(venvPython); err == nil {
			log.Debugf("Using venv Python: %s", venvPython)
			return venvPython, nil
		}
	}

	// Fall back to system python
	for _, name := range []string{"python3", "python"} {
		python, err := exec.LookPath(name)
		if err == nil {
			log.Debugf("Using system Python: %s", python)
			return python, nil
		}
	}

	return "", fmt.Errorf("python not found. Ensure you have activated the venv or installed python globally")
}

// RunScript executes the embedded OpenAPI schema generation script with the given arguments.
func RunScript(args []string) error {
	python, err := FindPythonBinary()
	if err != nil {
		return err
	}

	// Get the backend directory to run from
	backendDir, err := paths.BackendDir()
	if err != nil {
		return fmt.Errorf("failed to find backend directory: %w", err)
	}

	// Run the embedded script using python -c
	// We pass the script via stdin to avoid issues with command line length limits
	cmdArgs := append([]string{"-"}, args...)
	cmd := exec.Command(python, cmdArgs...)
	cmd.Dir = backendDir
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = os.Environ()

	// Pass the embedded script via stdin
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("failed to create stdin pipe: %w", err)
	}

	log.Debugf("Running embedded script with: %s %v", python, cmdArgs)
	log.Debugf("Working directory: %s", backendDir)

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start python: %w", err)
	}

	// Write the script to stdin
	if _, err := stdin.Write([]byte(embeddedScript)); err != nil {
		return fmt.Errorf("failed to write script to stdin: %w", err)
	}
	if err := stdin.Close(); err != nil {
		return fmt.Errorf("failed to close stdin: %w", err)
	}

	return cmd.Wait()
}

// GenerateSchema generates the OpenAPI schema to the specified output path.
func GenerateSchema(outputPath string) error {
	args := []string{"schema", "-o", outputPath}
	return RunScript(args)
}

// GenerateClient generates a Python client from an OpenAPI schema.
func GenerateClient(schemaPath string, outputDir string) error {
	args := []string{"client", "-i", schemaPath}
	if outputDir != "" {
		args = append(args, "-o", outputDir)
	}
	return RunScript(args)
}

// GenerateAll generates both the OpenAPI schema and Python client.
func GenerateAll(schemaPath string, clientOutputDir string) error {
	args := []string{"all", "-o", schemaPath}
	if clientOutputDir != "" {
		args = append(args, "--client-output", clientOutputDir)
	}
	return RunScript(args)
}

