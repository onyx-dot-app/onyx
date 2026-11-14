//go:build !(darwin || dragonfly || freebsd || netbsd || openbsd || linux || windows)

package iostreams

import "os"

// DiscardPendingInput has no portable implementation on this platform.
func DiscardPendingInput(*os.File) {}
