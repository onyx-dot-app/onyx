// Package hostinfo reads node facts from /proc and the kernel.
package hostinfo

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
)

// Stats implements agent.HostStats for a data dir.
type Stats struct {
	DataDir string
	// NodeDir is the node file system under a loop store data dir, or "".
	NodeDir string
}

// MemInfo returns MemTotal and MemAvailable in MiB.
func (s Stats) MemInfo() (uint64, uint64, error) {
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return 0, 0, err
	}
	defer func() { _ = f.Close() }()
	return parseMemInfo(f)
}

func parseMemInfo(r io.Reader) (total, avail uint64, err error) {
	var haveTotal, haveAvail bool
	sc := bufio.NewScanner(r)
	for sc.Scan() {
		fields := strings.Fields(sc.Text())
		if len(fields) < 2 {
			continue
		}
		kib, convErr := strconv.ParseUint(fields[1], 10, 64)
		if convErr != nil {
			continue
		}
		switch fields[0] {
		case "MemTotal:":
			total, haveTotal = kib>>10, true
		case "MemAvailable:":
			avail, haveAvail = kib>>10, true
		}
	}
	if err := sc.Err(); err != nil {
		return 0, 0, err
	}
	if !haveTotal || !haveAvail {
		return 0, 0, fmt.Errorf("meminfo has no MemTotal or MemAvailable")
	}
	return total, avail, nil
}

// DiskFreeBytes returns the space that is free for root on the data dir. On
// a loop store (a sparse image) it is at most the space on NodeDir above the
// 10% that kubelet keeps free (nodefs hard eviction).
func (s Stats) DiskFreeBytes() (uint64, error) {
	free, err := diskFree(s.DataDir)
	if err != nil || s.NodeDir == "" {
		return free, err
	}
	avail, total, err := diskAvail(s.NodeDir)
	if err != nil {
		return 0, err
	}
	return min(free, aboveEviction(avail, total)), nil
}

// aboveEviction is avail minus 10% of total, or 0.
func aboveEviction(avail, total uint64) uint64 {
	if reserve := total / 10; avail > reserve {
		return avail - reserve
	}
	return 0
}

// CPUModel returns the first "model name" in /proc/cpuinfo.
func CPUModel() string {
	f, err := os.Open("/proc/cpuinfo")
	if err != nil {
		return ""
	}
	defer func() { _ = f.Close() }()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		k, v, ok := strings.Cut(sc.Text(), ":")
		if ok && strings.TrimSpace(k) == "model name" {
			return strings.TrimSpace(v)
		}
	}
	return ""
}

// KernelRelease returns the host kernel release.
func KernelRelease() string {
	raw, err := os.ReadFile("/proc/sys/kernel/osrelease")
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(raw))
}

// PrivateMemoryBytes returns the Anonymous bytes of /proc/<pid>/smaps_rollup.
// For a Firecracker process that maps its snapshot memory file, that is the
// guest pages it wrote (copy-on-write) plus its own heap. Pages it only read
// are page cache of the file and are not counted.
func PrivateMemoryBytes(pid int) (uint64, error) {
	f, err := os.Open(fmt.Sprintf("/proc/%d/smaps_rollup", pid))
	if err != nil {
		return 0, err
	}
	defer func() { _ = f.Close() }()
	return parseAnonymous(f)
}

func parseAnonymous(r io.Reader) (uint64, error) {
	sc := bufio.NewScanner(r)
	lines := 0
	for sc.Scan() {
		lines++
		fields := strings.Fields(sc.Text())
		if len(fields) < 2 || fields[0] != "Anonymous:" {
			continue
		}
		kib, err := strconv.ParseUint(fields[1], 10, 64)
		if err != nil {
			return 0, fmt.Errorf("smaps_rollup Anonymous %q: %w", fields[1], err)
		}
		return kib << 10, nil
	}
	if err := sc.Err(); err != nil {
		return 0, err
	}
	if lines == 0 {
		// A zombie process has an empty smaps_rollup and no memory.
		return 0, nil
	}
	return 0, fmt.Errorf("smaps_rollup has no Anonymous line")
}
