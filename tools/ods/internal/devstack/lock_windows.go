//go:build windows

package devstack

import (
	"errors"
	"os"
)

var (
	errWouldBlock = errors.New("lock held")
	// errUnsupported is returned where process groups and flock are missing.
	errUnsupported = errors.New("ods stack supports macOS and Linux only")
)

func tryFlock(*os.File) error { return errUnsupported }

func unflock(*os.File) error { return nil }
