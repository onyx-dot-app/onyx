package sysops

import (
	"errors"
	"testing"
)

func TestWaitDevSize(t *testing.T) {
	sizes := []uint64{1 << 30, 1 << 30, 2 << 30}
	reads := 0
	read := func() (uint64, error) {
		n := sizes[min(reads, len(sizes)-1)]
		reads++
		return n, nil
	}
	if n, err := waitDevSize(read, 2<<30, 5, 0); err != nil || n != 2<<30 || reads != 3 {
		t.Fatalf("grown late: n=%d err=%v reads=%d", n, err, reads)
	}
	reads = 0
	if _, err := waitDevSize(read, 4<<30, 4, 0); err == nil || reads != 4 {
		t.Fatalf("never grown: err=%v reads=%d", err, reads)
	}
	reads = 0
	if n, err := waitDevSize(read, 0, 4, 0); err != nil || n != 1<<30 || reads != 1 {
		t.Fatalf("no minimum: n=%d err=%v reads=%d", n, err, reads)
	}
	boom := errors.New("boom")
	if _, err := waitDevSize(func() (uint64, error) { return 0, boom }, 1, 4, 0); !errors.Is(err, boom) {
		t.Fatalf("read error: %v", err)
	}
}
