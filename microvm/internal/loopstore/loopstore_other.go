//go:build !linux

package loopstore

import "errors"

// Ensure needs Linux (loop devices, XFS).
func Ensure(Options) (*Store, error) {
	return nil, errors.New("the host agent data dir needs Linux")
}
