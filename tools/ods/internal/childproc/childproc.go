// Package childproc runs a wrapped tool as a child process and gives the tool's
// result back to whoever ran ods. Every ods command that fronts another tool —
// uv, bun, go — needs the same behavior, so it lives here rather than in each
// command.
package childproc

import (
	"errors"
	"os"
	"os/exec"

	log "github.com/sirupsen/logrus"
)

// Run runs a wrapped tool with our stdio attached and does not return on
// failure. The child's exit code becomes ours, so shell chains and CI see the
// underlying tool's result, and stderr the child already printed is not
// repeated. label names the tool in the message used when the process could
// not be started at all.
func Run(c *exec.Cmd, label string) {
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
