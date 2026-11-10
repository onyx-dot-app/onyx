package fcvm

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

func TestTailReadsOnlyTheEnd(t *testing.T) {
	path := filepath.Join(t.TempDir(), "fc.log")
	body := append(bytes.Repeat([]byte("x"), 1<<20), []byte("last line\n")...)
	if err := os.WriteFile(path, body, 0o600); err != nil {
		t.Fatal(err)
	}
	got := tail(path)
	if len(got) != tailBytes-1 || !bytes.HasSuffix([]byte(got), []byte("last line")) {
		t.Fatalf("tail is %d bytes, ends %q", len(got), got[max(0, len(got)-12):])
	}
	short := filepath.Join(t.TempDir(), "short.log")
	if err := os.WriteFile(short, []byte(" boot failed \n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := tail(short); got != "boot failed" {
		t.Fatalf("short tail %q", got)
	}
}
