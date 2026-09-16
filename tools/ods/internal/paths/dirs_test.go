package paths

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

// skipUnlessXDG skips the tests that assert the XDG layout, which only
// applies outside Windows.
func skipUnlessXDG(t *testing.T) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the directories follow APPDATA and LOCALAPPDATA on Windows")
	}
}

func TestConfigDir_followsXDGConfigHome(t *testing.T) {
	skipUnlessXDG(t)
	home := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", home)

	if got, want := ConfigDir(), filepath.Join(home, "onyx-dev"); got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
	if got, want := ConfigFilePath(), filepath.Join(home, "onyx-dev", "config.json"); got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestConfigDir_fallsBackToTheHomeDirectory(t *testing.T) {
	skipUnlessXDG(t)
	home := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", "")
	t.Setenv("HOME", home)

	if got, want := ConfigDir(), filepath.Join(home, ".config", "onyx-dev"); got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestDataDir_followsXDGDataHome(t *testing.T) {
	skipUnlessXDG(t)
	home := t.TempDir()
	t.Setenv("XDG_DATA_HOME", home)

	if got, want := DataDir(), filepath.Join(home, "onyx-dev"); got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
	if got, want := SnapshotsDir(), filepath.Join(home, "onyx-dev", "snapshots"); got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestDataDir_fallsBackToTheHomeDirectory(t *testing.T) {
	skipUnlessXDG(t)
	home := t.TempDir()
	t.Setenv("XDG_DATA_HOME", "")
	t.Setenv("HOME", home)

	if got, want := DataDir(), filepath.Join(home, ".local", "share", "onyx-dev"); got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestEnsureConfigDir_createsTheDirectory(t *testing.T) {
	skipUnlessXDG(t)
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())

	// Twice, because an existing directory is not an error.
	for i := 0; i < 2; i++ {
		if err := EnsureConfigDir(); err != nil {
			t.Fatalf("EnsureConfigDir failed: %v", err)
		}
	}

	info, err := os.Stat(ConfigDir())
	if err != nil {
		t.Fatalf("expected %s to exist: %v", ConfigDir(), err)
	}
	if !info.IsDir() {
		t.Fatalf("expected %s to be a directory", ConfigDir())
	}
}

func TestEnsureSnapshotsDir_createsTheDirectory(t *testing.T) {
	skipUnlessXDG(t)
	t.Setenv("XDG_DATA_HOME", t.TempDir())

	if err := EnsureSnapshotsDir(); err != nil {
		t.Fatalf("EnsureSnapshotsDir failed: %v", err)
	}

	info, err := os.Stat(SnapshotsDir())
	if err != nil {
		t.Fatalf("expected %s to exist: %v", SnapshotsDir(), err)
	}
	if !info.IsDir() {
		t.Fatalf("expected %s to be a directory", SnapshotsDir())
	}
}

func TestBackendDir_sitsInTheRepositoryRoot(t *testing.T) {
	root, err := GitRoot()
	if err != nil {
		t.Skipf("not a git checkout: %v", err)
	}

	backendDir, err := BackendDir()
	if err != nil {
		t.Fatalf("BackendDir failed: %v", err)
	}

	if want := filepath.Join(root, "backend"); backendDir != want {
		t.Fatalf("expected %q, got %q", want, backendDir)
	}
}

func TestBackendDir_failsOutsideAGitRepository(t *testing.T) {
	dir := t.TempDir()
	// Stop git from finding a repository that encloses the temp directory.
	t.Setenv("GIT_CEILING_DIRECTORIES", filepath.Dir(dir))
	t.Chdir(dir)

	if root, err := GitRoot(); err == nil {
		t.Fatalf("expected GitRoot to fail outside a repository, got %q", root)
	}
	if backendDir, err := BackendDir(); err == nil {
		t.Fatalf("expected BackendDir to fail outside a repository, got %q", backendDir)
	}
}
