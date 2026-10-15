//go:build !windows

package devstack

import (
	"errors"
	"os"
	"syscall"
)

var errWouldBlock = errors.New("lock held")

func tryFlock(f *os.File) error {
	err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
	if errors.Is(err, syscall.EWOULDBLOCK) {
		return errWouldBlock
	}
	return err
}

func unflock(f *os.File) error {
	return syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
}
