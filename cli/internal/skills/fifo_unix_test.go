//go:build !windows

package skills

import "syscall"

// makeFIFO creates a named pipe, used to check that Load never reads one.
func makeFIFO(path string) error {
	return syscall.Mkfifo(path, 0o600)
}
