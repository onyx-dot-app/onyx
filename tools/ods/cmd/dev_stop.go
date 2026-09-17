package cmd

import (
	"os/exec"
	"strings"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
)

func newDevStopCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "stop",
		Short: "Stop the running devcontainer",
		Long: `Stop the running devcontainer.

Examples:
  ods dev stop`,
		Run: func(cmd *cobra.Command, args []string) {
			if err := runDevStop(); err != nil {
				log.Fatal(err)
			}
		},
	}

	return cmd
}

func runDevStop() error {
	root, err := paths.GitRoot()
	if err != nil {
		return fatalErrorf("Failed to find git root: %w", err)
	}

	// Find the container by the devcontainer label
	out, err := exec.Command(
		"docker", "ps", "-q",
		"--filter", "label=devcontainer.local_folder="+root,
	).Output()
	if err != nil {
		return fatalErrorf("Failed to find devcontainer: %w", err)
	}

	containerID := strings.TrimSpace(string(out))
	if containerID == "" {
		log.Info("No running devcontainer found")
		return nil
	}

	log.Infof("Stopping devcontainer %s...", containerID)
	c := exec.Command("docker", "stop", containerID)
	if err := c.Run(); err != nil {
		return fatalErrorf("Failed to stop devcontainer: %w", err)
	}
	log.Info("Devcontainer stopped")
	return nil
}
