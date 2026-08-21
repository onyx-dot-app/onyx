package cmd

import (
	"os"
	"os/exec"

	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/log"
)

func newDevRebuildCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "rebuild",
		Short: "Pull the latest devcontainer image and recreate",
		Long: `Pull the latest devcontainer image and recreate the container.

Use after the published image has been updated or after changing devcontainer.json.

Examples:
  ods dev rebuild`,
		Run: func(cmd *cobra.Command, args []string) {
			runDevRebuild()
		},
	}

	return cmd
}

func runDevRebuild() {
	image := devcontainerImage()

	log.Infof("Pulling %s...", image)
	pull := exec.Command("docker", "pull", image)
	pull.Stdout = os.Stdout
	pull.Stderr = os.Stderr
	if err := pull.Run(); err != nil {
		log.Warnf("Failed to pull image (continuing with local copy): %v", err)
	}

	runDevcontainer("up", []string{"--remove-existing-container"})
}
