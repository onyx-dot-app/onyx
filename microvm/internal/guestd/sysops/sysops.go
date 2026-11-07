// Package sysops holds the guest system calls of the daemon's Init: set the
// clock, add entropy, grow a file system, mount cgroup v2. They work on
// Linux as root; other systems get stubs that fail.
package sysops

import "errors"

// ErrUnsupported is returned on systems other than Linux.
var ErrUnsupported = errors.New("not supported on this system")
