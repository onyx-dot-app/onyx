package cmd

import (
	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

// LogsOptions holds options for the logs command
type LogsOptions struct {
	Follow bool
	Tail   string
}

// NewLogsCommand creates a new logs command for viewing docker container logs
func NewLogsCommand() *cobra.Command {
	opts := &LogsOptions{}

	cmd := &cobra.Command{
		Use:   "logs [profile]",
		Short: "View logs from Onyx docker containers",
		Long: `View logs from running Onyx docker containers.

Available profiles:
  dev          Use dev configuration (exposes service ports for development)
  multitenant  Use multitenant configuration

Examples:
  # View logs (follow mode)
  ods logs

  # View logs for dev profile
  ods logs dev

  # View last 100 lines and follow
  ods logs --tail 100

  # View logs without following
  ods logs --follow=false`,
		Args:      cobra.MaximumNArgs(1),
		ValidArgs: validProfiles,
		Run: func(cmd *cobra.Command, args []string) {
			profile := ""
			if len(args) > 0 {
				profile = args[0]
			}
			runComposeLogs(profile, opts)
		},
	}

	cmd.Flags().BoolVar(&opts.Follow, "follow", true, "Follow log output")
	cmd.Flags().StringVar(&opts.Tail, "tail", "", "Number of lines to show from the end of the logs (e.g. 100)")

	return cmd
}

func runComposeLogs(profile string, opts *LogsOptions) {
	validateProfile(profile)

	args := baseArgs(profile)
	args = append(args, "logs")
	if opts.Follow {
		args = append(args, "-f")
	}
	if opts.Tail != "" {
		args = append(args, "--tail", opts.Tail)
	}

	log.Infof("Viewing logs with %s configuration...", profileLabel(profile))
	execDockerCompose(args, nil)
}
