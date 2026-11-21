package hostinfo

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
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

func TestSliceCgroupDir(t *testing.T) {
	for slice, want := range map[string]string{
		"fcvms.slice":    "/cg/fcvms.slice",
		"craft-fc.slice": "/cg/craft.slice/craft-fc.slice",
		"a-b-c.slice":    "/cg/a.slice/a-b.slice/a-b-c.slice",
	} {
		if got := SliceCgroupDir("/cg", slice); got != want {
			t.Errorf("%s: %s, want %s", slice, got, want)
		}
	}
}

func TestSliceRoom(t *testing.T) {
	stat := "anon 100\nfile 3221225472\nactive_file 1073741824\ninactive_file 2147483648\nshmem 0\n"
	// 10 GiB limit, 7 GiB in use of which 3 GiB is page cache: 6 GiB left.
	room, limited, err := sliceRoom("10737418240\n", "7516192768\n", stat)
	if err != nil || !limited || room != 6<<10 {
		t.Fatalf("room %d limited %v err %v", room, limited, err)
	}
	if _, limited, err := sliceRoom("max\n", "1", stat); err != nil || limited {
		t.Fatalf("no limit: limited %v err %v", limited, err)
	}
	// Over the limit (the kernel is reclaiming): no room.
	if room, limited, err := sliceRoom("1073741824", "8589934592", stat); err != nil || !limited || room != 0 {
		t.Fatalf("over the limit: room %d limited %v err %v", room, limited, err)
	}
	if _, _, err := sliceRoom("1073741824", "1", "anon 1\n"); err == nil {
		t.Fatal("memory.stat without file counters accepted")
	}
}

func TestSliceFiles(t *testing.T) {
	dir := t.TempDir()
	for name, body := range map[string]string{
		"memory.max":     "4294967296\n",
		"memory.current": "1073741824\n",
		"memory.stat":    "active_file 0\ninactive_file 0\n",
		"memory.events":  "low 0\nhigh 0\nmax 4\noom 2\noom_kill 2\noom_group_kill 0\n",
	} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	s := Stats{SliceDir: dir}
	if room, limited, err := s.SliceRoomMiB(); err != nil || !limited || room != 3<<10 {
		t.Fatalf("room %d limited %v err %v", room, limited, err)
	}
	if n, err := s.SliceOOMKills(); err != nil || n != 2 {
		t.Fatalf("oom kills %d %v", n, err)
	}
	// Another missing file fails closed.
	partial := filepath.Join(dir, "partial.slice")
	if err := os.MkdirAll(partial, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(partial, "memory.max"), []byte("max\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := (Stats{SliceDir: partial, SliceLimitBytes: 1 << 30}).SliceRoomMiB(); err == nil {
		t.Fatal("a slice without memory.current read as fine")
	}
	missing := filepath.Join(dir, "not-started.slice")
	// Before the first VM scope, the room is the limit that the agent set.
	if room, limited, err := (Stats{SliceDir: missing, SliceLimitBytes: 8 << 30}).SliceRoomMiB(); err != nil || !limited || room != 8<<10 {
		t.Fatalf("no cgroup yet: room %d limited %v err %v", room, limited, err)
	}
	for _, s := range []Stats{{}, {SliceDir: missing}} {
		if _, limited, err := s.SliceRoomMiB(); err != nil || limited {
			t.Fatalf("%q: limited %v err %v", s.SliceDir, limited, err)
		}
		if n, err := s.SliceOOMKills(); err != nil || n != 0 {
			t.Fatalf("%q: oom kills %d %v", s.SliceDir, n, err)
		}
	}
}
