package cmd

import (
	"errors"
	"os"
	"os/exec"

	log "github.com/sirupsen/logrus"
)

// runChild runs a wrapped tool with our stdio attached and does not return on
// failure. The child's exit code becomes ours, so shell chains and CI see the
// underlying tool's result, and stderr the child already printed is not
// repeated. label names the tool in the message used when the process could
// not be started at all.
func runChild(c *exec.Cmd, label string) {
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	c.Stdin = os.Stdin

	if err := c.Run(); err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			if code := exitErr.ExitCode(); code != -1 {
				os.Exit(code)
			}
		}
		log.Fatalf("Failed to run %s: %v", label, err)
	}
}
