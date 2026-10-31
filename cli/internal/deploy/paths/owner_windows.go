//go:build windows

package paths

// checkOwnedByUser is a no-op on Windows, which has no Unix owner or mode bits.
func checkOwnedByUser(string) error {
	return nil
}
