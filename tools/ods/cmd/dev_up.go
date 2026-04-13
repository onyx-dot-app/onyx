package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

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
// Used by ensureRemoteUser to detect rootless Docker.
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
		// Only bare paths (starting with /) are valid socket paths.
		// Non-unix schemes (e.g. tcp://) can't be bind-mounted.
		if len(dh) > 0 && dh[0] == '/' {
			return dh
		}
		log.Warnf("DOCKER_HOST=%q is not a unix socket path; falling back to local socket detection", dh)
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

// worktreeGitMount returns a --mount flag value that makes a git worktree's
// .git reference resolve inside the container. In a worktree, .git is a file
// containing "gitdir: /path/to/main/.git/worktrees/<name>", so we need the
// main repo's .git directory to exist at the same absolute host path inside
// the container.
//
// Returns ("", false) when the workspace is not a worktree.
func worktreeGitMount(root string) (string, bool) {
	dotgit := filepath.Join(root, ".git")
	info, err := os.Lstat(dotgit)
	if err != nil || info.IsDir() {
		return "", false // regular repo or no .git
	}

	// .git is a file — parse the gitdir path.
	out, err := exec.Command("git", "-C", root, "rev-parse", "--git-common-dir").Output()
	if err != nil {
		log.Warnf("Failed to detect git common dir: %v", err)
		return "", false
	}
	commonDir := strings.TrimSpace(string(out))

	// Resolve to absolute path.
	if !filepath.IsAbs(commonDir) {
		commonDir = filepath.Join(root, commonDir)
	}
	commonDir, _ = filepath.EvalSymlinks(commonDir)

	mount := fmt.Sprintf("type=bind,source=%s,target=%s", commonDir, commonDir)
	log.Debugf("Worktree detected — mounting main .git: %s", commonDir)
	return mount, true
}

// sshAgentMount returns a --mount flag value that forwards the host's SSH agent
// socket into the container.  Returns ("", false) when SSH_AUTH_SOCK is unset or
// the socket is not accessible.
func sshAgentMount() (string, bool) {
	sock := os.Getenv("SSH_AUTH_SOCK")
	if sock == "" {
		log.Debug("SSH_AUTH_SOCK not set — skipping SSH agent forwarding")
		return "", false
	}
	if _, err := os.Stat(sock); err != nil {
		log.Debugf("SSH_AUTH_SOCK=%s not accessible: %v", sock, err)
		return "", false
	}
	mount := fmt.Sprintf("type=bind,source=%s,target=/tmp/ssh-agent.sock", sock)
	log.Debugf("Forwarding SSH agent: %s", sock)
	return mount, true
}

// ensureRemoteUser sets DEVCONTAINER_REMOTE_USER when rootless Docker is
// detected.  Container root maps to the host user in rootless mode, so running
// as root inside the container avoids the UID mismatch on new files.
// Must be called after ensureDockerSock.
func ensureRemoteUser() {
	if os.Getenv("DEVCONTAINER_REMOTE_USER") != "" {
		return
	}

	if runtime.GOOS == "linux" {
		sock := os.Getenv("DOCKER_SOCK")
		xdg := os.Getenv("XDG_RUNTIME_DIR")
		// Heuristic: rootless Docker on Linux typically places its socket
		// under $XDG_RUNTIME_DIR. If DOCKER_SOCK was set to a custom path
		// outside XDG_RUNTIME_DIR, set DEVCONTAINER_REMOTE_USER=root manually.
		if xdg != "" && strings.HasPrefix(sock, xdg) {
			log.Debug("Rootless Docker detected — setting DEVCONTAINER_REMOTE_USER=root")
			if err := os.Setenv("DEVCONTAINER_REMOTE_USER", "root"); err != nil {
				log.Warnf("Failed to set DEVCONTAINER_REMOTE_USER: %v", err)
			}
		}
	}
}

// runDevcontainer executes "devcontainer <action> --workspace-folder <root> [extraArgs...]".
func runDevcontainer(action string, extraArgs []string) {
	checkDevcontainerCLI()
	ensureDockerSock()
	ensureRemoteUser()

	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}

	args := []string{action, "--workspace-folder", root}
	if mount, ok := worktreeGitMount(root); ok {
		args = append(args, "--mount", mount)
	}
	if mount, ok := sshAgentMount(); ok {
		args = append(args, "--mount", mount)
	}
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
