package files

import (
	"os"

	"golang.org/x/sys/unix"
)

// renameAt renames from to to inside the open directory dir, or with
// exchange swaps the two in one step.
func renameAt(dir *os.File, from, to string, exchange bool) error {
	flags := uint(unix.RENAME_NOREPLACE)
	if exchange {
		flags = unix.RENAME_EXCHANGE
	}
	fd := int(dir.Fd())
	return fsErr(unix.Renameat2(fd, from, fd, to, flags))
}
