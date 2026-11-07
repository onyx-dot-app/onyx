package sysops

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"os"
	"strings"
	"time"
	"unsafe"

	"golang.org/x/sys/unix"
)

// SetClock sets CLOCK_REALTIME.
func SetClock(t time.Time) error {
	ts := unix.NsecToTimespec(t.UnixNano())
	return unix.ClockSettime(unix.CLOCK_REALTIME, &ts)
}

// AddEntropy adds b to the kernel RNG with RNDADDENTROPY (credited). If
// the ioctl fails, it writes b to /dev/urandom (mixed in, not credited) and
// returns the ioctl error as notCredited, for the log.
func AddEntropy(b []byte) (credited bool, notCredited, err error) {
	f, err := os.OpenFile("/dev/urandom", os.O_WRONLY, 0)
	if err != nil {
		return false, nil, err
	}
	defer func() { _ = f.Close() }()
	// struct rand_pool_info { int entropy_count; int buf_size; __u32 buf[]; }
	info := make([]byte, 8+len(b))
	binary.NativeEndian.PutUint32(info[0:], uint32(len(b)*8))
	binary.NativeEndian.PutUint32(info[4:], uint32(len(b)))
	copy(info[8:], b)
	_, _, errno := unix.Syscall(unix.SYS_IOCTL, f.Fd(), unix.RNDADDENTROPY, uintptr(unsafe.Pointer(&info[0])))
	if errno == 0 {
		return true, nil, nil
	}
	ioctlErr := fmt.Errorf("RNDADDENTROPY: %w", errno)
	if _, err := f.Write(b); err != nil {
		return false, ioctlErr, fmt.Errorf("%w; write: %w", ioctlErr, err)
	}
	return false, ioctlErr, nil
}

// _IOW('f', 16, __u64)
const ext4IocResizeFS = 0x40086610

// GrowFS grows the ext4 file system mounted at mountPoint to the size of
// its block device (online, like resize2fs). It returns the file system
// size before and after. A mount point that is not ext4 is an error.
func GrowFS(mountPoint string) (oldBytes, newBytes uint64, err error) {
	dev, fstype, err := mountSource(mountPoint)
	if err != nil {
		return 0, 0, err
	}
	if fstype != "ext4" {
		return 0, 0, fmt.Errorf("%s is %s, not ext4", mountPoint, fstype)
	}
	var st unix.Statfs_t
	if err := unix.Statfs(mountPoint, &st); err != nil {
		return 0, 0, err
	}
	bsize := uint64(st.Bsize)
	oldBytes = st.Blocks * bsize
	df, err := os.Open(dev)
	if err != nil {
		return 0, 0, err
	}
	var devBytes uint64
	_, _, errno := unix.Syscall(unix.SYS_IOCTL, df.Fd(), unix.BLKGETSIZE64, uintptr(unsafe.Pointer(&devBytes)))
	_ = df.Close()
	if errno != 0 {
		return 0, 0, fmt.Errorf("BLKGETSIZE64 %s: %w", dev, errno)
	}
	mp, err := os.Open(mountPoint)
	if err != nil {
		return 0, 0, err
	}
	defer func() { _ = mp.Close() }()
	blocks := devBytes / bsize
	_, _, errno = unix.Syscall(unix.SYS_IOCTL, mp.Fd(), ext4IocResizeFS, uintptr(unsafe.Pointer(&blocks)))
	if errno != 0 {
		return 0, 0, fmt.Errorf("EXT4_IOC_RESIZE_FS %s to %d blocks: %w", mountPoint, blocks, errno)
	}
	if err := unix.Statfs(mountPoint, &st); err != nil {
		return 0, 0, err
	}
	return oldBytes, st.Blocks * uint64(st.Bsize), nil
}

// mountSource returns the source and type of the mount at mountPoint.
func mountSource(mountPoint string) (source, fstype string, err error) {
	f, err := os.Open("/proc/self/mountinfo")
	if err != nil {
		return "", "", err
	}
	defer func() { _ = f.Close() }()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		// id parent major:minor root mountpoint options [optional...] - fstype source superoptions
		fields := strings.Fields(sc.Text())
		if len(fields) < 10 || fields[4] != mountPoint {
			continue
		}
		for i := 6; i < len(fields)-2; i++ {
			if fields[i] == "-" {
				// The last match wins: a later mount hides an earlier one.
				fstype, source = fields[i+1], fields[i+2]
				break
			}
		}
	}
	if err := sc.Err(); err != nil {
		return "", "", err
	}
	if source == "" {
		return "", "", fmt.Errorf("%s is not a mount point", mountPoint)
	}
	return source, fstype, nil
}

// EnsureCgroup2 mounts cgroup v2 at path unless it is already there.
func EnsureCgroup2(path string) error {
	var st unix.Statfs_t
	if err := unix.Statfs(path, &st); err == nil && st.Type == unix.CGROUP2_SUPER_MAGIC {
		return nil
	}
	if err := os.MkdirAll(path, 0o755); err != nil {
		return err
	}
	return unix.Mount("cgroup2", path, "cgroup2", unix.MS_NOSUID|unix.MS_NODEV|unix.MS_NOEXEC, "")
}
