package binaries

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
)

func TestParseVersion(t *testing.T) {
	if v := ParseVersion("Firecracker v1.17.0\n\nmore"); v != "v1.17.0" {
		t.Fatalf("got %q", v)
	}
	if v := ParseVersion("something else"); v != "" {
		t.Fatalf("got %q", v)
	}
}

func TestInstallOneChecksHash(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src")
	if err := os.WriteFile(src, []byte("binary"), 0o644); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256([]byte("binary"))
	good := hex.EncodeToString(sum[:])
	dst := filepath.Join(dir, "dst")
	if err := installOne(src, dst, "00"); err == nil {
		t.Fatal("installed a binary with the wrong hash")
	}
	if _, err := os.Stat(dst); !os.IsNotExist(err) {
		t.Fatal("wrong-hash install left a file")
	}
	if err := installOne(src, dst, good); err != nil {
		t.Fatal(err)
	}
	st, err := os.Stat(dst)
	if err != nil || st.Mode().Perm() != 0o755 {
		t.Fatalf("dst: %v %v", st, err)
	}
	// A correct copy is kept even if the source goes away.
	if err := os.Remove(src); err != nil {
		t.Fatal(err)
	}
	if err := installOne(src, dst, good); err != nil {
		t.Fatal(err)
	}
}

func TestInstallKernel(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "vmlinux")
	img := append(make([]byte, 4096), []byte("Linux version 6.18.25 (builder@host) #1 SMP\x00")...)
	if err := os.WriteFile(src, img, 0o644); err != nil {
		t.Fatal(err)
	}
	k, err := InstallKernel(src, filepath.Join(dir, "kernel"))
	if err != nil {
		t.Fatal(err)
	}
	if k.Release != "6.18.25" || len(k.SHA256) != 64 || filepath.Base(k.Path) != "vmlinux-"+k.SHA256[:16] {
		t.Fatalf("kernel %+v", k)
	}
	// A second install keeps the copy.
	if k2, err := InstallKernel(src, filepath.Join(dir, "kernel")); err != nil || *k2 != *k {
		t.Fatalf("second install %+v %v", k2, err)
	}
	if err := os.WriteFile(src, []byte("no banner"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := InstallKernel(src, filepath.Join(dir, "kernel2")); err == nil {
		t.Fatal("a file without a Linux banner was accepted")
	}
}
