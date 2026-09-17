package dockercmd

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"os/user"
	"runtime"
	"strings"
	"time"
)

// Linux provisioning (also used inside WSL). Mirrors install.sh: Docker
// Engine via get.docker.com (package manager on Amazon Linux), the compose
// plugin from the docker/compose releases, and docker group membership with
// the sudo fallback covering the current run.

const composePluginDir = "/usr/local/lib/docker/cli-plugins"

// InstallDockerLinux installs Docker Engine and starts/enables the service.
// sudo may prompt for a password, so command output streams to progress.
func InstallDockerLinux(ctx context.Context, r Runner, progress io.Writer) error {
	if distroID() == "amzn" {
		pkg := "yum"
		if _, err := exec.LookPath("dnf"); err == nil {
			pkg = "dnf"
		}
		fmt.Fprintf(progress, "Detected Amazon Linux — installing Docker via %s...\n", pkg)
		if _, err := r.Run(ctx, Command{Name: "sudo", Args: []string{pkg, "install", "-y", "docker"}, Stdout: progress, Stderr: progress}); err != nil {
			return fmt.Errorf("package manager install failed: %w", err)
		}
	} else {
		fmt.Fprintln(progress, "Installing Docker via get.docker.com...")
		script, err := os.CreateTemp("", "get-docker-*.sh")
		if err != nil {
			return err
		}
		defer func() { _ = os.Remove(script.Name()) }()
		if err := downloadTo(ctx, "https://get.docker.com", script); err != nil {
			return fmt.Errorf("failed to download the Docker install script: %w", err)
		}
		if _, err := r.Run(ctx, Command{Name: "sudo", Args: []string{"sh", script.Name()}, Stdout: progress, Stderr: progress}); err != nil {
			return fmt.Errorf("the Docker install script failed: %w", err)
		}
	}

	// Best effort, matching install.sh: systemd hosts start via systemctl,
	// others via service; enable so Docker survives reboots.
	if _, err := r.Run(ctx, Command{Name: "sudo", Args: []string{"systemctl", "start", "docker"}}); err != nil {
		_, _ = r.Run(ctx, Command{Name: "sudo", Args: []string{"service", "docker", "start"}})
	}
	_, _ = r.Run(ctx, Command{Name: "sudo", Args: []string{"systemctl", "enable", "docker"}})
	return nil
}

// InstallComposePluginLinux downloads the docker compose plugin into the
// system-wide CLI plugin directory.
func InstallComposePluginLinux(ctx context.Context, r Runner, progress io.Writer) error {
	arch := runtime.GOARCH
	switch arch {
	case "amd64":
		arch = "x86_64"
	case "arm64":
		arch = "aarch64"
	}
	url := "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-" + arch

	tmp, err := os.CreateTemp("", "docker-compose-*")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	fmt.Fprintln(progress, "Downloading the Docker Compose plugin...")
	if err := downloadTo(ctx, url, tmp); err != nil {
		return fmt.Errorf("failed to download the Docker Compose plugin: %w", err)
	}

	if _, err := r.Run(ctx, Command{Name: "sudo", Args: []string{"mkdir", "-p", composePluginDir}, Stdout: progress, Stderr: progress}); err != nil {
		return err
	}
	dest := composePluginDir + "/docker-compose"
	if _, err := r.Run(ctx, Command{Name: "sudo", Args: []string{"mv", tmp.Name(), dest}, Stdout: progress, Stderr: progress}); err != nil {
		return err
	}
	if _, err := r.Run(ctx, Command{Name: "sudo", Args: []string{"chmod", "+x", dest}, Stdout: progress, Stderr: progress}); err != nil {
		return err
	}
	return nil
}

// EnsureDockerGroup adds the current user to the docker group when they are
// not already a member (effective on next login; the sudo fallback covers
// the current run). Callers invoke this only after `docker info` failed
// without sudo, mirroring install.sh.
func EnsureDockerGroup(ctx context.Context, r Runner, progress io.Writer) error {
	u, err := user.Current()
	if err != nil {
		return err
	}
	res, err := r.Run(ctx, Command{Name: "id", Args: []string{"-nG", u.Username}})
	if err == nil {
		for _, g := range strings.Fields(res.Stdout) {
			if g == "docker" {
				return nil
			}
		}
	}
	if _, err := r.Run(ctx, Command{Name: "getent", Args: []string{"group", "docker"}}); err != nil {
		if _, err := r.Run(ctx, Command{Name: "sudo", Args: []string{"groupadd", "docker"}, Stdout: progress, Stderr: progress}); err != nil {
			return err
		}
	}
	fmt.Fprintf(progress, "Adding %s to the docker group (effective on next login)...\n", u.Username)
	if _, err := r.Run(ctx, Command{Name: "sudo", Args: []string{"usermod", "-aG", "docker", u.Username}, Stdout: progress, Stderr: progress}); err != nil {
		return err
	}
	return nil
}

func distroID() string {
	data, err := os.ReadFile("/etc/os-release")
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(data), "\n") {
		if id, ok := strings.CutPrefix(line, "ID="); ok {
			return strings.Trim(id, `"`)
		}
	}
	return ""
}

// downloadTo streams url into f and closes it.
func downloadTo(ctx context.Context, url string, f *os.File) error {
	defer func() { _ = f.Close() }()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	client := &http.Client{Timeout: 5 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d from %s", resp.StatusCode, url)
	}
	if _, err := io.Copy(f, resp.Body); err != nil {
		return err
	}
	return f.Sync()
}
