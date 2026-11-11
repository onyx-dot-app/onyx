//go:build unix

package sysops

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// attachWaitDelay is how long RunAttach waits for the output pipe after the
// timeout kills the script.
var attachWaitDelay = 5 * time.Second

// RunAttach runs the image's attach script (it mounts the per-VM drives and
// does nothing on a second run).
func RunAttach(path string, timeout time.Duration) error {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, path)
	cmd.Env = []string{"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
	// The context kills only the script. A child stuck on a drive can keep the
	// output pipe open; stop waiting for it shortly after the kill.
	cmd.WaitDelay = attachWaitDelay
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s: %w: %s", path, err, strings.TrimSpace(tail(out, 2000)))
	}
	return nil
}

// SignalPIDFile sends SIGHUP to the process in pidFile. It reports false,
// with no error, if the file or the process does not exist.
func SignalPIDFile(pidFile string) (bool, error) {
	raw, err := os.ReadFile(pidFile)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
	if err != nil || pid <= 1 {
		return false, fmt.Errorf("bad pid in %s: %q", pidFile, raw)
	}
	if err := syscall.Kill(pid, syscall.SIGHUP); err != nil {
		if errors.Is(err, syscall.ESRCH) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func tail(b []byte, n int) string {
	if len(b) > n {
		b = b[len(b)-n:]
	}
	return string(b)
}
