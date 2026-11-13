//go:build !linux

package loopstore

import "errors"

// Ensure needs Linux (loop devices, XFS).
func Ensure(Options) (*Store, error) {
	return nil, errors.New("the host agent data dir needs Linux")
}

// Trim needs Linux.
func Trim(string) (uint64, error) { return 0, errors.New("trim needs Linux") }
