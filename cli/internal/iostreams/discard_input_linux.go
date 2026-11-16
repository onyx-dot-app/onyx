//go:build linux

package iostreams

import (
	"os"

	"golang.org/x/sys/unix"
)

// DiscardPendingInput drops input that a terminal received but nobody read,
// so text typed before a prompt cannot answer it.
func DiscardPendingInput(f *os.File) {
	fd := int(f.Fd())
	if termios, err := unix.IoctlGetTermios(fd, unix.TCGETS); err == nil {
		_ = unix.IoctlSetTermios(fd, unix.TCSETSF, termios)
	}
}
