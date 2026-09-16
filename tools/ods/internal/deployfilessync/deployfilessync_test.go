package deployfilessync

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// seedSources writes a fake deployment/ tree containing every synced file.
func seedSources(t *testing.T, repoRoot string) {
	t.Helper()
	for _, rel := range RelPaths {
		path := filepath.Join(SourceDir(repoRoot), filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			t.Fatalf("mkdir for %s: %v", rel, err)
		}
		if err := os.WriteFile(path, []byte("content of "+rel+"\n"), 0644); err != nil {
			t.Fatalf("write %s: %v", rel, err)
		}
	}
}

func TestCheckReportsMissingCopiesAsStale(t *testing.T) {
	repoRoot := t.TempDir()
	seedSources(t, repoRoot)

	results, err := Check(repoRoot)
	if err != nil {
		t.Fatalf("Check failed: %v", err)
	}
	if len(results) != len(RelPaths) {
		t.Fatalf("got %d results, want %d", len(results), len(RelPaths))
	}
	for _, r := range results {
		if !r.Stale {
			t.Errorf("%s: expected stale (no embedded copy exists)", r.RelPath)
		}
	}
}

func TestWriteSyncsAndCheckTurnsClean(t *testing.T) {
	repoRoot := t.TempDir()
	seedSources(t, repoRoot)

	if _, err := Write(repoRoot); err != nil {
		t.Fatalf("Write failed: %v", err)
	}

	results, err := Check(repoRoot)
	if err != nil {
		t.Fatalf("Check failed: %v", err)
	}
	for _, r := range results {
		if r.Stale {
			t.Errorf("%s: still stale after Write", r.RelPath)
		}
		if r.Source != r.Dest {
			t.Errorf("%s: embedded copy differs from source", r.RelPath)
		}
	}
}

func TestSourceEditMakesCopyStaleAgain(t *testing.T) {
	repoRoot := t.TempDir()
	seedSources(t, repoRoot)
	if _, err := Write(repoRoot); err != nil {
		t.Fatalf("Write failed: %v", err)
	}

	edited := filepath.Join(SourceDir(repoRoot), "docker_compose", "env.template")
	if err := os.WriteFile(edited, []byte("IMAGE_TAG=v9.9.9\n"), 0644); err != nil {
		t.Fatalf("edit source: %v", err)
	}

	results, err := Check(repoRoot)
	if err != nil {
		t.Fatalf("Check failed: %v", err)
	}
	staleCount := 0
	for _, r := range results {
		if r.Stale {
			staleCount++
			if r.RelPath != "docker_compose/env.template" {
				t.Errorf("unexpected stale file %s", r.RelPath)
			}
		}
	}
	if staleCount != 1 {
		t.Errorf("got %d stale files, want 1", staleCount)
	}
}

func TestCheckFailsWhenSourceMissing(t *testing.T) {
	repoRoot := t.TempDir()
	if _, err := Check(repoRoot); err == nil {
		t.Fatal("expected error for missing source files")
	}
}

// Write only touches stale copies: a fresh copy keeps its file untouched.
func TestWriteLeavesFreshCopiesAlone(t *testing.T) {
	repoRoot := t.TempDir()
	seedSources(t, repoRoot)
	if _, err := Write(repoRoot); err != nil {
		t.Fatalf("Write failed: %v", err)
	}
	// Swap one fresh copy for a symlink to its source. The content still
	// matches, and a rewrite would replace the symlink with a regular file.
	fresh := filepath.Join(DestDir(repoRoot), "docker_compose", "README.md")
	source := filepath.Join(SourceDir(repoRoot), "docker_compose", "README.md")
	if err := os.Remove(fresh); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(source, fresh); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}

	results, err := Write(repoRoot)
	if err != nil {
		t.Fatalf("Write failed: %v", err)
	}
	for _, r := range results {
		if r.Stale {
			t.Errorf("%s: expected fresh", r.RelPath)
		}
	}
	info, err := os.Lstat(fresh)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode()&os.ModeSymlink == 0 {
		t.Fatal("expected the fresh copy left untouched")
	}
}

// An embedded copy that cannot be read stops the sync rather than being
// reported as missing and overwritten.
func TestWriteFailsWhenACopyIsUnreadable(t *testing.T) {
	repoRoot := t.TempDir()
	seedSources(t, repoRoot)
	dir := filepath.Join(DestDir(repoRoot), "docker_compose", "README.md")
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}

	_, err := Write(repoRoot)

	want := "failed to read embedded copy docker_compose/README.md"
	if err == nil || !strings.Contains(err.Error(), want) {
		t.Fatalf("expected %q, got %v", want, err)
	}
}
