package cmd

import (
	"fmt"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/docker"
)

var (
	Version string
	Commit  string
)

// RootOptions holds options for the root command.
type RootOptions struct {
	Debug   bool
	Project string
}

// NewRootCommand creates the root command.
func NewRootCommand() *cobra.Command {
	opts := &RootOptions{}

	cmd := &cobra.Command{
		Use:   "ods ",
		Short: "Developer utilities for working on onyx.app",
		Run:   rootCmd,
		PersistentPreRun: func(cmd *cobra.Command, args []string) {
			if opts.Debug {
				log.SetLevel(log.DebugLevel)
			} else {
				log.SetLevel(log.InfoLevel)
			}
			log.SetFormatter(&log.TextFormatter{
				DisableTimestamp: true,
			})
			docker.SetProjectFlags(opts.Project)
		},
		Version: fmt.Sprintf("%s\ncommit %s", Version, Commit),
	}

	cmd.PersistentFlags().BoolVar(&opts.Debug, "debug", false, "run in debug mode")
	cmd.PersistentFlags().StringVar(&opts.Project, "project", "", "Docker Compose project name (default: basename of git root)")

	// Add subcommands
	cmd.AddCommand(NewBackendCommand())
	cmd.AddCommand(NewCheckLazyImportsCommand())
	cmd.AddCommand(NewCherryPickCommand())
	cmd.AddCommand(NewDBCommand())
	cmd.AddCommand(NewDeployCommand())
	cmd.AddCommand(NewOpenAPICommand())
	cmd.AddCommand(NewComposeCommand())
	cmd.AddCommand(NewEnvCommand())
	cmd.AddCommand(NewLogsCommand())
	cmd.AddCommand(NewPullCommand())
	cmd.AddCommand(NewRunCICommand())
	cmd.AddCommand(NewScreenshotDiffCommand())
	cmd.AddCommand(NewDesktopCommand())
	cmd.AddCommand(NewDevCommand())
	cmd.AddCommand(NewWebCommand())
	cmd.AddCommand(NewLatestStableTagCommand())
	cmd.AddCommand(NewWhoisCommand())
	cmd.AddCommand(NewTraceCommand())
	cmd.AddCommand(NewInstallSkillCommand())
	cmd.AddCommand(NewReleaseCommand())

	return cmd
}

func rootCmd(cmd *cobra.Command, args []string) {
	_ = cmd.Help()
}
