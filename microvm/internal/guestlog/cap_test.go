package guestlog

import (
	"os"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
)

func size(t *testing.T, path string) int64 {
	t.Helper()
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	return st.Size()
}

// The console writer keeps one O_APPEND fd, like Firecracker's stdout.
func TestConsoleCapTruncatesInPlace(t *testing.T) {
	f := newFixture(t, &Shipper{MaxFileBytes: 100}, id1)
	path := f.lay.ConsoleLog(id1)
	w, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = w.Close() }()
	f.s.Start(t.Context())
	_, _ = w.WriteString(strings.Repeat("123456789\n", 9) + "half")
	f.s.Tick()
	if got := len(texts(f.lines())); got != 9 || size(t, path) != 94 {
		t.Fatalf("under the cap: %d lines, size %d", got, size(t, path))
	}
	_, _ = w.WriteString(" line\n")
	f.s.Tick()
	eq(t, texts(f.lines()), "half line")
	if n := size(t, path); n != 0 {
		t.Fatalf("console.log not emptied at the cap: %d bytes", n)
	}
	// The writer's next line lands at the new end and ships whole.
	_, _ = w.WriteString("after\n")
	f.s.Tick()
	eq(t, texts(f.lines()), "after")
	if n := size(t, path); n != 6 {
		t.Fatalf("size after the truncate: %d", n)
	}
}

func TestConsoleCapKeepsUnreadBytes(t *testing.T) {
	dir := t.TempDir()
	path := dir + "/console.log"
	if err := os.WriteFile(path, []byte(strings.Repeat("x", 180)), 0o600); err != nil {
		t.Fatal(err)
	}
	fh, err := os.OpenFile(path, os.O_RDWR, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = fh.Close() }()
	s := &Shipper{MaxFileBytes: 100}
	ft := &fileTail{path: path, off: 150, appendOnly: true}
	// 30 unread bytes and under twice the cap: wait for the next read.
	if lost := s.capFile(&vmTail{}, fh, ft); lost != 0 || size(t, path) != 180 || ft.off != 150 {
		t.Fatalf("truncated with unread bytes: lost %d size %d off %d", lost, size(t, path), ft.off)
	}
	// Past twice the cap: empty it anyway and count the unread bytes.
	if err := os.WriteFile(path, []byte(strings.Repeat("x", 250)), 0o600); err != nil {
		t.Fatal(err)
	}
	if lost := s.capFile(&vmTail{}, fh, ft); lost != 100 || size(t, path) != 0 || ft.off != 0 {
		t.Fatalf("lost %d size %d off %d", lost, size(t, path), ft.off)
	}
}

func TestShipOffStillCaps(t *testing.T) {
	f := newFixture(t, &Shipper{MaxFileBytes: 100, ShipOff: true}, id1)
	f.s.Start(t.Context())
	f.write(id1, Console, strings.Repeat("123456789\n", 15))
	f.s.Tick()
	if out := f.lines(); len(out) != 0 {
		t.Fatalf("shipping off wrote %d lines", len(out))
	}
	if n := size(t, f.lay.ConsoleLog(id1)); n != 0 {
		t.Fatalf("console.log not capped with shipping off: %d", n)
	}
	f.write(id1, Console, "small\n")
	f.s.Tick()
	if n := size(t, f.lay.ConsoleLog(id1)); n != 6 {
		t.Fatalf("console.log under the cap changed: %d", n)
	}
}

func TestNoCapByDefault(t *testing.T) {
	f := newFixture(t, &Shipper{}, id1)
	f.s.Start(t.Context())
	f.write(id1, Console, strings.Repeat("123456789\n", 15))
	f.s.Tick()
	if n := size(t, f.lay.ConsoleLog(id1)); n != 150 {
		t.Fatalf("size %d", n)
	}
}

// A cap that fails is reported once, then again after it works.
func TestCapFailureIsLoggedOnce(t *testing.T) {
	f := newFixture(t, &Shipper{MaxFileBytes: 100}, id1)
	path := f.lay.HostPath(id1, jailer.LogFile)
	if err := os.WriteFile(path, []byte(strings.Repeat("x", 150)), 0o600); err != nil {
		t.Fatal(err)
	}
	// A read-only fd makes the hole punch fail on every OS.
	fh, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = fh.Close() }()
	f.s.init()
	ft := &fileTail{stream: Firecracker, path: path, off: 150}
	tail := &vmTail{vm: f.vms[0]}
	f.s.capFile(tail, fh, ft)
	f.s.capFile(tail, fh, ft)
	recs := f.lines()
	if len(recs) != 1 || recs[0]["msg"] != "guest log cap failed" || recs[0]["path"] != path ||
		recs[0]["sandbox_id"] != id1 || recs[0]["err"] == "" || recs[0]["level"] != "ERROR" {
		t.Fatalf("cap failure records: %v", recs)
	}
	if ft.punched != 0 || !ft.capErr {
		t.Fatalf("state after a failed cap: %+v", ft)
	}
}
