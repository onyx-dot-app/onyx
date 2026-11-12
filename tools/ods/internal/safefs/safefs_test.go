package safefs

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestWriteFileNoFollow_writesAndKeepsMode(t *testing.T) {
	base := t.TempDir()
	dest := filepath.Join(base, "a", "b", "file.sh")

	if err := WriteFileNoFollow(base, dest, []byte("one"), 0o644); err != nil {
		t.Fatalf("first write: %v", err)
	}
	if err := os.Chmod(dest, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := WriteFileNoFollow(base, dest, []byte("two"), 0o644); err != nil {
		t.Fatalf("second write: %v", err)
	}

	if got, _ := os.ReadFile(dest); string(got) != "two" {
		t.Fatalf("expected new content, got %q", got)
	}
	info, err := os.Stat(dest)
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm() != 0o755 {
		t.Fatalf("expected the existing mode kept, got %v", info.Mode().Perm())
	}
}

func TestWriteFileNoFollow_refusesSymlinks(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink fixtures are POSIX-only")
	}
	cases := []struct {
		name  string
		plant func(t *testing.T, base, outside string) string
	}{
		{
			name: "leaf link to an existing file",
			plant: func(t *testing.T, base, outside string) string {
				dest := filepath.Join(base, "file")
				mustSymlink(t, filepath.Join(outside, "sentinel"), dest)
				return dest
			},
		},
		{
			name: "dangling leaf link",
			plant: func(t *testing.T, base, outside string) string {
				dest := filepath.Join(base, "file")
				mustSymlink(t, filepath.Join(outside, "created"), dest)
				return dest
			},
		},
		{
			name: "linked parent directory",
			plant: func(t *testing.T, base, outside string) string {
				mustSymlink(t, outside, filepath.Join(base, "dir"))
				return filepath.Join(base, "dir", "sentinel")
			},
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			base, outside := t.TempDir(), t.TempDir()
			sentinel := filepath.Join(outside, "sentinel")
			if err := os.WriteFile(sentinel, []byte("original"), 0o644); err != nil {
				t.Fatal(err)
			}
			dest := c.plant(t, base, outside)

			if err := WriteFileNoFollow(base, dest, []byte("payload"), 0o644); err == nil {
				t.Fatal("expected the write to be refused")
			}

			if got, _ := os.ReadFile(sentinel); string(got) != "original" {
				t.Fatalf("link target changed: %q", got)
			}
			if _, err := os.Lstat(filepath.Join(outside, "created")); !os.IsNotExist(err) {
				t.Fatalf("link target was created: %v", err)
			}
		})
	}
}

func TestWriteFileNoFollow_refusesPathOutsideBase(t *testing.T) {
	base := t.TempDir()
	if err := WriteFileNoFollow(base, filepath.Join(base, "..", "escape"), []byte("x"), 0o644); err == nil {
		t.Fatal("expected a path outside base to be refused")
	}
}

func mustSymlink(t *testing.T, target, link string) {
	t.Helper()
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
}

func TestCheckNoSymlinks(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink fixtures are POSIX-only")
	}
	base := t.TempDir()
	mustSymlink(t, t.TempDir(), filepath.Join(base, "link"))
	if err := os.Mkdir(filepath.Join(base, "real"), 0o755); err != nil {
		t.Fatal(err)
	}

	if err := CheckNoSymlinks(base, filepath.Join(base, "real", "missing", "x")); err != nil {
		t.Fatalf("expected real and missing parts accepted: %v", err)
	}
	if err := CheckNoSymlinks(base, filepath.Join(base, "link", "rules")); err == nil {
		t.Fatal("expected a linked part to be refused")
	}
	if err := CheckNoSymlinks(base, filepath.Join(base, "..")); err == nil {
		t.Fatal("expected a path outside base to be refused")
	}
}
