package devstack

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestEnvironmentUpdateCannotChangeAnotherCheckoutsSymlinkTarget(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("creating symlinks requires Windows privileges")
	}
	original := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(original, []byte("POSTGRES_PORT=5432\nSECRET=private\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	local := filepath.Join(t.TempDir(), ".env")
	if err := os.Symlink(original, local); err != nil {
		t.Fatal(err)
	}
	if err := UpsertEnvFile(local, map[string]string{"POSTGRES_PORT": "55432"}); err != nil {
		t.Fatal(err)
	}
	source, err := os.ReadFile(original)
	if err != nil || string(source) != "POSTGRES_PORT=5432\nSECRET=private\n" {
		t.Fatalf("another checkout's environment changed: %v", err)
	}
	updated, err := os.ReadFile(local)
	if err != nil || string(updated) != "POSTGRES_PORT=55432\nSECRET=private\n" {
		t.Fatalf("local update failed: %v", err)
	}
	info, err := os.Lstat(local)
	if err != nil || info.Mode()&os.ModeSymlink != 0 {
		t.Fatalf("local environment remained shared: %v", err)
	}
}
