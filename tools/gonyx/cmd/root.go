package cmd

import (
	"fmt"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
)

var (
	Version string
	Commit  string
)

// RootOptions holds options for the root command
type RootOptions struct {
	Debug bool
}

// NewRootCommand creates the root command
func NewRootCommand() *cobra.Command {
	opts := &RootOptions{}

	cmd := &cobra.Command{
		Use:   "gonyx ",
		Short: "Developer utilities for working on onyx.app",
		Run:   rootCmd,
		PersistentPreRun: func(cmd *cobra.Command, args []string) {
			if opts.Debug {
				log.SetLevel(log.DebugLevel)
			} else {
				log.SetLevel(log.InfoLevel)
			}
		},
		Version: fmt.Sprintf("%s\ncommit %s", Version, Commit),
	}

	cmd.PersistentFlags().BoolVar(&opts.Debug, "debug", false, "run in debug mode")

	// Add subcommands
	cmd.AddCommand(NewCherryPickCommand())

	return cmd
}

func rootCmd(cmd *cobra.Command, args []string) {
	log.Debug("Debug log in rootCmd")
}
