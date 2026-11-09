package managed

import (
	"fmt"
	"os"

	"golang.org/x/sys/unix"
)

// TmpfsStager unpacks each bundle into its own tmpfs, sized to the bundle
// limit plus room for directories, so the files stay in memory and a bad
// bundle cannot fill the node's disk.
type TmpfsStager struct{}

// Stage implements Stager.
func (TmpfsStager) Stage(dir string, maxBytes int64) (string, func() error, error) {
	p, err := os.MkdirTemp(dir, ".stage-")
	if err != nil {
		return "", nil, err
	}
	size := maxBytes + maxBytes/8 + 64<<20
	opts := fmt.Sprintf("size=%d,mode=0700", size)
	if err := unix.Mount("craft-managed-stage", p, "tmpfs", unix.MS_NODEV|unix.MS_NOSUID|unix.MS_NOEXEC, opts); err != nil {
		_ = os.Remove(p)
		return "", nil, fmt.Errorf("mount tmpfs on %s: %w", p, err)
	}
	return p, func() error {
		if err := Unmount(p); err != nil {
			return err
		}
		return os.Remove(p)
	}, nil
}

// Unmount detaches a stage tmpfs. A directory that is not a mount point is
// not an error.
func Unmount(p string) error {
	if err := unix.Unmount(p, unix.MNT_DETACH); err != nil && err != unix.EINVAL && err != unix.ENOENT {
		return fmt.Errorf("unmount %s: %w", p, err)
	}
	return nil
}
