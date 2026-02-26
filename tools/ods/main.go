package main

import (
	"fmt"
	"os"

	"github.com/onyx-dot-app/onyx/tools/ods/cmd"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
)

var (
	version = "dev"
	commit  = "none"
)

func main() {
	// If a stashed binary exists (from a prior cherry-pick) and we are not
	// already running from it, re-exec immediately.  This must happen before
	// Cobra parses subcommands because the installed binary may be an older
	// version (overwritten by uv-sync) that doesn't recognise newer commands.
	git.ReExecFromStashedBinary()

	// Set the version in the cmd package
	cmd.Version = version
	cmd.Commit = commit

	rootCmd := cmd.NewRootCommand()

	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(2)
	}
}
