//go:build linux

package guestlog

import (
	"os"

	"golang.org/x/sys/unix"
)

// punchHole frees the disk blocks of fh before end and keeps the file size.
func punchHole(fh *os.File, end int64) error {
	return unix.Fallocate(int(fh.Fd()), unix.FALLOC_FL_PUNCH_HOLE|unix.FALLOC_FL_KEEP_SIZE, 0, end)
}
