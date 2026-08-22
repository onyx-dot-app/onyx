//go:build windows

package skills

import "errors"

// makeFIFO reports that named pipes are unavailable, so the caller skips.
func makeFIFO(string) error {
	return errors.New("named pipes are not supported on windows")
}
