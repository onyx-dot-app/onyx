//go:build !linux

package guestlog

import (
	"errors"
	"os"
)

func punchHole(*os.File, int64) error { return errors.New("punch hole needs Linux") }
