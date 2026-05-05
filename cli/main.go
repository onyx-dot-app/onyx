package main

import (
	"errors"
	"fmt"
	"os"

	"github.com/onyx-dot-app/onyx/cli/cmd"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
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
		var exitErr *exitcodes.ExitError
		if errors.As(err, &exitErr) {
			os.Exit(exitErr.Code)
		}
		os.Exit(1)
	}
}
