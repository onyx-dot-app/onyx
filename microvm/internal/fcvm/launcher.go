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
}

// FileSource is a file to put in a VM chroot.
type FileSource struct {
	// Name is the file name in the chroot root.
	Name string
	// Src is the host path of the source file.
	Src string
	// Link hard-links Src (shared, read-only). Otherwise Src is copied with
	// a reflink and owned by the VM UID.
	Link bool
	// Size extends a reflink copy to this size. 0 keeps the source size.
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
