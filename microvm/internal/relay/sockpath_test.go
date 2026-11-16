package relay

import (
	"os"
	"path/filepath"
	"testing"
)

// shortSock returns a unix socket path in a new dir under /tmp, unique
// across processes. t.TempDir paths can pass the 104-byte macOS limit.
func shortSock(t *testing.T, name string) string {
	t.Helper()
	dir, err := os.MkdirTemp("/tmp", "fct-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	return filepath.Join(dir, name+".sock")
}
