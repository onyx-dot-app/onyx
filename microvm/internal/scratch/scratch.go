// Package scratch makes the per-VM scratch disk.
//
// The disk is a reflink copy of the template's scratch image, extended
// (sparse) to the requested size. The ext4 file system inside keeps the
// template size until the guest daemon grows it, so the cap is the file size:
// the guest cannot write past the end of the block device.
package scratch

import (
	"errors"
	"fmt"
	"os"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// GiB is the scratch size unit.
const GiB int64 = 1 << 30

// ErrNoReflink means the file system cannot make reflink copies.
var ErrNoReflink = errors.New("the file system does not support reflink copies (FICLONE)")

// CheckSize checks a requested size against the template size and the node
// limit. The disk can only grow.
func CheckSize(requestGiB, templateGiB, maxGiB uint32) error {
	if requestGiB < templateGiB {
		return apierr.New(pb.ErrorReason_SCRATCH_TOO_SMALL,
			"scratch_gib %d is smaller than the template scratch disk (%d GiB); the disk can only grow", requestGiB, templateGiB)
	}
	if requestGiB > maxGiB {
		return apierr.New(pb.ErrorReason_SCRATCH_TOO_LARGE, "scratch_gib %d is larger than the node limit %d", requestGiB, maxGiB)
	}
	return nil
}

// Prepare makes dst as a reflink copy of src, extends it to sizeBytes and
// gives it to uid:gid with mode 0600. It fails if src is larger than
// sizeBytes. On error, dst is removed.
func Prepare(src, dst string, sizeBytes int64, uid, gid int) (err error) {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer func() { _ = in.Close() }()
	st, err := in.Stat()
	if err != nil {
		return err
	}
	if st.Size() > sizeBytes {
		return fmt.Errorf("template scratch image is %d bytes, larger than the requested %d", st.Size(), sizeBytes)
	}
	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	defer func() {
		closeErr := out.Close()
		if err == nil {
			err = closeErr
		}
		if err != nil {
			_ = os.Remove(dst)
		}
	}()
	if err := clone(out, in); err != nil {
		return err
	}
	if err := out.Truncate(sizeBytes); err != nil {
		return err
	}
	if err := out.Chown(uid, gid); err != nil {
		return err
	}
	return out.Sync()
}

// ProbeReflink checks that dir supports reflink copies.
func ProbeReflink(dir string) error {
	a, err := os.CreateTemp(dir, ".reflink-probe-*")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(a.Name()); _ = a.Close() }()
	if _, err := a.Write([]byte("probe")); err != nil {
		return err
	}
	b, err := os.CreateTemp(dir, ".reflink-probe-*")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(b.Name()); _ = b.Close() }()
	return clone(b, a)
}
