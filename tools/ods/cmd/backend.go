package cmd

import (
	"os"
	"os/exec"
	"path/filepath"
	"strconv"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/backendenv"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/childproc"
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
			runBackendService("api", "onyx.main:app", port, opts)
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
			runBackendService("model_server", "model_server.main:app", port, opts)
		},
	}

	cmd.Flags().StringVar(&port, "port", "9000", "Port to listen on")

	return cmd
}

func resolvePort(port string) string {
	portNum, err := strconv.Atoi(port)
	if err != nil {
		log.Fatalf("Invalid port %q: %v", port, err)
	}
	resolved, err := portutil.FindAvailable(portNum, 65535-portNum, nil)
	if err != nil {
		log.Fatalf("No available ports found starting from %d", portNum)
	}
	return strconv.Itoa(resolved)
}

func runBackendService(name, module, port string, opts *BackendOptions) {
	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}

	port = resolvePort(port)

	envFile, err := backendenv.EnsureFile(root)
	if err != nil {
		log.Fatal(err)
	}
	fileVars, err := backendenv.Load(envFile)
	if err != nil {
		log.Fatal(err)
	}
	fileVars = append(fileVars, backendenv.EEDefaults(opts.NoEE)...)

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

	mergedEnv := backendenv.Merge(os.Environ(), fileVars)
	log.Debugf("Applied %d env vars from %s (shell takes precedence)", len(fileVars), envFile)

	svcCmd := exec.Command("uv", uvicornArgs...)
	svcCmd.Dir = backendDir
	svcCmd.Env = mergedEnv
	childproc.Run(svcCmd, name)
}
