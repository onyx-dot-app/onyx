package sysops

import (
	"context"
	"errors"
	"fmt"
	"os"
	"time"
	"unsafe"

	"golang.org/x/sys/unix"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
)

// moveMountBeneath is MOVE_MOUNT_BENEATH (Linux 6.5); x/sys/unix does not
// define it yet.
const moveMountBeneath = 0x00000200

// Managed implements guestd.ManagedOps with the Linux mount API.
type Managed struct{}

var _ guestd.ManagedOps = Managed{}

// Probe implements guestd.ManagedOps.
func (Managed) Probe(dev string) (guestd.DevState, error) {
	var st unix.Stat_t
	if err := unix.Stat(dev, &st); err != nil {
		if errors.Is(err, unix.ENOENT) {
			return guestd.DevState{}, nil
		}
		return guestd.DevState{}, err
	}
	if st.Mode&unix.S_IFMT != unix.S_IFBLK {
		return guestd.DevState{}, fmt.Errorf("%s is not a block device", dev)
	}
	out := guestd.DevState{Present: true, Rdev: st.Rdev}
	// O_DIRECT reads the device, not the guest's cached blocks.
	fd, err := unix.Open(dev, unix.O_RDONLY|unix.O_DIRECT|unix.O_CLOEXEC, 0)
	if err != nil {
		return out, fmt.Errorf("open %s: %w", dev, err)
	}
	defer func() { _ = unix.Close(fd) }()
	if out.Size, err = devSize(fd); err != nil {
		return out, fmt.Errorf("%s: %w", dev, err)
	}
	if out.Size >= 4096 {
		buf := alignedBuf(4096)
		if n, err := unix.Pread(fd, buf, 0); err == nil && n == len(buf) {
			out.UUID = ext4UUID(buf)
		}
	}
	// An exclusive open fails with EBUSY while a file system holds the
	// device, also a lazily detached one that still has open files.
	efd, err := unix.Open(dev, unix.O_RDONLY|unix.O_EXCL|unix.O_CLOEXEC, 0)
	switch {
	case err == nil:
		_ = unix.Close(efd)
	case errors.Is(err, unix.EBUSY):
		out.InUse = true
	default:
		return out, fmt.Errorf("open %s exclusive: %w", dev, err)
	}
	return out, nil
}

func devSize(fd int) (uint64, error) {
	var n uint64
	if _, _, errno := unix.Syscall(unix.SYS_IOCTL, uintptr(fd), unix.BLKGETSIZE64, uintptr(unsafe.Pointer(&n))); errno != 0 {
		return 0, fmt.Errorf("BLKGETSIZE64: %w", errno)
	}
	return n, nil
}

// alignedBuf returns n bytes aligned to 4096, for O_DIRECT.
func alignedBuf(n int) []byte {
	raw := make([]byte, n+4096)
	off := 4096 - int(uintptr(unsafe.Pointer(&raw[0]))&4095)
	if off == 4096 {
		off = 0
	}
	return raw[off : off+n]
}

// MountedDev implements guestd.ManagedOps.
func (Managed) MountedDev(mountPoint string) (uint64, bool, error) {
	_, _, err := mountSource(mountPoint)
	if err != nil {
		var st unix.Stat_t
		if serr := unix.Stat(mountPoint, &st); serr != nil {
			return 0, false, serr
		}
		return 0, false, nil
	}
	var st unix.Stat_t
	if err := unix.Stat(mountPoint, &st); err != nil {
		return 0, false, err
	}
	return st.Dev, true, nil
}

// WaitSize implements guestd.ManagedOps. Firecracker sends a config change
// after PATCH /drives; the guest updates the capacity in a work queue.
func (Managed) WaitSize(ctx context.Context, dev string, size uint64) error {
	fd, err := unix.Open(dev, unix.O_RDONLY|unix.O_CLOEXEC, 0)
	if err != nil {
		return err
	}
	defer func() { _ = unix.Close(fd) }()
	for {
		got, err := devSize(fd)
		if err != nil {
			return err
		}
		if got == size {
			return nil
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("size is %d bytes, want %d: %w", got, size, ctx.Err())
		case <-time.After(2 * time.Millisecond):
		}
	}
}

// Flush implements guestd.ManagedOps (BLKFLSBUF, like blockdev --flushbufs).
func (Managed) Flush(dev string) error {
	f, err := os.Open(dev)
	if err != nil {
		return err
	}
	defer func() { _ = f.Close() }()
	if _, _, errno := unix.Syscall(unix.SYS_IOCTL, f.Fd(), unix.BLKFLSBUF, 0); errno != 0 {
		return fmt.Errorf("BLKFLSBUF: %w", errno)
	}
	return nil
}

// Mount implements guestd.ManagedOps. It makes a detached mount with
// fsopen/fsmount and attaches it with move_mount.
func (Managed) Mount(dev, mountPoint string, beneath bool) error {
	fsfd, err := unix.Fsopen("ext4", unix.FSOPEN_CLOEXEC)
	if err != nil {
		return fmt.Errorf("fsopen: %w", err)
	}
	defer func() { _ = unix.Close(fsfd) }()
	cfg := func(what string, err error) error {
		if err == nil {
			return nil
		}
		return fmt.Errorf("fsconfig %s: %w%s", what, err, fsLog(fsfd))
	}
	if err := cfg("source", unix.FsconfigSetString(fsfd, "source", dev)); err != nil {
		return err
	}
	for _, flag := range []string{"ro", "noload"} {
		if err := cfg(flag, unix.FsconfigSetFlag(fsfd, flag)); err != nil {
			return err
		}
	}
	if err := cfg("create", unix.FsconfigCreate(fsfd)); err != nil {
		return err
	}
	attrs := unix.MOUNT_ATTR_RDONLY | unix.MOUNT_ATTR_NOSUID | unix.MOUNT_ATTR_NODEV | unix.MOUNT_ATTR_NOEXEC
	mfd, err := unix.Fsmount(fsfd, unix.FSMOUNT_CLOEXEC, attrs)
	if err != nil {
		return fmt.Errorf("fsmount: %w%s", err, fsLog(fsfd))
	}
	defer func() { _ = unix.Close(mfd) }()
	if err := unix.MountSetattr(mfd, "", unix.AT_EMPTY_PATH, &unix.MountAttr{Propagation: unix.MS_PRIVATE}); err != nil {
		return fmt.Errorf("mount_setattr private: %w", err)
	}
	flags := unix.MOVE_MOUNT_F_EMPTY_PATH
	if beneath {
		flags |= moveMountBeneath
	}
	if err := unix.MoveMount(mfd, "", unix.AT_FDCWD, mountPoint, flags); err != nil {
		return fmt.Errorf("move_mount (beneath %v): %w", beneath, err)
	}
	return nil
}

// fsLog reads the messages that the file system context logged.
func fsLog(fsfd int) string {
	var out string
	buf := make([]byte, 512)
	for range 8 {
		n, err := unix.Read(fsfd, buf)
		if err != nil || n <= 0 {
			break
		}
		out += "; " + string(buf[:n])
	}
	return out
}

// DetachTop implements guestd.ManagedOps.
func (Managed) DetachTop(mountPoint string) error {
	return unix.Unmount(mountPoint, unix.MNT_DETACH)
}

// MountedOn implements guestd.ManagedOps.
func (Managed) MountedOn(mountPoint string, rdev uint64) (bool, error) {
	raw, err := os.ReadFile("/proc/self/mountinfo")
	if err != nil {
		return false, err
	}
	return mountedOn(string(raw), mountPoint, unix.Major(rdev), unix.Minor(rdev)), nil
}
