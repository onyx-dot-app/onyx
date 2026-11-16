//go:build linux

package hostinfo

import "golang.org/x/sys/unix"

func diskFree(dir string) (uint64, error) {
	var st unix.Statfs_t
	if err := unix.Statfs(dir, &st); err != nil {
		return 0, err
	}
	return st.Bfree * uint64(st.Bsize), nil
}

// diskAvail returns the space free for non-root users and the size of dir's
// file system.
func diskAvail(dir string) (avail, total uint64, err error) {
	var st unix.Statfs_t
	if err := unix.Statfs(dir, &st); err != nil {
		return 0, 0, err
	}
	return st.Bavail * uint64(st.Bsize), st.Blocks * uint64(st.Bsize), nil
}
