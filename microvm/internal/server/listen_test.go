package server

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestListenUnixSocketIsPrivate(t *testing.T) {
	// A short temp dir: macOS temp paths are close to the sun_path limit.
	dir, err := os.MkdirTemp("", "ha")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	path := filepath.Join(dir, "run", "a.sock")
	old := syscall.Umask(0o022)
	defer syscall.Umask(old)
	ln, err := ListenUnix(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close() }()
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if st.Mode().Perm() != 0o600 {
		t.Fatalf("socket mode %v, want 0600", st.Mode().Perm())
	}
	if got := syscall.Umask(0o022); got != 0o022 {
		t.Fatalf("umask left at %o", got)
	}
}
