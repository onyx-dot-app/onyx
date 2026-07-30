//go:build unix

package resources

import "golang.org/x/sys/unix"

// DiskAvailableGB returns the free space at path in GB (-1 = unknown).
func DiskAvailableGB(path string) int {
	var st unix.Statfs_t
	if err := unix.Statfs(path, &st); err != nil {
		return -1
	}
	return int(uint64(st.Bavail) * uint64(st.Bsize) / (1 << 30))
}
