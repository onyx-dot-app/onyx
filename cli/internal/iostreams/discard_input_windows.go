//go:build windows

package iostreams

import (
	"os"

	"golang.org/x/sys/windows"
)

// DiscardPendingInput drops input that a console received but nobody read,
// so text typed before a prompt cannot answer it.
func DiscardPendingInput(f *os.File) {
	_ = windows.FlushConsoleInputBuffer(windows.Handle(f.Fd()))
}
