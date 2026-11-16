//go:build !linux

package scratch

import "os"

func clone(_, _ *os.File) error { return ErrNoReflink }
