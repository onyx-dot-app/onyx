package scratch

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
)

// Clone makes dst as a reflink copy of src, with mode and owner uid:gid. It
// never makes a hard link: dst is a new inode that shares the data blocks
// until one side writes, so a write or truncate of dst (for example a
// snapshot/create to that path) never changes src. On error, dst is removed.
func Clone(src, dst string, mode os.FileMode, uid, gid int) (err error) {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer func() { _ = in.Close() }()
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
	if err := checkNotLinked(in, out); err != nil {
		return err
	}
	if err := out.Chown(uid, gid); err != nil {
		return err
	}
	return out.Chmod(mode)
}

// checkNotLinked fails if out is the same inode as in, or has another name.
func checkNotLinked(in, out *os.File) error {
	si, err := in.Stat()
	if err != nil {
		return err
	}
	so, err := out.Stat()
	if err != nil {
		return err
	}
	if os.SameFile(si, so) {
		return errors.New("copy is the same inode as its source")
	}
	if n := nlink(so); n != 1 {
		return fmt.Errorf("copy has %d links, want 1", n)
	}
	return nil
}

// CopyFile copies src to a new file dst with mode 0644: a reflink copy if
// both are on one reflink file system, otherwise a sparse byte copy (zero
// blocks become holes). It returns whether it made a reflink copy.
func CopyFile(src, dst string) (reflinked bool, err error) {
	in, err := os.Open(src)
	if err != nil {
		return false, err
	}
	defer func() { _ = in.Close() }()
	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		return false, err
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
	cloneErr := clone(out, in)
	if cloneErr == nil {
		return true, checkNotLinked(in, out)
	}
	if !errors.Is(cloneErr, ErrNoReflink) {
		return false, cloneErr
	}
	if err := sparseCopy(out, in); err != nil {
		return false, err
	}
	return false, out.Sync()
}

const copyChunk = 1 << 20

func sparseCopy(out, in *os.File) error {
	buf := make([]byte, copyChunk)
	zero := make([]byte, copyChunk)
	var off int64
	for {
		n, err := io.ReadFull(in, buf)
		if n > 0 {
			if !bytes.Equal(buf[:n], zero[:n]) {
				if _, werr := out.WriteAt(buf[:n], off); werr != nil {
					return werr
				}
			}
			off += int64(n)
		}
		if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
			break
		}
		if err != nil {
			return err
		}
	}
	return out.Truncate(off)
}
