package cmd

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/portutil"
)

// NewBackendCommand creates the parent "backend" command with subcommands for
// running backend services.
// BackendOptions holds options shared across backend subcommands.
type BackendOptions struct {
	NoEE bool
}

func NewBackendCommand() *cobra.Command {
	opts := &BackendOptions{}

	cmd := &cobra.Command{
		Use:   "backend",
		Short: "Run backend services (api, model_server)",
		Long: `Run backend services with environment from .vscode/.env.

On first run, copies .vscode/env_template.txt to .vscode/.env if the
.env file does not already exist.

Enterprise Edition features are enabled by default for development,
with license enforcement disabled.

Available subcommands:
  api            Start the FastAPI backend server
  model_server   Start the model server`,
	}

	cmd.PersistentFlags().BoolVar(&opts.NoEE, "no-ee", false, "Disable Enterprise Edition features (enabled by default)")

	cmd.AddCommand(newBackendAPICommand(opts))
	cmd.AddCommand(newBackendModelServerCommand(opts))

	return cmd
}

func newBackendAPICommand(opts *BackendOptions) *cobra.Command {
	var port string

	cmd := &cobra.Command{
		Use:   "api",
		Short: "Start the backend API server (uvicorn with hot-reload)",
		Long: `Start the backend API server using uvicorn with hot-reload.

Examples:
  ods backend api
  ods backend api --port 9090
  ods backend api --no-ee`,
		Run: func(cmd *cobra.Command, args []string) {
			if err := runBackendService("api", "onyx.main:app", port, opts); err != nil {
				exitBackendService(err)
			}
		},
	}

	cmd.Flags().StringVar(&port, "port", "8080", "Port to listen on")

	return cmd
}

func newBackendModelServerCommand(opts *BackendOptions) *cobra.Command {
	var port string

	cmd := &cobra.Command{
		Use:   "model_server",
		Short: "Start the model server (uvicorn with hot-reload)",
		Long: `Start the model server using uvicorn with hot-reload.

Examples:
  ods backend model_server
  ods backend model_server --port 9001`,
		Run: func(cmd *cobra.Command, args []string) {
			if err := runBackendService("model_server", "model_server.main:app", port, opts); err != nil {
				exitBackendService(err)
			}
		},
	}

	cmd.Flags().StringVar(&port, "port", "9000", "Port to listen on")

	return cmd
}

func resolvePort(port string) (string, error) {
	portNum, err := strconv.Atoi(port)
	if err != nil {
		return "", fatalErrorf("Invalid port %q: %v", port, err)
	}
	resolved, err := portutil.FindAvailable(portNum, 65535-portNum, nil)
	if err != nil {
		return "", fatalErrorf("No available ports found starting from %d", portNum)
	}
	return strconv.Itoa(resolved), nil
}

// exitBackendService ends the process after runBackendService fails. A service
// that ran and exited passes its exit code through, so the stderr it already
// printed is not repeated.
func exitBackendService(err error) {
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		if code := exitErr.ExitCode(); code != -1 {
			os.Exit(code)
		}
	}
	log.Fatal(err)
}

// runBackendService runs the service with uv. Only the service's own failure
// wraps its *exec.ExitError. Setup errors format theirs with %v, so a failing
// git call is logged rather than passed through as an exit code.
func runBackendService(name, module, port string, opts *BackendOptions) error {
	root, err := paths.GitRoot()
	if err != nil {
		return fatalErrorf("Failed to find git root: %v", err)
	}

	port, err = resolvePort(port)
	if err != nil {
		return err
	}

	envFile, err := ensureBackendEnvFile(root)
	if err != nil {
		return err
	}
	fileVars, err := loadBackendEnvFile(envFile)
	if err != nil {
		return err
	}

	eeDefaults := eeEnvDefaults(opts.NoEE)
	fileVars = append(fileVars, eeDefaults...)

	backendDir := filepath.Join(root, "backend")

	uvicornArgs := []string{
		"run", "uvicorn", module,
		"--reload",
		"--port", port,
	}
	log.Infof("Starting %s on port %s...", name, port)
	if !opts.NoEE {
		log.Info("Enterprise Edition enabled (use --no-ee to disable)")
	}
	log.Debugf("Running in %s: uv %v", backendDir, uvicornArgs)

	mergedEnv := mergeEnv(os.Environ(), fileVars)
	log.Debugf("Applied %d env vars from %s (shell takes precedence)", len(fileVars), envFile)

	svcCmd := exec.Command("uv", uvicornArgs...)
	svcCmd.Dir = backendDir
	svcCmd.Stdout = os.Stdout
	svcCmd.Stderr = os.Stderr
	svcCmd.Stdin = os.Stdin
	svcCmd.Env = mergedEnv

	if err := svcCmd.Run(); err != nil {
		return fatalErrorf("Failed to run %s: %w", name, err)
	}
	return nil
}

// eeEnvDefaults returns env entries for EE and license enforcement settings.
// These are appended to the file vars so they act as defaults — shell env
// and .env file values still take precedence via mergeEnv.
func eeEnvDefaults(noEE bool) []string {
	if noEE {
		return []string{
			"ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=false",
		}
	}
	return []string{
		"ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=true",
		"LICENSE_ENFORCEMENT_ENABLED=false",
	}
}

// ensureBackendEnvFile copies env_template.txt to .env if .env doesn't exist.
func ensureBackendEnvFile(root string) (string, error) {
	vscodeDir := filepath.Join(root, ".vscode")
	envFile := filepath.Join(vscodeDir, ".env")
	templateFile := filepath.Join(vscodeDir, "env_template.txt")

	if _, err := os.Stat(envFile); err != nil {
		if !errors.Is(err, os.ErrNotExist) {
			return "", fatalErrorf("Failed to stat env file %s: %v", envFile, err)
		}
	} else {
		log.Debugf("Using existing env file: %s", envFile)
		return envFile, nil
	}

	templateData, err := os.ReadFile(templateFile)
	if err != nil {
		return "", fatalErrorf("Failed to read env template %s: %v", templateFile, err)
	}

	if err := os.MkdirAll(vscodeDir, 0755); err != nil {
		return "", fatalErrorf("Failed to create .vscode directory: %v", err)
	}

	if err := os.WriteFile(envFile, templateData, 0644); err != nil {
		return "", fatalErrorf("Failed to write env file %s: %v", envFile, err)
	}

	log.Infof("Created %s from template (review and fill in <REPLACE THIS> values)", envFile)
	return envFile, nil
}

// mergeEnv combines shell environment with file-based defaults. Shell values
// take precedence — file entries are only added for keys not already present.
func mergeEnv(shellEnv, fileVars []string) []string {
	existing := make(map[string]bool, len(shellEnv))
	for _, entry := range shellEnv {
		if idx := strings.Index(entry, "="); idx > 0 {
			existing[entry[:idx]] = true
		}
	}

	merged := make([]string, len(shellEnv))
	copy(merged, shellEnv)
	for _, entry := range fileVars {
		if idx := strings.Index(entry, "="); idx > 0 {
			key := entry[:idx]
			if !existing[key] {
				merged = append(merged, entry)
			} else {
				log.Debugf("Env var %s already set in shell, skipping .env value", key)
			}
		}
	}
	return merged
}

// loadBackendEnvFile parses a .env file into KEY=VALUE entries suitable for
// appending to os.Environ(). Blank lines and comments are skipped.
func loadBackendEnvFile(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fatalErrorf("Failed to open env file %s: %v", path, err)
	}
	defer func() { _ = f.Close() }()

	var envVars []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if idx := strings.Index(line, "="); idx > 0 {
			key := strings.TrimSpace(line[:idx])
			value := strings.TrimSpace(line[idx+1:])
			value = strings.Trim(value, `"'`)
			envVars = append(envVars, fmt.Sprintf("%s=%s", key, value))
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, fatalErrorf("Failed to read env file %s: %v", path, err)
	}

	return envVars, nil
}
