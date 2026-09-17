package resources

import (
	"net"
	"strconv"
	"strings"
	"testing"
)

func TestDockerInfoMemoryMB(t *testing.T) {
	cases := map[string]int{
		"Total Memory: 7.667GiB":                     7851, // 7.667 * 1024
		" Total Memory: 512MiB":                      512,
		"Kernel Version: 6.1\n Total Memory: 2GiB\n": 2048,
		"no memory line":                             0,
		"":                                           0,
	}
	for in, want := range cases {
		if got := dockerInfoMemoryMB(in); got != want {
			t.Errorf("dockerInfoMemoryMB(%q) = %d, want %d", in, got, want)
		}
	}
}

func TestFormatMemory(t *testing.T) {
	cases := map[int]string{
		0:     "unknown",
		512:   "512MB",
		1024:  "~1.0GB",
		15872: "~15.5GB",
	}
	for in, want := range cases {
		if got := FormatMemory(in); got != want {
			t.Errorf("FormatMemory(%d) = %q, want %q", in, got, want)
		}
	}
}

func TestFindAvailablePortSkipsBusyPort(t *testing.T) {
	// Occupy a port, then scan starting at it: the scan must move past.
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer func() { _ = l.Close() }()
	go func() {
		for {
			conn, err := l.Accept()
			if err != nil {
				return
			}
			_ = conn.Close()
		}
	}()

	_, portStr, err := net.SplitHostPort(l.Addr().String())
	if err != nil {
		t.Fatalf("split: %v", err)
	}
	busy, err := strconv.Atoi(portStr)
	if err != nil {
		t.Fatalf("atoi: %v", err)
	}

	got := FindAvailablePort(busy)
	if got == busy {
		t.Fatalf("returned the busy port %d", busy)
	}
	if got < busy || got > busy+100 {
		t.Fatalf("unexpected port %d for busy %d", got, busy)
	}
}

func TestDiskAvailableGBOnCwd(t *testing.T) {
	got := DiskAvailableGB(".")
	if got < 0 {
		t.Skip("disk space unknown in this environment")
	}
	// Sanity only: a working checkout has some free space.
	if got == 0 && !strings.Contains(t.Name(), "full-disk") {
		t.Logf("0GB free reported — plausible on a nearly full disk")
	}
}
