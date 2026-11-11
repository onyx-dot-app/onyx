package cmd

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

// devLicenseEnv names the variable that holds the license internal developers
// seed to unlock paid features. With no license in the database the backend
// runs as Community.
const devLicenseEnv = "ONYX_DEV_LICENSE"

// NewBackendCommand creates the parent "backend" command with subcommands for
// running backend services.
func NewBackendCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "backend",
		Short: "Run backend services (api, model-server)",
		Long: `Run backend services with environment from .vscode/.env.

On first run, copies .vscode/env_template.txt to .vscode/.env if the
.env file does not already exist.

Paid features need a license in the database. When ONYX_DEV_LICENSE is set, in
the shell or in .vscode/.env, "backend api" seeds it before the server starts.
With no license in the database the backend runs as Community Edition.

Available subcommands:
  api            Start the FastAPI backend server
  model-server   Start the model server`,
	}

	cmd.AddCommand(newBackendAPICommand())
	cmd.AddCommand(newBackendModelServerCommand())

	return cmd
}

func newBackendAPICommand() *cobra.Command {
	var port string

	cmd := &cobra.Command{
		Use:   "api",
		Short: "Start the backend API server (uvicorn with hot-reload)",
		Long: `Start the backend API server using uvicorn with hot-reload.

Examples:
  ods backend api
  ods backend api --port 9090`,
		Run: func(cmd *cobra.Command, args []string) {
			if err := runBackendService("api", port, args...); err != nil {
				exitBackendService(err)
			}
		},
	}

	cmd.Flags().StringVar(&port, "port", "", "Port to listen on (default: saved project port, otherwise 8080)")

	return cmd
}

func newBackendModelServerCommand() *cobra.Command {
	var port string

	cmd := &cobra.Command{
		Use:     "model-server",
		Aliases: []string{"model_server"},
		Short:   "Start the model server (uvicorn with hot-reload)",
		Long: `Start the model server using uvicorn with hot-reload.

Examples:
  ods backend model-server
  ods backend model-server --port 9001`,
		Run: func(cmd *cobra.Command, args []string) {
			if err := runBackendService("model", port, args...); err != nil {
				exitBackendService(err)
			}
		},
	}

	cmd.Flags().StringVar(&port, "port", "", "Port to listen on (default: saved project port, otherwise 9000)")

	return cmd
}

// exitBackendService ends the process after a command's child process fails. A
// child that ran and exited passes its exit code through, so the stderr it
// already printed is not repeated.
func exitBackendService(err error) {
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		if code := exitErr.ExitCode(); code != -1 {
			os.Exit(code)
		}
	}
	log.Fatal(err)
}

func runBackendService(name, port string, args ...string) error {
	for _, arg := range args {
		if arg == "--port" || strings.HasPrefix(arg, "--port=") || arg == "-p" {
			return fatalErrorf("Set the backend port with --port before the -- separator")
		}
	}
	root, err := paths.GitRoot()
	if err != nil {
		return fatalErrorf("Failed to find git root: %v", err)
	}

	preferred := 0
	if port != "" {
		preferred, err = strconv.Atoi(port)
		if err != nil || preferred < 1 || preferred > 65535 {
			return fatalErrorf("Invalid port %q", port)
		}
	}
	if _, _, err := devstack.PrepareEnvFiles(root); err != nil {
		return err
	}
	target, err := resolveRuntimeTarget()
	if err != nil {
		return fmt.Errorf("resolve backend target: %v", err)
	}
	launch, err := devstack.LoadLaunch(filepath.Join(root, ".vscode", "launch.json"))
	if err != nil {
		return fmt.Errorf("load backend launch configuration: %v", err)
	}
	options := devstack.ServiceOptions{
		PreferredPort: preferred, Args: args,
		BeforeStart: func(ctx context.Context, sp devstack.Spec) error {
			if err := runInDir(ctx, root, "uv", "sync", "--frozen"); err != nil {
				if ctx.Err() != nil {
					return ctx.Err()
				}
				return fatalErrorf("Failed to sync Python dependencies: %v", err)
			}
			return prepareAPIService(ctx, sp)
		},
		IO:       devstack.ServiceIO{Stdin: os.Stdin, Stdout: os.Stdout, Stderr: os.Stderr},
		LockWait: 30 * time.Second, StopTimeout: 20 * time.Second,
	}
	if runtime.GOOS == "windows" {
		return devstack.RunForegroundService(context.Background(), target, launch, name, options)
	}
	if err := stackForTarget(target).RunService(context.Background(), target, launch, name, options); err != nil {
		return fatalErrorf("Failed to run %s: %w", name, err)
	}
	return nil
}

func prepareAPIService(ctx context.Context, sp devstack.Spec) error {
	if sp.Slug != "api" {
		return nil
	}
	return seedDevLicense(ctx, sp.Dir, sp.Env)
}

// seedDevLicense installs the dev license so paid features unlock. It does
// nothing when the variable is unset or empty. Multi-tenant mode takes its
// tier from the control plane, and the seed has no tenant to write to.
func seedDevLicense(ctx context.Context, backendDir string, env []string) error {
	if devstack.EnvValue(env, devLicenseEnv) == "" {
		return nil
	}
	if strings.EqualFold(devstack.EnvValue(env, "MULTI_TENANT"), "true") {
		log.Infof("Not seeding the dev license from %s in multi-tenant mode", devLicenseEnv)
		return nil
	}

	log.Infof("Seeding the dev license from %s...", devLicenseEnv)
	seedCmd := exec.CommandContext(ctx, "uv", "run", "python", "-m", "scripts.seed_dev_license")
	seedCmd.Dir = backendDir
	seedCmd.Stdout = os.Stdout
	seedCmd.Stderr = os.Stderr
	seedCmd.Env = env
	if err := seedCmd.Run(); err != nil {
		return fatalErrorf("Failed to seed the dev license: %v", err)
	}
	return nil
}
