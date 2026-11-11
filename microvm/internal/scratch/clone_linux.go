//go:build linux

package scratch

import (
	"errors"
	"fmt"
	"os"

	"golang.org/x/sys/unix"
)

func clone(dst, src *os.File) error {
	err := unix.IoctlFileClone(int(dst.Fd()), int(src.Fd()))
	if errors.Is(err, unix.EOPNOTSUPP) || errors.Is(err, unix.EXDEV) || errors.Is(err, unix.EINVAL) {
		return fmt.Errorf("%w: %v", ErrNoReflink, err)
	}
	return err
}
