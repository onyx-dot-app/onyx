//go:build linux

package loopstore

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"

	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
)

const (
	sysBlock    = "/sys/block"
	loopControl = "/dev/loop-control"
	// discard gives the blocks of deleted files back to the sparse image.
	mountData = "discard"
)

// Ensure makes sure that DataDir supports reflink copies, in this mount
// namespace and, with HostMountNS, in the host mount namespace. It returns
// nil if the data dir has reflink without a store. Otherwise (Mode Auto) it
// makes the image if there is none, attaches it to a loop device if it is not
// attached, and mounts it at DataDir where it is not mounted.
func Ensure(o Options) (*Store, error) {
	err := scratch.ProbeReflink(o.DataDir)
	if err == nil {
		if err := checkHostView(o); err != nil {
			return nil, err
		}
		return mounted(o.DataDir), nil
	}
	if !errors.Is(err, scratch.ErrNoReflink) {
		return nil, err
	}
	if o.Mode == Off {
		return nil, fmt.Errorf("%w; mount an XFS file system with reflink (mkfs.xfs -m reflink=1) at %s, or use --loop-store=auto", err, o.DataDir)
	}
	// The data dir before the mount: the image and a root drive that the
	// init container put there stay reachable through this descriptor.
	lower, err := unix.Open(o.DataDir, unix.O_PATH|unix.O_DIRECTORY|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	defer func() { _ = unix.Close(lower) }()
	lowerRoot := fmt.Sprintf("/proc/self/fd/%d", lower)

	s := &Store{Image: filepath.Join(o.DataDir, ImageName)}
	if _, err := os.Stat(s.Image); errors.Is(err, fs.ErrNotExist) {
		if err := makeImage(o, s.Image); err != nil {
			return nil, fmt.Errorf("loop store %s: %w", s.Image, err)
		}
		s.Created = true
	} else if err != nil {
		return nil, err
	}
	st, err := os.Stat(s.Image)
	if err != nil {
		return nil, err
	}
	s.SizeBytes = st.Size()
	dev, rdev, release, err := attach(s.Image)
	if err != nil {
		return nil, fmt.Errorf("loop store %s: %w", s.Image, err)
	}
	defer release()
	s.Device = dev
	if err := mountBoth(o, dev, rdev); err != nil {
		return nil, fmt.Errorf("loop store %s on %s: %w", s.Image, dev, err)
	}
	if err := scratch.ProbeReflink(o.DataDir); err != nil {
		return nil, fmt.Errorf("loop store %s mounted at %s: %w", s.Image, o.DataDir, err)
	}
	if err := checkHostView(o); err != nil {
		return nil, err
	}
	if rel := rootfsRel(o.DataDir, o.RootfsDir); rel != "" {
		t0 := time.Now()
		copied, err := syncRootfs(lowerRoot, o.DataDir, rel)
		if err != nil {
			return nil, fmt.Errorf("copy the root drive into the loop store: %w", err)
		}
		if copied && o.Log != nil {
			o.Log.Info("copied the root drive into the loop store", "dir", o.RootfsDir, "ms", time.Since(t0).Milliseconds())
		}
	}
	return s, nil
}

// mounted describes the loop store that is already mounted at dataDir (for
// example after an agent restart), or returns nil for another file system.
func mounted(dataDir string) *Store {
	d, err := statDev(dataDir)
	if err != nil {
		return nil
	}
	sys := fmt.Sprintf("/sys/dev/block/%d:%d", unix.Major(d), unix.Minor(d))
	raw, err := os.ReadFile(filepath.Join(sys, "loop", "backing_file"))
	if err != nil {
		return nil
	}
	image := strings.TrimSpace(string(raw))
	if filepath.Base(image) != ImageName {
		return nil
	}
	s := &Store{Image: image}
	if name, err := os.Readlink(sys); err == nil {
		s.Device = "/dev/" + filepath.Base(name)
	}
	if raw, err := os.ReadFile(filepath.Join(sys, "size")); err == nil {
		if sectors, err := strconv.ParseInt(strings.TrimSpace(string(raw)), 10, 64); err == nil {
			s.SizeBytes = sectors * 512
		}
	}
	return s
}

// makeImage makes a sparse XFS image: first as <image>.new, then one rename,
// so an image is never half made.
func makeImage(o Options, image string) error {
	mkfs, err := exec.LookPath("mkfs.xfs")
	if err != nil {
		return fmt.Errorf("mkfs.xfs is not in the agent image (xfsprogs): %w", err)
	}
	var sfs unix.Statfs_t
	if err := unix.Statfs(o.DataDir, &sfs); err != nil {
		return err
	}
	size, err := imageSize(o.SizeGiB, sfs.Bavail*uint64(sfs.Bsize))
	if err != nil {
		return err
	}
	tmp := image + ".new"
	if err := os.Remove(tmp); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	f, err := os.OpenFile(tmp, os.O_RDWR|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	if err := f.Truncate(int64(size)); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	// -K: no discard of the new (sparse) file.
	if out, err := exec.Command(mkfs, "-q", "-K", "-m", "reflink=1", "-L", "craft-fc", tmp).CombinedOutput(); err != nil {
		_ = os.Remove(tmp)
		return fmt.Errorf("mkfs.xfs: %w: %s", err, strings.TrimSpace(string(out)))
	}
	f, err = os.Open(tmp)
	if err != nil {
		return err
	}
	err = f.Sync()
	_ = f.Close()
	if err != nil {
		return err
	}
	if err := os.Rename(tmp, image); err != nil {
		return err
	}
	if o.Log != nil {
		o.Log.Info("made the loop store image", "image", image, "gib", size>>30)
	}
	return nil
}

// attach returns the loop device of image: the one it is attached to, or a
// new one. release closes the new device; the mount keeps it, and
// LO_FLAGS_AUTOCLEAR detaches it after the last unmount.
func attach(image string) (dev string, rdev uint64, release func(), err error) {
	var st unix.Stat_t
	if err := unix.Stat(image, &st); err != nil {
		return "", 0, nil, err
	}
	if dev, rdev, ok := findAttached(st.Dev, st.Ino); ok {
		return dev, rdev, func() {}, nil
	}
	ctl, err := os.OpenFile(loopControl, os.O_RDWR, 0)
	if err != nil {
		return "", 0, nil, fmt.Errorf("no loop devices (%w); load the loop module on the node, or mount an XFS file system with reflink at the data dir", err)
	}
	defer func() { _ = ctl.Close() }()
	img, err := os.OpenFile(image, os.O_RDWR, 0)
	if err != nil {
		return "", 0, nil, err
	}
	defer func() { _ = img.Close() }()
	// Another process can take the free device first: try again.
	for range 8 {
		n, err := unix.IoctlRetInt(int(ctl.Fd()), unix.LOOP_CTL_GET_FREE)
		if err != nil {
			return "", 0, nil, fmt.Errorf("LOOP_CTL_GET_FREE: %w", err)
		}
		name := fmt.Sprintf("loop%d", n)
		path, rdev, err := deviceNode(name)
		if err != nil {
			return "", 0, nil, err
		}
		lf, err := os.OpenFile(path, os.O_RDWR, 0)
		if err != nil {
			return "", 0, nil, err
		}
		err = configure(int(lf.Fd()), int(img.Fd()), image)
		if errors.Is(err, unix.EBUSY) {
			_ = lf.Close()
			continue
		}
		if err != nil {
			_ = lf.Close()
			return "", 0, nil, fmt.Errorf("attach to %s: %w", path, err)
		}
		return path, rdev, func() { _ = lf.Close() }, nil
	}
	return "", 0, nil, errors.New("no free loop device after 8 tries")
}

// configure attaches imgFD to the loop device loopFD with direct I/O (no
// second page cache copy) if the kernel takes it.
func configure(loopFD, imgFD int, image string) error {
	cfg := unix.LoopConfig{Fd: uint32(imgFD)}
	cfg.Info.Flags = unix.LO_FLAGS_AUTOCLEAR | unix.LO_FLAGS_DIRECT_IO
	copy(cfg.Info.File_name[:len(cfg.Info.File_name)-1], image)
	err := unix.IoctlLoopConfigure(loopFD, &cfg)
	if errors.Is(err, unix.EINVAL) {
		cfg.Info.Flags = unix.LO_FLAGS_AUTOCLEAR
		err = unix.IoctlLoopConfigure(loopFD, &cfg)
	}
	return err
}

// findAttached returns the loop device whose backing file is the inode
// dev:ino.
func findAttached(dev, ino uint64) (string, uint64, bool) {
	ents, err := os.ReadDir(sysBlock)
	if err != nil {
		return "", 0, false
	}
	for _, e := range ents {
		name := e.Name()
		if !strings.HasPrefix(name, "loop") {
			continue
		}
		// Only attached devices have a backing file.
		if _, err := os.Stat(filepath.Join(sysBlock, name, "loop", "backing_file")); err != nil {
			continue
		}
		path, rdev, err := deviceNode(name)
		if err != nil {
			continue
		}
		f, err := os.Open(path)
		if err != nil {
			continue
		}
		info, err := unix.IoctlLoopGetStatus64(int(f.Fd()))
		_ = f.Close()
		if err == nil && info.Device == dev && info.Inode == ino {
			return path, rdev, true
		}
	}
	return "", 0, false
}

// deviceNode returns /dev/<name> and its device number. A privileged
// container has a copy of the node's /dev from its start, so a loop device
// made later can be missing: then it makes the node.
func deviceNode(name string) (string, uint64, error) {
	raw, err := os.ReadFile(filepath.Join(sysBlock, name, "dev"))
	if err != nil {
		return "", 0, err
	}
	major, minor, err := parseDevNumber(string(raw))
	if err != nil {
		return "", 0, err
	}
	rdev := unix.Mkdev(major, minor)
	path := "/dev/" + name
	var st unix.Stat_t
	if err := unix.Stat(path, &st); err == nil {
		if st.Mode&unix.S_IFMT == unix.S_IFBLK && st.Rdev == rdev {
			return path, rdev, nil
		}
		return "", 0, fmt.Errorf("%s is not block device %d:%d", path, major, minor)
	}
	if err := unix.Mknod(path, unix.S_IFBLK|0o660, int(rdev)); err != nil && !errors.Is(err, unix.EEXIST) {
		return "", 0, fmt.Errorf("mknod %s: %w", path, err)
	}
	return path, rdev, nil
}

// otherHostNS reports whether the host mount namespace (pid 1) is not ours.
func otherHostNS(o Options) bool {
	if !o.HostMountNS {
		return false
	}
	own, err1 := os.Readlink("/proc/self/ns/mnt")
	host, err2 := os.Readlink("/proc/1/ns/mnt")
	return err1 != nil || err2 != nil || own != host
}

func statDev(path string) (uint64, error) {
	var st unix.Stat_t
	if err := unix.Stat(path, &st); err != nil {
		return 0, err
	}
	return st.Dev, nil
}

// mountBoth mounts dev at the data dir in the host mount namespace (where
// the VMs run) and in this one, where it is not there yet. With the default
// hostPath mount propagation (None), the agent container does not see a host
// mount made after its start, so it mounts the device itself too.
func mountBoth(o Options, dev string, rdev uint64) error {
	if otherHostNS(o) {
		hd, err := statDev("/proc/1/root" + o.DataDir)
		if err != nil {
			return err
		}
		if hd != rdev {
			out, err := exec.Command("nsenter", "-t", "1", "-m", "--",
				"mount", "-t", "xfs", "-o", "noatime,"+mountData, dev, o.DataDir).CombinedOutput()
			if err != nil {
				return fmt.Errorf("mount in the host mount namespace: %w: %s", err, strings.TrimSpace(string(out)))
			}
		}
	}
	d, err := statDev(o.DataDir)
	if err != nil {
		return err
	}
	if d == rdev {
		return nil
	}
	if err := unix.Mount(dev, o.DataDir, "xfs", unix.MS_NOATIME, mountData); err != nil {
		return fmt.Errorf("mount: %w (the node kernel needs XFS)", err)
	}
	return nil
}

// checkHostView fails if the VMs (host mount namespace) would see another
// file system at the data dir than the agent.
func checkHostView(o Options) error {
	if !otherHostNS(o) {
		return nil
	}
	own, err := statDev(o.DataDir)
	if err != nil {
		return err
	}
	host, err := statDev("/proc/1/root" + o.DataDir)
	if err != nil {
		return fmt.Errorf("data dir in the host mount namespace: %w", err)
	}
	if own != host {
		return fmt.Errorf("data dir %s is device %d:%d in the agent but %d:%d on the host; mount the host path into the agent container at the same path",
			o.DataDir, unix.Major(own), unix.Minor(own), unix.Major(host), unix.Minor(host))
	}
	return nil
}
