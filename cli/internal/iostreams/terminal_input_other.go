//go:build !windows

package iostreams

import "os"

// OpenTerminalInput opens the controlling terminal, for a prompt while stdin
// is redirected.
func OpenTerminalInput() (*os.File, error) {
	return os.Open("/dev/tty")
}
