package fcvm

import (
	"io"
	"log/slog"
	"os"
	"strings"

	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
)

// Launcher starts VMs with the jailer. It implements agent.Launcher.
type Launcher struct {
	Cmd jailer.Command
	Log *slog.Logger
	// ProcFS is the proc file system that Adopt and Scan read. Empty means
	// /proc. Tests use a fake process table.
	ProcFS string
	// Cgroups says how to read the VM cgroups (DetectCgroupView). The zero
	// value is the host cgroup namespace.
	Cgroups CgroupView
	// MemOverheadMiB is the memory each VM scope gets on top of the guest
	// memory (memory.max). 0 means jailer.DefaultMemOverheadMiB.
	MemOverheadMiB uint32
}

// limits returns the cgroup limits of a VM scope: memory.max = guest memory
// + MemOverheadMiB, cpu.max = vcpus CPUs.
func (l *Launcher) limits(vcpus, memMiB uint32) jailer.Limits {
	over := l.MemOverheadMiB
	if over == 0 {
		over = jailer.DefaultMemOverheadMiB
	}
	return jailer.VMLimits(vcpus, memMiB, over)
}

// FileSource is a file to put in a VM chroot. Every file is a reflink copy,
// never a hard link: a snapshot/create truncates its target in place, so a
// link would let one VM destroy a template.
type FileSource struct {
	// Name is the file name in the chroot root.
	Name string
	// Src is the host path of the source file. It must be on the data dir
	// file system.
	Src string
	// VMOwned makes the copy owned by the VM UID with mode 0600 (a writable
	// drive). Otherwise it is root-owned with mode 0644 (read-only for the VM).
	VMOwned bool
	// Size extends a VMOwned copy to this size. 0 keeps the source size.
	Size int64
}

// tailBytes is how much of a log file tail returns.
const tailBytes = 2048

// tail returns the last 2 KiB of a log file. It reads only that part.
func tail(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return "(" + err.Error() + ")"
	}
	defer func() { _ = f.Close() }()
	if st, err := f.Stat(); err == nil && st.Size() > tailBytes {
		if _, err := f.Seek(-tailBytes, io.SeekEnd); err != nil {
			return "(" + err.Error() + ")"
		}
	}
	raw, err := io.ReadAll(io.LimitReader(f, tailBytes))
	if err != nil {
		return "(" + err.Error() + ")"
	}
	return strings.TrimSpace(string(raw))
}
