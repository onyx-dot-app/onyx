package dockercmd

import (
	"context"
	"os"
	"os/exec"
	"regexp"
	"runtime"
	"strings"
)

var versionPattern = regexp.MustCompile(`\d+\.\d+\.\d+`)

// Docker invokes the docker CLI, transparently prefixing sudo when the
// current user cannot reach the daemon directly (Linux only; mirrors
// install.sh's DOCKER_SUDO fallback so a just-added docker group membership
// doesn't force a re-login mid-install).
type Docker struct {
	Runner Runner
	sudo   bool
}

func NewDocker(r Runner) *Docker {
	return &Docker{Runner: r}
}

// Installed reports whether the docker CLI is on PATH.
func Installed() bool {
	_, err := exec.LookPath("docker")
	return err == nil
}

// IsWSL reports whether this process runs inside Windows Subsystem for Linux.
func IsWSL() bool {
	if os.Getenv("WSL_DISTRO_NAME") != "" {
		return true
	}
	data, err := os.ReadFile("/proc/version")
	return err == nil && strings.Contains(strings.ToLower(string(data)), "microsoft")
}

// UsingSudo reports whether docker invocations are being prefixed with sudo.
func (d *Docker) UsingSudo() bool { return d.sudo }

// RefreshSudo re-evaluates whether docker commands need a sudo prefix: only
// on Linux/WSL, only for non-root users, and only when `docker info` fails
// without it.
func (d *Docker) RefreshSudo(ctx context.Context) {
	d.sudo = false
	if !Installed() || os.Geteuid() == 0 {
		return
	}
	if runtime.GOOS != "linux" && !IsWSL() {
		return
	}
	if _, err := d.Runner.Run(ctx, Command{Name: "docker", Args: []string{"info"}}); err == nil {
		return
	}
	d.sudo = true
}

// Command builds a docker invocation. Without sudo, env entries ride the
// process environment; with sudo they become argv to `env` (positional args
// survive sudo's env_reset, inherited environment does not).
func (d *Docker) Command(env map[string]string, args ...string) Command {
	return d.commandFor("docker", env, args...)
}

// DaemonRunning reports whether the docker daemon answers `docker info`.
func (d *Docker) DaemonRunning(ctx context.Context) bool {
	_, err := d.Runner.Run(ctx, d.Command(nil, "info"))
	return err == nil
}

// Version returns the docker CLI version ("" when unparsable).
func (d *Docker) Version(ctx context.Context) string {
	res, err := d.Runner.Run(ctx, Command{Name: "docker", Args: []string{"--version"}})
	if err != nil {
		return ""
	}
	return versionPattern.FindString(res.Stdout)
}

// EnsureNetwork creates the named docker network if it doesn't exist.
func (d *Docker) EnsureNetwork(ctx context.Context, name string) (created bool, err error) {
	if _, err := d.Runner.Run(ctx, d.Command(nil, "network", "inspect", name)); err == nil {
		return false, nil
	}
	if _, err := d.Runner.Run(ctx, d.Command(nil, "network", "create", name)); err != nil {
		return false, err
	}
	return true, nil
}

// EnsureVolume creates the named docker volume if it doesn't exist.
func (d *Docker) EnsureVolume(ctx context.Context, name string) (created bool, err error) {
	if _, err := d.Runner.Run(ctx, d.Command(nil, "volume", "inspect", name)); err == nil {
		return false, nil
	}
	if _, err := d.Runner.Run(ctx, d.Command(nil, "volume", "create", name)); err != nil {
		return false, err
	}
	return true, nil
}
