package cmd

import (
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

// PullOptions holds options for the pull command
type PullOptions struct {
	Tag string
}

// NewPullCommand creates a new pull command for pulling docker images
func NewPullCommand() *cobra.Command {
	opts := &PullOptions{}

	cmd := &cobra.Command{
		Use:   "pull [profile]",
		Short: "Pull images for Onyx docker containers",
		Long: `Pull the latest images for Onyx docker containers.

Available profiles:
  dev          Use dev configuration (exposes service ports for development)
  multitenant  Use multitenant configuration

Examples:
  # Pull images with default configuration
  ods pull

  # Pull images for dev profile
  ods pull dev

  # Pull images with a specific tag
  ods pull --tag edge`,
		Args:      cobra.MaximumNArgs(1),
		ValidArgs: validProfiles,
		Run: func(cmd *cobra.Command, args []string) {
			profile := ""
			if len(args) > 0 {
				profile = args[0]
			}
			runComposePull(profile, opts)
		},
	}

	cmd.Flags().StringVar(&opts.Tag, "tag", "", "Set the IMAGE_TAG for docker compose (e.g. edge, v2.10.4)")

	return cmd
}

func runComposePull(profile string, opts *PullOptions) {
	validateProfile(profile)

	args := baseArgs(profile)
	args = append(args, "pull")

	log.Infof("Pulling images with %s configuration...", profileLabel(profile))
	execDockerCompose(args, envForTag(opts.Tag))
	log.Info("Images pulled successfully")
}
