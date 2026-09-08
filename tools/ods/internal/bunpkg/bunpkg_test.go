package bunpkg

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func writeFile(t *testing.T, path string, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func setMtime(t *testing.T, path string, mtime time.Time) {
	t.Helper()
	if err := os.Chtimes(path, mtime, mtime); err != nil {
		t.Fatal(err)
	}
}

func TestNodeModulesNeedsInstall(t *testing.T) {
	now := time.Now()

	t.Run("missing node_modules", func(t *testing.T) {
		dir := t.TempDir()
		needs, reason := NodeModulesNeedsInstall(dir)
		if !needs {
			t.Fatal("expected install for missing node_modules")
		}
		if reason != "node_modules not found" {
			t.Fatalf("unexpected reason: %q", reason)
		}
	})

	t.Run("empty node_modules", func(t *testing.T) {
		dir := t.TempDir()
		if err := os.Mkdir(filepath.Join(dir, "node_modules"), 0o755); err != nil {
			t.Fatal(err)
		}
		needs, reason := NodeModulesNeedsInstall(dir)
		if !needs {
			t.Fatal("expected install for empty node_modules")
		}
		if reason != "node_modules is empty" {
			t.Fatalf("unexpected reason: %q", reason)
		}
	})

	t.Run("populated without stamp is stale", func(t *testing.T) {
		dir := t.TempDir()
		writeFile(t, filepath.Join(dir, "bun.lock"), "lock-v1")
		writeFile(t, filepath.Join(dir, "node_modules", "pkg", "index.js"), "")
		needs, _ := NodeModulesNeedsInstall(dir)
		if !needs {
			t.Fatal("expected install when no stamp recorded")
		}
	})

	t.Run("stamp matches lockfile", func(t *testing.T) {
		dir := t.TempDir()
		writeFile(t, filepath.Join(dir, "bun.lock"), "lock-v1")
		writeFile(t, filepath.Join(dir, "node_modules", "pkg", "index.js"), "")
		WriteLockStamp(dir)
		needs, reason := NodeModulesNeedsInstall(dir)
		if needs {
			t.Fatalf("expected no install with matching stamp, got: %q", reason)
		}
	})

	t.Run("lockfile changed after stamp", func(t *testing.T) {
		dir := t.TempDir()
		writeFile(t, filepath.Join(dir, "bun.lock"), "lock-v1")
		writeFile(t, filepath.Join(dir, "node_modules", "pkg", "index.js"), "")
		WriteLockStamp(dir)
		writeFile(t, filepath.Join(dir, "bun.lock"), "lock-v2")
		setMtime(t, filepath.Join(dir, "bun.lock"), now)
		needs, _ := NodeModulesNeedsInstall(dir)
		if !needs {
			t.Fatal("expected install after lockfile change")
		}
	})

	t.Run("stamp replaces an existing file it cannot write in place", func(t *testing.T) {
		// Sessions run as different users against the shared node_modules
		// volume, so the previous stamp may not be writable — only
		// replaceable via the directory. Simulate with a read-only stamp.
		dir := t.TempDir()
		writeFile(t, filepath.Join(dir, "bun.lock"), "lock-v2")
		writeFile(t, filepath.Join(dir, "node_modules", "pkg", "index.js"), "")
		stampPath := filepath.Join(dir, "node_modules", lockStampName)
		writeFile(t, stampPath, "stale-hash")
		if err := os.Chmod(stampPath, 0o444); err != nil {
			t.Fatal(err)
		}
		WriteLockStamp(dir)
		needs, reason := NodeModulesNeedsInstall(dir)
		if needs {
			t.Fatalf("expected stamp to be replaced despite read-only file, got: %q", reason)
		}
	})

	t.Run("no lockfile skips staleness check", func(t *testing.T) {
		dir := t.TempDir()
		writeFile(t, filepath.Join(dir, "node_modules", "pkg", "index.js"), "")
		needs, _ := NodeModulesNeedsInstall(dir)
		if needs {
			t.Fatal("expected no install without a lockfile to compare")
		}
	})
}

func TestLibNeedsBuild(t *testing.T) {
	old := time.Now().Add(-time.Hour)
	older := old.Add(-time.Hour)

	t.Run("missing package is skipped", func(t *testing.T) {
		needs, _ := LibNeedsBuild(filepath.Join(t.TempDir(), "lib", "nope"))
		if needs {
			t.Fatal("expected missing package to be skipped")
		}
	})

	t.Run("missing dist", func(t *testing.T) {
		pkgDir := t.TempDir()
		writeFile(t, filepath.Join(pkgDir, "src", "index.ts"), "")
		needs, reason := LibNeedsBuild(pkgDir)
		if !needs {
			t.Fatal("expected build for missing dist")
		}
		if reason != "has no dist build" {
			t.Fatalf("unexpected reason: %q", reason)
		}
	})

	t.Run("dist newer than sources", func(t *testing.T) {
		pkgDir := t.TempDir()
		src := filepath.Join(pkgDir, "src", "index.ts")
		dist := filepath.Join(pkgDir, "dist", "index.js")
		writeFile(t, src, "")
		writeFile(t, dist, "")
		setMtime(t, src, older)
		setMtime(t, filepath.Join(pkgDir, "src"), older)
		setMtime(t, pkgDir, older)
		needs, reason := LibNeedsBuild(pkgDir)
		if needs {
			t.Fatalf("expected no build when dist is fresh, got: %q", reason)
		}
	})

	t.Run("source newer than dist", func(t *testing.T) {
		pkgDir := t.TempDir()
		src := filepath.Join(pkgDir, "src", "index.ts")
		dist := filepath.Join(pkgDir, "dist", "index.js")
		writeFile(t, src, "")
		writeFile(t, dist, "")
		setMtime(t, dist, older)
		setMtime(t, filepath.Join(pkgDir, "dist"), older)
		setMtime(t, src, old)
		needs, _ := LibNeedsBuild(pkgDir)
		if !needs {
			t.Fatal("expected build when a source is newer than dist")
		}
	})

	t.Run("changes under excluded dirs are ignored", func(t *testing.T) {
		pkgDir := t.TempDir()
		src := filepath.Join(pkgDir, "src", "index.ts")
		dist := filepath.Join(pkgDir, "dist", "index.js")
		dep := filepath.Join(pkgDir, "node_modules", "dep", "index.js")
		writeFile(t, src, "")
		writeFile(t, dist, "")
		writeFile(t, dep, "")
		setMtime(t, src, older)
		setMtime(t, filepath.Join(pkgDir, "src"), older)
		setMtime(t, pkgDir, older)
		needs, reason := LibNeedsBuild(pkgDir)
		if needs {
			t.Fatalf("expected node_modules churn to be ignored, got: %q", reason)
		}
	})
}
