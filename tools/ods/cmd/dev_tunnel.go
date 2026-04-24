package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

func newDevTunnelCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "tunnel <port|host:container>",
		Short: "Tunnel a devcontainer port to the host",
		Long: `Forward a TCP port from the running devcontainer to the host.

Runs socat on the host and forwards each accepted connection into the
devcontainer via ` + "`docker exec socat`" + `, which connects to
127.0.0.1:<container-port> inside the container.  Routing via loopback
sidesteps the devcontainer's default-deny inbound firewall.

Runs in the foreground — Ctrl-C tears the tunnel down.

Examples:
  ods dev tunnel 8080        # host 8080 -> devcontainer 8080
  ods dev tunnel 9000:8080   # host 9000 -> devcontainer 8080`,
		Args: cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			hostPort, containerPort, err := parseTunnelPorts(args[0])
			if err != nil {
				log.Fatalf("Invalid port spec %q: %v", args[0], err)
			}
			runDevTunnel(hostPort, containerPort)
		},
	}

	return cmd
}

func parseTunnelPorts(spec string) (int, int, error) {
	parts := strings.Split(spec, ":")
	switch len(parts) {
	case 1:
		p, err := parsePort(parts[0])
		if err != nil {
			return 0, 0, err
		}
		return p, p, nil
	case 2:
		host, err := parsePort(parts[0])
		if err != nil {
			return 0, 0, fmt.Errorf("host port: %w", err)
		}
		container, err := parsePort(parts[1])
		if err != nil {
			return 0, 0, fmt.Errorf("container port: %w", err)
		}
		return host, container, nil
	default:
		return 0, 0, fmt.Errorf("expected <port> or <host>:<container>")
	}
}

func parsePort(s string) (int, error) {
	p, err := strconv.Atoi(s)
	if err != nil {
		return 0, fmt.Errorf("not a number: %q", s)
	}
	if p < 1 || p > 65535 {
		return 0, fmt.Errorf("out of range: %d", p)
	}
	return p, nil
}

func runDevTunnel(hostPort, containerPort int) {
	root, err := paths.GitRoot()
	if err != nil {
		log.Fatalf("Failed to find git root: %v", err)
	}

	out, err := exec.Command(
		"docker", "ps", "-q",
		"--filter", "label=devcontainer.local_folder="+root,
	).Output()
	if err != nil {
		log.Fatalf("Failed to find devcontainer: %v", err)
	}
	containerID := strings.TrimSpace(string(out))
	if containerID == "" {
		log.Fatal("No running devcontainer found — run `ods dev up` first")
	}

	log.Infof("Tunneling host :%d -> devcontainer :%d (Ctrl-C to stop)", hostPort, containerPort)

	socatArgs := []string{
		fmt.Sprintf("TCP-LISTEN:%d,fork,reuseaddr", hostPort),
		fmt.Sprintf("SYSTEM:docker exec -i %s socat - TCP\\:127.0.0.1\\:%d", containerID, containerPort),
	}

	log.Debugf("Running: socat %v", socatArgs)

	c := exec.Command("socat", socatArgs...)
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr

	if err := c.Run(); err != nil {
		log.Fatalf("socat failed: %v", err)
	}
}
