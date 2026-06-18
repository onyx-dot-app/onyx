package fsutil

import (
	"os"
	"path/filepath"
	"testing"
)

// TestCompareFile verifies that CompareFile correctly distinguishes between a
// missing file, a file with matching content, and a file with different content.
func TestCompareFile(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "skill.md")
	expected := []byte("expected content")

	status, err := CompareFile(path, expected)
	if err != nil {
		t.Fatalf("CompareFile on missing file failed: %v", err)
	}
	if status != StatusMissing {
		t.Fatalf("expected StatusMissing, got %v", status)
	}

	if err := os.WriteFile(path, expected, 0o644); err != nil {
		t.Fatalf("write expected file failed: %v", err)
	}
	status, err = CompareFile(path, expected)
	if err != nil {
		t.Fatalf("CompareFile on matching file failed: %v", err)
	}
	if status != StatusUpToDate {
		t.Fatalf("expected StatusUpToDate, got %v", status)
	}

	if err := os.WriteFile(path, []byte("different content"), 0o644); err != nil {
		t.Fatalf("write different file failed: %v", err)
	}
	status, err = CompareFile(path, expected)
	if err != nil {
		t.Fatalf("CompareFile on different file failed: %v", err)
	}
	if status != StatusDiffers {
		t.Fatalf("expected StatusDiffers, got %v", status)
	}
}

// TestEnsureDirForCopy verifies that EnsureDirForCopy clears symlinks and
// regular files so --copy can write a real directory, while leaving existing
// directories and missing paths untouched.
func TestEnsureDirForCopy(t *testing.T) {
	t.Run("removes symlink", func(t *testing.T) {
		tmpDir := t.TempDir()
		targetDir := filepath.Join(tmpDir, "target")
		linkPath := filepath.Join(tmpDir, "link")

		if err := os.MkdirAll(targetDir, 0o755); err != nil {
			t.Fatalf("mkdir target failed: %v", err)
		}
		if err := os.Symlink(targetDir, linkPath); err != nil {
			t.Fatalf("create symlink failed: %v", err)
		}

		if err := EnsureDirForCopy(linkPath); err != nil {
			t.Fatalf("EnsureDirForCopy failed: %v", err)
		}

		if _, err := os.Lstat(linkPath); !os.IsNotExist(err) {
			t.Fatalf("expected symlink path to be removed, got err=%v", err)
		}
	})

	t.Run("removes regular file", func(t *testing.T) {
		tmpDir := t.TempDir()
		filePath := filepath.Join(tmpDir, "onyx-cli")
		if err := os.WriteFile(filePath, []byte("x"), 0o644); err != nil {
			t.Fatalf("write file failed: %v", err)
		}

		if err := EnsureDirForCopy(filePath); err != nil {
			t.Fatalf("EnsureDirForCopy failed: %v", err)
		}

		if _, err := os.Lstat(filePath); !os.IsNotExist(err) {
			t.Fatalf("expected file path to be removed, got err=%v", err)
		}
	})

	t.Run("keeps existing directory", func(t *testing.T) {
		tmpDir := t.TempDir()
		dirPath := filepath.Join(tmpDir, "onyx-cli")
		if err := os.MkdirAll(dirPath, 0o755); err != nil {
			t.Fatalf("mkdir failed: %v", err)
		}

		if err := EnsureDirForCopy(dirPath); err != nil {
			t.Fatalf("EnsureDirForCopy failed: %v", err)
		}

		info, err := os.Lstat(dirPath)
		if err != nil {
			t.Fatalf("lstat directory failed: %v", err)
		}
		if !info.IsDir() {
			t.Fatalf("expected directory to remain, got mode %v", info.Mode())
		}
	})

	t.Run("missing path is no-op", func(t *testing.T) {
		tmpDir := t.TempDir()
		missingPath := filepath.Join(tmpDir, "does-not-exist")

		if err := EnsureDirForCopy(missingPath); err != nil {
			t.Fatalf("EnsureDirForCopy failed: %v", err)
		}
	})
}
