package docker

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
)

// legacyPostgresContainerNames are fallback names tried after the
// project-specific name.
var legacyPostgresContainerNames = []string{
	"onyx_postgres",                  // From restart_containers.sh
	"onyx-relational_db-1",           // Docker compose default project name
	"onyx-stack-relational_db-1",     // Docker compose with stack project name
	"docker_compose-relational_db-1", // Legacy docker compose naming
	"relational_db",                  // Service name only
}

// FindPostgresContainer finds a running PostgreSQL container. It tries the
// project-specific name first, then legacy names, then falls back to searching
// by image.
func FindPostgresContainer(projectName string) (string, error) {
	projectContainer := fmt.Sprintf("%s-relational_db-1", projectName)
	if isContainerRunning(projectContainer) {
		return projectContainer, nil
	}

	for _, name := range legacyPostgresContainerNames {
		if isContainerRunning(name) {
			return name, nil
		}
	}

	// Fall back to searching for any postgres container by image name. Try
	// multiple filters since the image name may vary (postgres,
	// postgres:15.2-alpine, etc.)
	cmd := exec.Command("docker", "ps", "--format", "{{.Names}}\t{{.Image}}")
	output, err := cmd.Output()
	if err == nil {
		lines := strings.Split(strings.TrimSpace(string(output)), "\n")
		for _, line := range lines {
			parts := strings.Split(line, "\t")
			if len(parts) >= 2 {
				name, image := parts[0], parts[1]
				if strings.Contains(image, "postgres") {
					return name, nil
				}
			}
		}
	}

	return "", fmt.Errorf("no running PostgreSQL container found for project %q; try: ods compose dev", projectName)
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

// ExecWithEnv runs a command inside a Docker container with environment
// variables.
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

// GetContainerIP returns the IP address of a container. It returns the first
// available network IP if the container has multiple networks.
func GetContainerIP(container string) (string, error) {
	// Get IPs from the container's network settings (space-separated if
	// multiple).
	cmd := exec.Command("docker", "inspect", "-f",
		"{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", container)
	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("failed to get container IP: %w", err)
	}

	// Take the first IP if there are multiple
	ips := strings.Fields(string(output))
	if len(ips) == 0 {
		return "", fmt.Errorf("container %s has no IP address", container)
	}

	return ips[0], nil
}

// GetHostPort runs "docker port <container> <containerPort>" and returns the
// host-side port number. Returns an error if the container is not running or the
// port is not mapped.
func GetHostPort(container string, containerPort int) (int, error) {
	cmd := exec.Command("docker", "port", container, strconv.Itoa(containerPort))
	out, err := cmd.Output()
	if err != nil {
		return 0, fmt.Errorf("docker port %s %d: %w", container, containerPort, err)
	}
	line := strings.SplitN(strings.TrimSpace(string(out)), "\n", 2)[0]
	if line == "" {
		return 0, fmt.Errorf("port %d not exposed on %s", containerPort, container)
	}
	parts := strings.Split(line, ":")
	if len(parts) < 2 {
		return 0, fmt.Errorf("unexpected docker port output: %s", line)
	}
	port, err := strconv.Atoi(parts[len(parts)-1])
	if err != nil {
		return 0, fmt.Errorf("invalid port number in docker port output: %s", line)
	}
	return port, nil
}

// IsPortExposed checks if a container port is exposed to the host.
func IsPortExposed(container string, containerPort string) bool {
	port, _ := strconv.Atoi(containerPort)
	_, err := GetHostPort(container, port)
	return err == nil
}
