package alembic

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	log "github.com/sirupsen/logrus"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/postgres"
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
// It will try to run alembic locally if the database is accessible,
// otherwise it will attempt to run via docker exec on a container
// that has alembic installed (e.g., api_server).
func Run(args []string, schema Schema) error {
	// Check if we need to run via docker exec
	if shouldUseDockerExec() {
		return runViaDockerExec(args, schema)
	}

	return runLocally(args, schema)
}

// shouldUseDockerExec determines if we should run alembic via docker exec.
// Returns true if POSTGRES_HOST is not set and the port isn't exposed.
func shouldUseDockerExec() bool {
	// If POSTGRES_HOST is explicitly set, respect it
	if os.Getenv("POSTGRES_HOST") != "" {
		return false
	}

	// Check if we can find a postgres container with exposed port
	container, err := docker.FindPostgresContainer()
	if err != nil {
		return false
	}

	return !docker.IsPortExposed(container, "5432")
}

// runLocally runs alembic on the local machine.
func runLocally(args []string, schema Schema) error {
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

	// Pass through POSTGRES_* environment variables
	cmd.Env = buildAlembicEnv()

	return cmd.Run()
}

// runViaDockerExec runs alembic inside a Docker container that has network access.
func runViaDockerExec(args []string, schema Schema) error {
	// Find a container with alembic installed (api_server)
	container, err := findAlembicContainer()
	if err != nil {
		// No suitable container found, give helpful error
		log.Errorf("PostgreSQL port 5432 is not exposed and no container with alembic found.")
		log.Errorf("")
		log.Errorf("Either expose the port by restarting with the dev compose file:")
		log.Errorf("  docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d")
		log.Errorf("")
		log.Errorf("Or start the api_server container:")
		log.Errorf("  docker compose up -d api_server")
		return fmt.Errorf("cannot connect to database")
	}

	log.Infof("Running alembic via docker exec on container: %s", container)

	// Build the alembic command
	var alembicArgs []string
	if schema == SchemaPrivate {
		alembicArgs = append(alembicArgs, "-n", "schema_private")
	}
	alembicArgs = append(alembicArgs, args...)

	// Run alembic inside the container
	// The container should have the correct env vars and network access
	dockerArgs := []string{"exec", "-i", container, "alembic"}
	dockerArgs = append(dockerArgs, alembicArgs...)

	cmd := exec.Command("docker", dockerArgs...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin

	return cmd.Run()
}

// alembicContainerNames lists containers that typically have alembic installed.
var alembicContainerNames = []string{
	"onyx-api_server-1",
	"onyx-stack-api_server-1",
	"api_server",
}

// buildAlembicEnv builds the environment for running alembic.
// It inherits the current environment and ensures POSTGRES_* variables are set.
// If POSTGRES_HOST is not explicitly set, it attempts to detect the PostgreSQL
// container IP address automatically.
func buildAlembicEnv() []string {
	env := os.Environ()

	// Get postgres config (which reads from env with defaults)
	config := postgres.NewConfigFromEnv()

	// If POSTGRES_HOST is not explicitly set, try to detect the host
	host := config.Host
	if os.Getenv("POSTGRES_HOST") == "" {
		if detectedHost := detectPostgresHost(); detectedHost != "" {
			host = detectedHost
		}
	}

	// Ensure POSTGRES_* variables are set (use existing or defaults)
	envVars := map[string]string{
		"POSTGRES_HOST":     host,
		"POSTGRES_PORT":     config.Port,
		"POSTGRES_USER":     config.User,
		"POSTGRES_PASSWORD": config.Password,
		"POSTGRES_DB":       config.Database,
	}

	// Only add if not already set in environment (except HOST which we may have detected)
	for key, value := range envVars {
		if key == "POSTGRES_HOST" || os.Getenv(key) == "" {
			env = append(env, fmt.Sprintf("%s=%s", key, value))
		}
	}

	return env
}

// findAlembicContainer finds a running container that has alembic installed.
func findAlembicContainer() (string, error) {
	for _, name := range alembicContainerNames {
		if isContainerRunning(name) {
			return name, nil
		}
	}
	return "", fmt.Errorf("no container with alembic found")
}

// isContainerRunning checks if a container is running.
func isContainerRunning(name string) bool {
	cmd := exec.Command("docker", "inspect", "-f", "{{.State.Running}}", name)
	output, err := cmd.Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(output)) == "true"
}

// detectPostgresHost attempts to find a running PostgreSQL container
// and return the host to connect to (for local execution).
func detectPostgresHost() string {
	container, err := docker.FindPostgresContainer()
	if err != nil {
		log.Debugf("Could not find PostgreSQL container: %v", err)
		return ""
	}

	// Check if port 5432 is exposed to the host
	if docker.IsPortExposed(container, "5432") {
		log.Infof("Using PostgreSQL container: %s (localhost:5432)", container)
		return "localhost"
	}

	// Port not exposed - this shouldn't happen if shouldUseDockerExec() works correctly
	return ""
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
