package browser

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// limitCgroup sets the memory limit of the browser's parent cgroup. The OOM
// killer then kills the whole browser (Xvfb and Chromium), and the
// supervisor restarts it.
func limitCgroup(root string, maxBytes int64) error {
	if err := os.WriteFile(filepath.Join(root, "memory.max"), []byte(strconv.FormatInt(maxBytes, 10)), 0); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(root, "memory.oom.group"), []byte("1"), 0)
}

func memoryCurrent(root string) uint64 {
	raw, err := os.ReadFile(filepath.Join(root, "memory.current"))
	if err != nil {
		return 0
	}
	n, _ := strconv.ParseUint(strings.TrimSpace(string(raw)), 10, 64)
	return n
}

// prepareX11 makes the X11 socket dir and removes the lock and socket that a
// killed Xvfb leaves; Xvfb refuses a display with a lock file.
func prepareX11(tmp string, display int) {
	d := strconv.Itoa(display)
	if os.Geteuid() == 0 {
		dir := filepath.Join(tmp, ".X11-unix")
		_ = os.Mkdir(dir, 0o1777)
		_ = os.Chown(dir, 0, 0)
		_ = os.Chmod(dir, os.ModeSticky|0o777)
	}
	_ = os.Remove(filepath.Join(tmp, ".X"+d+"-lock"))
	_ = os.Remove(filepath.Join(tmp, ".X11-unix", "X"+d))
}
