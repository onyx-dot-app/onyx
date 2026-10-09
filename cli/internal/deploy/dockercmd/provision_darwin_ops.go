package dockercmd

import (
	"context"
	"fmt"
	"io"
	"time"
)

// StartDockerDesktopDarwin launches Docker Desktop on macOS and waits for the
// daemon to answer, mirroring install.sh's `open -a Docker` + poll loop.
func StartDockerDesktopDarwin(ctx context.Context, d *Docker, progress io.Writer, maxWait time.Duration) error {
	if _, err := d.Runner.Run(ctx, Command{Name: "open", Args: []string{"-a", "Docker"}}); err != nil {
		return fmt.Errorf("failed to launch Docker Desktop: %w", err)
	}

	deadline := time.Now().Add(maxWait)
	for {
		if d.DaemonRunning(ctx) {
			return nil
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("Docker Desktop did not start within %s — start it manually and re-run", maxWait)
		}
		fmt.Fprintln(progress, "Waiting for Docker Desktop to start...")
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
}
