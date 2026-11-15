package scratch

import (
	"os"
	"syscall"
)

// nlink returns the link count of a file, or 1 if it is not known.
func nlink(st os.FileInfo) uint64 {
	if s, ok := st.Sys().(*syscall.Stat_t); ok {
		return uint64(s.Nlink)
	}
	return 1
}
