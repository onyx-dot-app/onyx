package docker

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// Known container names for PostgreSQL in order of preference
var postgresContainerNames = []string{
	"onyx_postgres",                  // From restart_containers.sh
	"onyx-stack-relational_db-1",     // Docker compose with project name
	"docker_compose-relational_db-1", // Legacy docker compose naming
	"relational_db",                  // Service name only
}

// FindPostgresContainer finds a running PostgreSQL container.
// It tries known container names first, then falls back to searching.
func FindPostgresContainer() (string, error) {
	// Try known names first
	for _, name := range postgresContainerNames {
		if isContainerRunning(name) {
			return name, nil
		}
	}

	// Fall back to searching for any postgres container
	cmd := exec.Command("docker", "ps", "--format", "{{.Names}}", "--filter", "ancestor=postgres")
	output, err := cmd.Output()
	if err == nil {
		containers := strings.Split(strings.TrimSpace(string(output)), "\n")
		for _, container := range containers {
			if container != "" {
				return container, nil
			}
		}
	}

	return "", fmt.Errorf("no running PostgreSQL container found. Try one of: %s", strings.Join(postgresContainerNames, ", "))
}

// isContainerRunning checks if a container with the given name is running.
func isContainerRunning(name string) bool {
	cmd := exec.Command("docker", "inspect", "-f", "{{.State.Running}}", name)
	output, err := cmd.Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(output)) == "true"
}

// Exec runs a command inside a Docker container.
func Exec(container string, args ...string) error {
	dockerArgs := append([]string{"exec", "-i", container}, args...)
	cmd := exec.Command("docker", dockerArgs...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	return cmd.Run()
}

// ExecWithEnv runs a command inside a Docker container with environment variables.
func ExecWithEnv(container string, env map[string]string, args ...string) error {
	dockerArgs := []string{"exec", "-i"}
	for k, v := range env {
		dockerArgs = append(dockerArgs, "-e", fmt.Sprintf("%s=%s", k, v))
	}
	dockerArgs = append(dockerArgs, container)
	dockerArgs = append(dockerArgs, args...)

	cmd := exec.Command("docker", dockerArgs...)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	return cmd.Run()
}

// ExecOutput runs a command inside a Docker container and returns its output.
func ExecOutput(container string, args ...string) (string, error) {
	dockerArgs := append([]string{"exec", "-i", container}, args...)
	cmd := exec.Command("docker", dockerArgs...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	if err != nil {
		return "", fmt.Errorf("%w: %s", err, stderr.String())
	}
	return stdout.String(), nil
}

// CopyFromContainer copies a file from a container to the host.
func CopyFromContainer(container, src, dst string) error {
	cmd := exec.Command("docker", "cp", fmt.Sprintf("%s:%s", container, src), dst)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

// CopyToContainer copies a file from the host to a container.
func CopyToContainer(container, src, dst string) error {
	cmd := exec.Command("docker", "cp", src, fmt.Sprintf("%s:%s", container, dst))
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}
