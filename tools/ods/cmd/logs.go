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
		Use:   "logs [service...]",
		Short: "View logs from Onyx docker containers",
		Long: `View logs from running Onyx docker containers.

All arguments are treated as service names to filter logs.
If no services are specified, logs from all services are shown.

Examples:
  # View logs from all services (follow mode)
  ods logs

  # View logs for a specific service
  ods logs api_server

  # View logs for multiple services
  ods logs api_server background

  # View last 100 lines and follow
  ods logs --tail 100 api_server

  # View logs without following
  ods logs --follow=false`,
		Args: cobra.ArbitraryArgs,
		ValidArgsFunction: func(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
			return runningServiceNames(), cobra.ShellCompDirectiveNoFileComp
		},
		Run: func(cmd *cobra.Command, args []string) {
			runComposeLogs(args, opts)
		},
	}

	cmd.Flags().BoolVar(&opts.Follow, "follow", true, "Follow log output")
	cmd.Flags().StringVar(&opts.Tail, "tail", "", "Number of lines to show from the end of the logs (e.g. 100)")

	return cmd
}

func runComposeLogs(services []string, opts *LogsOptions) {
	args := baseArgs("")
	args = append(args, "logs")
	if opts.Follow {
		args = append(args, "-f")
	}
	if opts.Tail != "" {
		args = append(args, "--tail", opts.Tail)
	}
	args = append(args, services...)

	log.Info("Viewing container logs...")
	execDockerCompose(args, nil)
}
