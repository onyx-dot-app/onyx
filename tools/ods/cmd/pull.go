package cmd

import (
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/log"
)

// PullOptions holds options for the pull command.
type PullOptions struct {
	Tag string
}

// NewPullCommand creates a new pull command for pulling docker images
func NewPullCommand() *cobra.Command {
	opts := &PullOptions{}

	cmd := &cobra.Command{
		Use:   "pull",
		Short: "Pull images for Onyx docker containers",
		Long: `Pull the latest images for Onyx docker containers.

Examples:
  # Pull images
  ods pull

  # Pull images with a specific tag
  ods pull --tag edge`,
		Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, args []string) {
			runComposePull(opts)
		},
	}

	cmd.Flags().StringVar(&opts.Tag, "tag", "", "Set the IMAGE_TAG for docker compose (e.g. edge, v2.10.4)")

	return cmd
}

func runComposePull(opts *PullOptions) {
	args := baseArgs("")
	args = append(args, "pull")

	log.Info("Pulling images...")
	execDockerCompose(args, envForTag(opts.Tag))
	log.Info("Images pulled successfully")
}
