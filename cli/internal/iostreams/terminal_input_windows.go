//go:build windows

package iostreams

import "os"

// OpenTerminalInput opens the console input buffer, for a prompt while stdin
// is redirected. Write access lets DiscardPendingInput flush it.
func OpenTerminalInput() (*os.File, error) {
	return os.OpenFile("CONIN$", os.O_RDWR, 0)
}
