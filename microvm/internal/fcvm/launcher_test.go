package fcvm

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
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

func TestLauncherLimits(t *testing.T) {
	l := &Launcher{}
	if got := l.limits(2, 4096); got != jailer.VMLimits(2, 4096, jailer.DefaultMemOverheadMiB) {
		t.Errorf("default overhead: %+v", got)
	}
	l.MemOverheadMiB = 64
	if got := l.limits(4, 8192); got.MemoryMaxBytes != (8192+64)<<20 || got.CPUQuotaPercent != 400 {
		t.Errorf("overhead 64: %+v", got)
	}
}
