package files

import (
	"os"

	"golang.org/x/sys/unix"
)

// renameAt renames from to to in dir, or with exchange swaps them.
func renameAt(dir *os.File, from, to string, exchange bool) error {
	flags := uint(unix.RENAME_NOREPLACE)
	if exchange {
		flags = unix.RENAME_EXCHANGE
	}
	fd := int(dir.Fd())
	return fsErr(unix.Renameat2(fd, from, fd, to, flags))
}
