package alembic

import (
	"context"
	"errors"
	"fmt"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/devstack"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/postgres"
)

func MigrationsPending(ctx context.Context, root string, env []string) (bool, error) {
	const probe = `from types import SimpleNamespace
from alembic import command
from alembic.config import Config
from alembic.util import DatabaseNotAtHead
config = Config("alembic.ini")
config.cmd_opts = SimpleNamespace(x=["create_schema=false"])
try:
    command.current(config, check_heads=True)
except DatabaseNotAtHead:
    raise SystemExit(10)
`
	cmd := exec.CommandContext(ctx, devstack.PythonExecutable(root), "-c", probe)
	cmd.Dir, cmd.Env = filepath.Join(root, "backend"), env
	output, err := cmd.CombinedOutput()
	if ctx.Err() != nil {
		return false, ctx.Err()
	}
	if err == nil {
		return false, nil
	}
	var exit *exec.ExitError
	if errors.As(err, &exit) && exit.ExitCode() == 10 {
		return true, nil
	}
	return false, fmt.Errorf("alembic revision check: %w\n%s", err, output)
}

type Schema string

const (
	SchemaDefault Schema = "default"
	SchemaPrivate Schema = "private"
)

func FindAlembicBinary() (string, error) {
	root, _ := paths.GitRoot()
	return findAlembicBinary(root)
}

func findAlembicBinary(root string) (string, error) {
	if root != "" {
		binary := filepath.Join(root, ".venv", "bin", "alembic")
		if runtime.GOOS == "windows" {
			binary = filepath.Join(root, ".venv", "Scripts", "alembic.exe")
		}
		if _, err := os.Stat(binary); err == nil {
			return binary, nil
		}
	}
	binary, err := exec.LookPath("alembic")
	if err != nil {
		return "", fmt.Errorf("alembic not found. Ensure you have activated the venv or installed alembic globally")
	}
	return binary, nil
}

// Run uses only the selected stack or an explicitly configured network database.
func Run(target devstack.Target, args []string, schema Schema) error {
	fileEnv, err := devstack.LoadEnvFile(filepath.Join(target.Root, ".vscode", ".env"))
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	env := devstack.MergeEnv(fileEnv, os.Environ())
	config := postgres.NewConfigFromEnvironment(append(fileEnv, os.Environ()...))
	explicitHost := os.Getenv("POSTGRES_HOST") != ""
	fileNetwork := !target.Managed && !postgres.IsLoopbackHost(config.Host)
	if !explicitHost && !fileNetwork {
		container, err := docker.FindPostgresContainer(target.Project)
		if err != nil {
			return err
		}
		port, err := docker.GetHostPort(container, 5432)
		if err != nil {
			return runViaDockerExec(target, args, schema, config)
		}
		// The actual mapping wins over both stale files and a saved lease.
		target.Ports = maps.Clone(target.Ports)
		if target.Ports == nil {
			target.Ports = map[string]int{}
		}
		target.Ports["POSTGRES_HOST_PORT"] = port
		env, err = target.Environment()
		if err != nil {
			return err
		}
		env = devstack.MergeEnv(env, []string{"POSTGRES_HOST=localhost", "POSTGRES_PORT=" + strconv.Itoa(port)})
		config.Host, config.Port = "localhost", strconv.Itoa(port)
	}
	env = devstack.MergeEnv(env, []string{
		"POSTGRES_HOST=" + config.Host, "POSTGRES_PORT=" + config.Port,
		"POSTGRES_USER=" + config.User, "POSTGRES_PASSWORD=" + config.Password, "POSTGRES_DB=" + config.Database,
	})
	log.Infof("Running alembic for project %s against %s:%s", target.Project, config.Host, config.Port)
	return runLocally(target, args, schema, env)
}

func commandArgs(args []string, schema Schema) []string {
	result := []string{}
	if schema == SchemaPrivate {
		result = append(result, "-n", "schema_private")
	}
	return append(result, args...)
}

func runLocally(target devstack.Target, args []string, schema Schema, env []string) error {
	backend := filepath.Join(target.Root, "backend")
	if info, err := os.Stat(backend); err != nil || !info.IsDir() {
		return fmt.Errorf("failed to find backend directory for selected checkout")
	}
	binary, err := findAlembicBinary(target.Root)
	if err != nil {
		return err
	}
	cmd := exec.Command(binary, commandArgs(args, schema)...)
	cmd.Dir, cmd.Env = backend, env
	cmd.Stdout, cmd.Stderr, cmd.Stdin = os.Stdout, os.Stderr, os.Stdin
	return cmd.Run()
}

func runViaDockerExec(target devstack.Target, args []string, schema Schema, config *postgres.Config) error {
	container, err := findAlembicContainer(target.Project)
	if err != nil {
		return fmt.Errorf("PostgreSQL for project %q has no exposed port and no selected api_server container: %w", target.Project, err)
	}
	log.Infof("Running alembic for project %s in container %s", target.Project, container)
	dockerArgs := []string{"exec", "-i",
		"-e", "POSTGRES_HOST=" + docker.ContainerName(docker.NormalizeProjectName(target.Project), "relational_db"),
		"-e", "POSTGRES_PORT=5432",
		"-e", "POSTGRES_USER=" + config.User,
		"-e", "POSTGRES_PASSWORD",
		"-e", "POSTGRES_DB=" + config.Database,
		container, "alembic",
	}
	dockerArgs = append(dockerArgs, commandArgs(args, schema)...)
	cmd := exec.Command("docker", dockerArgs...)
	cmd.Env = devstack.MergeEnv(os.Environ(), []string{"POSTGRES_PASSWORD=" + config.Password})
	cmd.Stdout, cmd.Stderr, cmd.Stdin = os.Stdout, os.Stderr, os.Stdin
	return cmd.Run()
}

func findAlembicContainer(project string) (string, error) {
	if strings.TrimSpace(project) == "" {
		return "", fmt.Errorf("an Alembic project must be selected")
	}
	container := docker.ContainerName(docker.NormalizeProjectName(project), "api_server")
	cmd := exec.Command("docker", "inspect", "-f", "{{.State.Running}}", container)
	output, err := cmd.Output()
	if err == nil && strings.TrimSpace(string(output)) == "true" {
		return container, nil
	}
	return "", fmt.Errorf("no running api_server container found for project %q", project)
}

func Upgrade(target devstack.Target, revision string, schema Schema) error {
	if revision == "" {
		revision = "head"
	}
	return Run(target, []string{"upgrade", revision}, schema)
}
func Downgrade(target devstack.Target, revision string, schema Schema) error {
	return Run(target, []string{"downgrade", revision}, schema)
}
func Current(target devstack.Target, schema Schema) error {
	return Run(target, []string{"current"}, schema)
}
func History(target devstack.Target, schema Schema, verbose bool) error {
	args := []string{"history"}
	if verbose {
		args = append(args, "-v")
	}
	return Run(target, args, schema)
}
