package alembic

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"

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

	// Pass through POSTGRES_* environment variables
	cmd.Env = buildAlembicEnv()

	return cmd.Run()
}

// buildAlembicEnv builds the environment for running alembic.
// It inherits the current environment and ensures POSTGRES_* variables are set.
// If POSTGRES_HOST is not explicitly set, it attempts to detect the PostgreSQL
// container IP address automatically.
func buildAlembicEnv() []string {
	env := os.Environ()

	// Get postgres config (which reads from env with defaults)
	config := postgres.NewConfigFromEnv()

	// If POSTGRES_HOST is not explicitly set, try to detect container IP
	host := config.Host
	if os.Getenv("POSTGRES_HOST") == "" {
		if containerIP := detectPostgresContainerIP(); containerIP != "" {
			host = containerIP
			log.Debugf("Auto-detected PostgreSQL container IP: %s", containerIP)
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

// detectPostgresContainerIP attempts to find a running PostgreSQL container
// and return its IP address.
func detectPostgresContainerIP() string {
	container, err := docker.FindPostgresContainer()
	if err != nil {
		log.Debugf("Could not find PostgreSQL container: %v", err)
		return ""
	}

	ip, err := docker.GetContainerIP(container)
	if err != nil {
		log.Debugf("Could not get container IP for %s: %v", container, err)
		return ""
	}

	log.Infof("Using PostgreSQL container: %s (%s)", container, ip)
	return ip
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
