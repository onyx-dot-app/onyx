//go:build !linux

package files

import (
	"fmt"
	"os"
)

// renameAt needs renameat2, which only Linux has; the daemon runs on Linux.
func renameAt(_ *os.File, from, to string, _ bool) error {
	return fmt.Errorf("%w: rename %s to %s needs Linux", ErrInvalid, from, to)
}
