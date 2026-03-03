// Package cmd implements Cobra CLI commands for the Onyx CLI.
package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

const version = "0.1.0"

var rootCmd = &cobra.Command{
	Use:   "onyx",
	Short: "Terminal UI for chatting with Onyx",
	Long:  "Onyx CLI — a terminal interface for chatting with your Onyx agent.",
}

func init() {
	rootCmd.Version = version
	// Default command is chat
	rootCmd.RunE = chatCmd.RunE
}

// Execute runs the root command.
func Execute() {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
