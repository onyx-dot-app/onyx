// Package loopstore gives the host agent a reflink file system on nodes
// whose data dir has none (for example the ext4 roots of GKE COS and AKS
// Ubuntu): a sparse image file with XFS (reflink=1), on a loop device,
// mounted at the data dir.
//
// The image is <data-dir>/.craft-fc-store.img on the node file system. The
// mount hides it, and all agent paths (journal, templates, jail) stay the
// same. After an agent restart the mount is still there; after a node reboot
// the agent attaches and mounts the same image again. An XFS data disk with
// reflink mounted at the data dir needs no store.
package loopstore

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
)

// ImageName is the store image file in the data dir (under the mount).
const ImageName = ".craft-fc-store.img"

const (
	// MinBytes is the smallest store the agent makes.
	MinBytes uint64 = 20 * uint64(scratch.GiB)
	// MaxBytes is the largest store that the automatic size makes.
	MaxBytes uint64 = 4096 * uint64(scratch.GiB)
	// autoPercent of the free space is the automatic size. The rest stays
	// for the node (images, logs), because the image is sparse.
	autoPercent = 80
)

// Mode says whether the agent may make a store.
type Mode string

const (
	// Auto makes a store when the data dir has no reflink.
	Auto Mode = "auto"
	// Off refuses to start when the data dir has no reflink.
	Off Mode = "off"
)

// ParseMode checks a --loop-store value.
func ParseMode(s string) (Mode, error) {
	switch Mode(s) {
	case Auto, Off:
		return Mode(s), nil
	}
	return "", fmt.Errorf("--loop-store %q must be auto or off", s)
}

// Options configure Ensure.
type Options struct {
	DataDir string
	Mode    Mode
	// SizeGiB is the size of a new image; 0 is AutoSize of the free space.
	SizeGiB uint64
	// HostMountNS: VMs run in the host mount namespace (nsenter -t 1 -m), so
	// the store is mounted there too.
	HostMountNS bool
	// RootfsDir is the agent's --rootfs-dir. If it is in DataDir, a root
	// drive that the init container put on the node file system is copied
	// into the store.
	RootfsDir string
	Log       *slog.Logger
}

// Store describes a mounted loop store.
type Store struct {
	Image     string
	Device    string
	SizeBytes int64
	// Created is true when this start made the image.
	Created bool
}

// AutoSize is the size of a new image for free bytes on the node file
// system: 80% of it, at most MaxBytes, rounded down to 1 MiB. It fails
// below MinBytes.
func AutoSize(free uint64) (uint64, error) {
	size := min(free/100*autoPercent, MaxBytes) &^ (1<<20 - 1)
	if size < MinBytes {
		return 0, fmt.Errorf("%d GiB free; the loop store needs at least %d GiB (%d%% of the free space)",
			free>>30, MinBytes>>30, autoPercent)
	}
	return size, nil
}

// imageSize is the size of a new image: SizeGiB if set, else AutoSize.
func imageSize(sizeGiB, free uint64) (uint64, error) {
	if sizeGiB == 0 {
		return AutoSize(free)
	}
	want := sizeGiB << 30
	if want < MinBytes {
		return 0, fmt.Errorf("--loop-store-gib %d is less than %d", sizeGiB, MinBytes>>30)
	}
	if want > free {
		return 0, fmt.Errorf("--loop-store-gib %d is more than the %d GiB free", sizeGiB, free>>30)
	}
	return want, nil
}

// parseDevNumber parses a sysfs "dev" file ("7:3\n").
func parseDevNumber(s string) (major, minor uint32, err error) {
	a, b, ok := strings.Cut(strings.TrimSpace(s), ":")
	if !ok {
		return 0, 0, fmt.Errorf("bad device number %q", s)
	}
	ma, err := strconv.ParseUint(a, 10, 32)
	if err != nil {
		return 0, 0, fmt.Errorf("bad device number %q", s)
	}
	mi, err := strconv.ParseUint(b, 10, 32)
	if err != nil {
		return 0, 0, fmt.Errorf("bad device number %q", s)
	}
	return uint32(ma), uint32(mi), nil
}

const (
	rootfsImage    = "rootfs.ext4"
	rootfsManifest = "manifest.json"
)

// syncRootfs copies the root drive in lowerRoot/rel (the data dir before the
// mount) to upperRoot/rel (the store) if the store has no copy of that
// build (same manifest.json). The lower copy stays, so the init container
// sees it as current after a node reboot. It reports whether it copied.
func syncRootfs(lowerRoot, upperRoot, rel string) (bool, error) {
	src := filepath.Join(lowerRoot, rel)
	want, err := os.ReadFile(filepath.Join(src, rootfsManifest))
	if errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if _, err := os.Stat(filepath.Join(src, rootfsImage)); errors.Is(err, fs.ErrNotExist) {
		return false, nil
	} else if err != nil {
		return false, err
	}
	dst := filepath.Join(upperRoot, rel)
	if got, err := os.ReadFile(filepath.Join(dst, rootfsManifest)); err == nil && bytes.Equal(got, want) {
		if _, err := os.Stat(filepath.Join(dst, rootfsImage)); err == nil {
			return false, nil
		}
	}
	// Like install-rootfs.sh: build next to it, then one rename.
	tmp, old := dst+".new", dst+".old"
	if err := os.RemoveAll(tmp); err != nil {
		return false, err
	}
	if err := os.RemoveAll(old); err != nil {
		return false, err
	}
	if err := os.MkdirAll(tmp, 0o755); err != nil {
		return false, err
	}
	if err := os.Chmod(tmp, 0o755); err != nil {
		return false, err
	}
	if _, err := scratch.CopyFile(filepath.Join(src, rootfsImage), filepath.Join(tmp, rootfsImage)); err != nil {
		return false, err
	}
	if err := writeSynced(filepath.Join(tmp, rootfsManifest), want); err != nil {
		return false, err
	}
	if _, err := os.Stat(dst); err == nil {
		if err := os.Rename(dst, old); err != nil {
			return false, err
		}
	}
	if err := os.Rename(tmp, dst); err != nil {
		return false, err
	}
	return true, os.RemoveAll(old)
}

func writeSynced(path string, data []byte) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	return f.Close()
}

// rootfsRel is RootfsDir relative to DataDir, or "" if it is not inside.
func rootfsRel(dataDir, rootfsDir string) string {
	if rootfsDir == "" {
		return ""
	}
	rel, err := filepath.Rel(filepath.Clean(dataDir), filepath.Clean(rootfsDir))
	if err != nil || rel == "." || rel == ".." || strings.HasPrefix(rel, "../") {
		return ""
	}
	return rel
}
