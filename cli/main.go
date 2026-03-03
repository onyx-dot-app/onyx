package main

import (
	"fmt"
	"os"

	"github.com/onyx-dot-app/onyx/cli/cmd"
)

var (
	version = "dev"
	commit  = "none"
)

func main() {
	cmd.Version = version
	cmd.Commit = commit

	if err := cmd.Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
