package hostinfo

import (
	"errors"
	"io/fs"
	"os"
	"runtime"
	"strings"
	"testing"
)

func TestParseMemInfo(t *testing.T) {
	total, avail, err := parseMemInfo(strings.NewReader("MemTotal:       64775184 kB\nMemFree:  1 kB\nMemAvailable:   62916612 kB\n"))
	if err != nil || total != 63257 || avail != 61442 {
		t.Fatalf("got %d %d %v", total, avail, err)
	}
	if _, _, err := parseMemInfo(strings.NewReader("MemTotal: 1 kB\n")); err == nil {
		t.Fatal("no error without MemAvailable")
	}
}

func TestParseAnonymous(t *testing.T) {
	rollup := "55d0c0a00000-7ffd5b5f8000 ---p 00000000 00:00 0  [rollup]\nRss:  480000 kB\nPss:   60000 kB\nAnonymous:   14336 kB\nSwap: 0 kB\n"
	got, err := parseAnonymous(strings.NewReader(rollup))
	if err != nil || got != 14336<<10 {
		t.Fatalf("got %d %v", got, err)
	}
	if _, err := parseAnonymous(strings.NewReader("Rss: 1 kB\n")); err == nil {
		t.Fatal("no error without Anonymous")
	}
	if got, err := parseAnonymous(strings.NewReader("")); err != nil || got != 0 {
		t.Fatalf("empty rollup: %d %v", got, err)
	}
	if _, err := parseAnonymous(strings.NewReader("Anonymous: x kB\n")); err == nil {
		t.Fatal("no error for a bad number")
	}
}

func TestPrivateMemoryBytesOfSelf(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("needs /proc")
	}
	got, err := PrivateMemoryBytes(os.Getpid())
	if err != nil || got == 0 {
		t.Fatalf("got %d %v", got, err)
	}
	if _, err := PrivateMemoryBytes(1 << 30); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("missing pid: %v", err)
	}
}

func TestAboveEviction(t *testing.T) {
	for _, tc := range []struct{ avail, total, want uint64 }{
		{avail: 50, total: 100, want: 40},
		{avail: 10, total: 100, want: 0},
		{avail: 5, total: 100, want: 0},
		{avail: 0, total: 0, want: 0},
	} {
		if got := aboveEviction(tc.avail, tc.total); got != tc.want {
			t.Errorf("aboveEviction(%d, %d) = %d, want %d", tc.avail, tc.total, got, tc.want)
		}
	}
}
