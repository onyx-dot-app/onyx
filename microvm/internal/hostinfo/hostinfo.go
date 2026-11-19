// Package hostinfo reads node facts from /proc and the kernel.
package hostinfo

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// Stats implements agent.HostStats for a data dir.
type Stats struct {
	DataDir string
	// NodeDir is the node file system under a loop store data dir, or "".
	NodeDir string
	// SliceDir is the host cgroup directory of the VM slice (SliceCgroupDir),
	// or "": no slice limit and no OOM count.
	SliceDir string
	// SliceLimitBytes is the memory.max that the agent set on the slice (0:
	// none). It is the room while the slice has no cgroup yet.
	SliceLimitBytes uint64
}

// SliceCgroupDir returns the cgroup directory of a systemd slice under the
// cgroup2 mount root: "a-b.slice" is in "a.slice/a-b.slice".
func SliceCgroupDir(root, slice string) string {
	name := strings.TrimSuffix(slice, ".slice")
	dir := root
	for i := range len(name) {
		if name[i] == '-' {
			dir = filepath.Join(dir, name[:i]+".slice")
		}
	}
	return filepath.Join(dir, slice)
}

// SliceRoomMiB returns the memory that the VM slice can still take before
// its memory.max: memory.max minus the slice's memory that the kernel cannot
// drop (memory.current less its file page cache). limited is false when the
// slice has no limit or Stats has no SliceDir. While the slice has no cgroup
// yet (systemd makes it when the first VM scope starts), the room is
// SliceLimitBytes.
func (s Stats) SliceRoomMiB() (room uint64, limited bool, err error) {
	if s.SliceDir == "" {
		return 0, false, nil
	}
	var raw [3][]byte
	for i, name := range []string{"memory.max", "memory.current", "memory.stat"} {
		if raw[i], err = os.ReadFile(filepath.Join(s.SliceDir, name)); err != nil {
			if i == 0 && errors.Is(err, fs.ErrNotExist) {
				return s.SliceLimitBytes >> 20, s.SliceLimitBytes > 0, nil
			}
			return 0, false, err
		}
	}
	return sliceRoom(string(raw[0]), string(raw[1]), string(raw[2]))
}

func sliceRoom(maxRaw, currentRaw, stat string) (uint64, bool, error) {
	maxRaw = strings.TrimSpace(maxRaw)
	if maxRaw == "max" {
		return 0, false, nil
	}
	limit, err := strconv.ParseUint(maxRaw, 10, 64)
	if err != nil {
		return 0, false, fmt.Errorf("memory.max %q: %w", maxRaw, err)
	}
	current, err := strconv.ParseUint(strings.TrimSpace(currentRaw), 10, 64)
	if err != nil {
		return 0, false, fmt.Errorf("memory.current %q: %w", currentRaw, err)
	}
	var file uint64
	for _, key := range []string{"active_file", "inactive_file"} {
		v, err := statValue(stat, key)
		if err != nil {
			return 0, false, err
		}
		file += v
	}
	used := current - min(file, current)
	if used >= limit {
		return 0, true, nil
	}
	return (limit - used) >> 20, true, nil
}

// SliceOOMKills returns oom_kill of the VM slice's memory.events: the
// processes that the kernel OOM-killed in the slice and in its VM scopes.
func (s Stats) SliceOOMKills() (uint64, error) {
	if s.SliceDir == "" {
		return 0, nil
	}
	raw, err := os.ReadFile(filepath.Join(s.SliceDir, "memory.events"))
	if errors.Is(err, fs.ErrNotExist) {
		return 0, nil
	}
	if err != nil {
		return 0, err
	}
	return statValue(string(raw), "oom_kill")
}

// statValue returns the value of key in a cgroup "key value" file.
func statValue(body, key string) (uint64, error) {
	for _, line := range strings.Split(body, "\n") {
		k, v, ok := strings.Cut(line, " ")
		if ok && k == key {
			n, err := strconv.ParseUint(strings.TrimSpace(v), 10, 64)
			if err != nil {
				return 0, fmt.Errorf("%s %q: %w", key, v, err)
			}
			return n, nil
		}
	}
	return 0, fmt.Errorf("no %s", key)
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
