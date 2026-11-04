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
