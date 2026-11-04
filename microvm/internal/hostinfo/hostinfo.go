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

// DiskFreeBytes returns the space that is free for root on the data dir.
func (s Stats) DiskFreeBytes() (uint64, error) { return diskFree(s.DataDir) }

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
