// Package sysops holds the guest system calls of the daemon's Init: set the
// clock, add entropy, grow a file system, mount cgroup v2. They work on
// Linux as root; other systems get stubs that fail.
package sysops

import (
	"errors"
	"fmt"
	"time"
)

// ErrUnsupported is returned on systems other than Linux.
var ErrUnsupported = errors.New("not supported on this system")

// waitDevSize calls read until the size is at least want, at most tries
// times.
func waitDevSize(read func() (uint64, error), want uint64, tries int, every time.Duration) (uint64, error) {
	for i := 1; ; i++ {
		n, err := read()
		if err != nil || n >= want {
			return n, err
		}
		if i >= tries {
			return n, fmt.Errorf("device is %d bytes, want at least %d (the resize has not reached the guest)", n, want)
		}
		time.Sleep(every)
	}
}
