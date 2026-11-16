package scratch

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func notLinked(t *testing.T, src, dst string) {
	t.Helper()
	ss, err := os.Stat(src)
	if err != nil {
		t.Fatal(err)
	}
	sd, err := os.Stat(dst)
	if err != nil {
		t.Fatal(err)
	}
	if os.SameFile(ss, sd) || nlink(sd) != 1 || nlink(ss) != 1 {
		t.Fatalf("copy is linked to its source (same file %v, links %d/%d)", os.SameFile(ss, sd), nlink(ss), nlink(sd))
	}
}

// A snapshot/create truncates its target. A truncate or write of a VM's copy
// must never change the template file.
func TestCloneIsNeverAHardLink(t *testing.T) {
	dir := t.TempDir()
	if err := ProbeReflink(dir); errors.Is(err, ErrNoReflink) {
		t.Skipf("no reflink on %s: %v", dir, err)
	} else if err != nil {
		t.Fatal(err)
	}
	src := filepath.Join(dir, "mem")
	want := bytes.Repeat([]byte("snapshot"), 4096)
	if err := os.WriteFile(src, want, 0o644); err != nil {
		t.Fatal(err)
	}
	dst := filepath.Join(dir, "vm-mem")
	if err := Clone(src, dst, 0o644, os.Getuid(), os.Getgid()); err != nil {
		t.Fatal(err)
	}
	notLinked(t, src, dst)
	if err := os.Truncate(dst, 0); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(dst, []byte("other"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(src); !bytes.Equal(got, want) {
		t.Fatal("a write to the copy changed the template file")
	}
	if err := Clone(src, dst, 0o644, os.Getuid(), os.Getgid()); err == nil {
		t.Fatal("Clone overwrote an existing file")
	}
}

func TestCopyFileSparseFallback(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "rootfs.ext4")
	f, err := os.Create(src)
	if err != nil {
		t.Fatal(err)
	}
	// Data, a 3 MiB hole, data, and a short tail.
	if _, err := f.Write(bytes.Repeat([]byte{1}, copyChunk)); err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteAt([]byte("tail"), 4*copyChunk+7); err != nil {
		t.Fatal(err)
	}
	_ = f.Close()
	dst := filepath.Join(dir, "copy")
	if _, err := CopyFile(src, dst); err != nil {
		t.Fatal(err)
	}
	notLinked(t, src, dst)
	a, _ := os.ReadFile(src)
	b, _ := os.ReadFile(dst)
	if !bytes.Equal(a, b) {
		t.Fatalf("copy differs (%d vs %d bytes)", len(a), len(b))
	}
	if _, err := CopyFile(src, dst); err == nil {
		t.Fatal("CopyFile overwrote an existing file")
	}
}
