// Package cmd implements Cobra CLI commands for the Onyx CLI.
package cmd

import "github.com/spf13/cobra"

// Version and Commit are set via ldflags at build time.
var (
	Version string
	Commit  string
)

func fullVersion() string {
	if Commit != "" && Commit != "none" && len(Commit) > 7 {
		return Version + " (" + Commit[:7] + ")"
	}
	return Version
}

// Execute creates and runs the root command.
func Execute() error {
	rootCmd := &cobra.Command{
		Use:     "onyx-cli",
		Short:   "Terminal UI for chatting with Onyx",
		Long:    "Onyx CLI — a terminal interface for chatting with your Onyx agent.",
		Version: fullVersion(),
	}

	// Register subcommands
	chatCmd := newChatCmd()
	rootCmd.AddCommand(chatCmd)
	rootCmd.AddCommand(newAskCmd())
	rootCmd.AddCommand(newAgentsCmd())
	rootCmd.AddCommand(newConfigureCmd())

	// Default command is chat
	rootCmd.RunE = chatCmd.RunE

	return rootCmd.Execute()
}
