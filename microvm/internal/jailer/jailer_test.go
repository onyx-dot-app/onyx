package jailer

import (
	"slices"
	"strings"
	"testing"
)

func TestArgv(t *testing.T) {
	c := Command{
		JailerBin: "/d/bin/v1/jailer", FirecrackerBin: "/d/bin/v1/firecracker",
		Layout: Layout{ChrootBase: "/d/jail"}, Slice: "fcvms.slice", HostMountNS: true,
	}
	id := "11111111-1111-4111-8111-111111111111"
	argv, err := c.Argv(id, 1000005, VMLimits(2, 4096, 128))
	if err != nil {
		t.Fatal(err)
	}
	want := []string{
		"nsenter", "-t", "1", "-m", "--",
		"systemd-run", "--quiet", "--scope", "--collect", "--slice=fcvms.slice", "--unit=fcvm-" + id + ".scope",
		"--property=MemoryMax=4429185024", "--property=CPUQuota=200%", "--",
		"/d/bin/v1/jailer", "--id", id, "--exec-file", "/d/bin/v1/firecracker", "--uid", "1000005", "--gid", "1000005",
		"--chroot-base-dir", "/d/jail", "--cgroup-version", "2", "--new-pid-ns", "--",
		"--api-sock", "/api.sock", "--level", "Warning", "--log-path", "/fc.log",
	}
	if !slices.Equal(argv, want) {
		t.Fatalf("argv\n got %q\nwant %q", argv, want)
	}
	if got := c.Layout.HostPath(id, APISock); got != "/d/jail/firecracker/"+id+"/root/api.sock" {
		t.Fatalf("host path %s", got)
	}
	for _, bad := range []string{"", "../x", "A", "a/b", "a b"} {
		if _, err := c.Argv(bad, 1, Limits{}); err == nil {
			t.Errorf("Argv accepted id %q", bad)
		}
	}
}

func TestSliceMemoryMax(t *testing.T) {
	for _, c := range []struct {
		total   uint64
		percent uint
		want    uint64
	}{
		{65536, 85, 55705 << 20},
		{16384, 100, 16384 << 20},
		{15995, 85, 13595 << 20},
	} {
		if got := SliceMemoryMax(c.total, c.percent); got != c.want {
			t.Errorf("SliceMemoryMax(%d, %d) = %d, want %d", c.total, c.percent, got, c.want)
		}
	}
	c := Command{Slice: "fcvms.slice", HostMountNS: true}
	want := []string{"nsenter", "-t", "1", "-m", "--", "systemctl", "set-property", "--runtime", "fcvms.slice", "MemoryMax=58410926080"}
	if got := c.SliceMemoryMaxArgv(55705 << 20); !slices.Equal(got, want) {
		t.Fatalf("argv\n got %q\nwant %q", got, want)
	}
}

func TestVMLimits(t *testing.T) {
	for _, c := range []struct {
		vcpus, mem, over uint32
		want             Limits
	}{
		{2, 4096, 128, Limits{MemoryMaxBytes: 4224 << 20, CPUQuotaPercent: 200}},
		{1, 512, 0, Limits{MemoryMaxBytes: 512 << 20, CPUQuotaPercent: 100}},
		{32, 65536, DefaultMemOverheadMiB, Limits{MemoryMaxBytes: (65536 + DefaultMemOverheadMiB) << 20, CPUQuotaPercent: 3200}},
	} {
		if got := VMLimits(c.vcpus, c.mem, c.over); got != c.want {
			t.Errorf("VMLimits(%d, %d, %d) = %+v, want %+v", c.vcpus, c.mem, c.over, got, c.want)
		}
	}
	// No limits: no properties.
	c := Command{JailerBin: "j", FirecrackerBin: "f", Layout: Layout{ChrootBase: "/d"}, Slice: "s"}
	argv, err := c.Argv("11111111-1111-4111-8111-111111111111", 1, Limits{})
	if err != nil {
		t.Fatal(err)
	}
	for _, a := range argv {
		if strings.HasPrefix(a, "--property=") {
			t.Errorf("unexpected %s", a)
		}
	}
}

func TestUIDPool(t *testing.T) {
	p, err := NewUIDPool(100, 3)
	if err != nil {
		t.Fatal(err)
	}
	a, _ := p.Get()
	b, _ := p.Get()
	c, _ := p.Get()
	if _, ok := p.Get(); ok {
		t.Fatal("pool gave a 4th UID")
	}
	if a != 100 || b != 101 || c != 102 {
		t.Fatalf("got %d %d %d", a, b, c)
	}
	p.Put(b)
	if got, ok := p.Get(); !ok || got != 101 {
		t.Fatalf("after put: %d %v", got, ok)
	}
	if p.Reserve(99) || p.Reserve(103) || p.Reserve(100) {
		t.Fatal("Reserve accepted an out-of-range or used UID")
	}
	p.Put(100)
	if !p.Reserve(100) || p.InUse() != 3 {
		t.Fatalf("reserve: in use %d", p.InUse())
	}
	if _, err := NewUIDPool(0, 1); err == nil {
		t.Fatal("pool with base 0")
	}
}
