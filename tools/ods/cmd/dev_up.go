package cmd

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

func newDevUpCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "up",
		Short: "Start the devcontainer",
		Long: `Start the devcontainer, pulling the image if needed.

Examples:
  ods dev up`,
		Run: func(cmd *cobra.Command, args []string) {
			runDevcontainer("up", nil)
		},
	}

	return cmd
}

// devcontainerImage reads the image field from .devcontainer/devcontainer.json.
func devcontainerImage() string {
	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}

	data, err := os.ReadFile(filepath.Join(root, ".devcontainer", "devcontainer.json"))
	if err != nil {
		log.Fatalf("Failed to read devcontainer.json: %v", err)
	}

	var cfg struct {
		Image string `json:"image"`
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		log.Fatalf("Failed to parse devcontainer.json: %v", err)
	}
	if cfg.Image == "" {
		log.Fatal("No image field in devcontainer.json")
	}
	return cfg.Image
}

// checkDevcontainerCLI ensures the devcontainer CLI is installed.
func checkDevcontainerCLI() {
	if _, err := exec.LookPath("devcontainer"); err != nil {
		log.Fatal("devcontainer CLI is not installed. Install it with: npm install -g @devcontainers/cli")
	}
}

// ensureDockerSock sets the DOCKER_SOCK environment variable if not already set.
// devcontainer.json references ${localEnv:DOCKER_SOCK} for the socket mount.
func ensureDockerSock() {
	if os.Getenv("DOCKER_SOCK") != "" {
		return
	}

	sock := detectDockerSock()
	if err := os.Setenv("DOCKER_SOCK", sock); err != nil {
		log.Fatalf("Failed to set DOCKER_SOCK: %v", err)
	}
}

// detectDockerSock returns the path to the Docker socket on the host.
func detectDockerSock() string {
	// Prefer explicit DOCKER_HOST (strip unix:// prefix if present).
	if dh := os.Getenv("DOCKER_HOST"); dh != "" {
		const prefix = "unix://"
		if len(dh) > len(prefix) && dh[:len(prefix)] == prefix {
			return dh[len(prefix):]
		}
		return dh
	}

	// Linux rootless Docker: $XDG_RUNTIME_DIR/docker.sock
	if runtime.GOOS == "linux" {
		if xdg := os.Getenv("XDG_RUNTIME_DIR"); xdg != "" {
			sock := filepath.Join(xdg, "docker.sock")
			if _, err := os.Stat(sock); err == nil {
				return sock
			}
		}
	}

	// macOS Docker Desktop: ~/.docker/run/docker.sock
	if runtime.GOOS == "darwin" {
		if home, err := os.UserHomeDir(); err == nil {
			sock := filepath.Join(home, ".docker", "run", "docker.sock")
			if _, err := os.Stat(sock); err == nil {
				return sock
			}
		}
	}

	// Fallback: standard socket path (Linux with standard Docker, macOS symlink)
	return "/var/run/docker.sock"
}

// runDevcontainer executes "devcontainer <action> --workspace-folder <root> [extraArgs...]".
func runDevcontainer(action string, extraArgs []string) {
	checkDevcontainerCLI()
	ensureDockerSock()

	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}

	args := []string{action, "--workspace-folder", root}
	args = append(args, extraArgs...)

	log.Debugf("Running: devcontainer %v", args)

	c := exec.Command("devcontainer", args...)
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	c.Stdin = os.Stdin

	if err := c.Run(); err != nil {
		log.Fatalf("devcontainer %s failed: %v", action, err)
	}
}
