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
