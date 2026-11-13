//go:build linux

package guestlog

import (
	"bytes"
	"os"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
)

// fc.log has a writer without O_APPEND (Firecracker v1.17), so the cap
// punches a hole: the size and the writer's offset stay valid.
func TestFirecrackerLogCapPunchesHole(t *testing.T) {
	f := newFixture(t, &Shipper{MaxFileBytes: 100}, id1)
	path := f.lay.HostPath(id1, jailer.LogFile)
	w, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = w.Close() }()
	f.s.Start(t.Context())
	_, _ = w.WriteString(strings.Repeat("123456789\n", 12))
	f.s.Tick()
	if got := len(texts(f.lines())); got != 12 {
		t.Fatalf("shipped %d lines", got)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(raw) != 120 || !bytes.Equal(raw, make([]byte, 120)) {
		t.Fatalf("fc.log not punched: %q", raw)
	}
	_, _ = w.WriteString("next\n")
	f.s.Tick()
	eq(t, texts(f.lines()), "next")
}
