// Package fsutil provides filesystem helper functions.
package fsutil

import (
	"bytes"
	"errors"
	"fmt"
	"os"
)

// FileStatus describes how an on-disk file compares to expected content.
type FileStatus int

const (
	StatusMissing  FileStatus = iota
	StatusUpToDate            // file exists with identical content
	StatusDiffers             // file exists with different content
)

// CompareFile checks whether the file at path matches the expected content.
func CompareFile(path string, expected []byte) (FileStatus, error) {
	existing, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return StatusMissing, nil
		}
		return 0, fmt.Errorf("could not read %s: %w", path, err)
	}
	if bytes.Equal(existing, expected) {
		return StatusUpToDate, nil
	}
	return StatusDiffers, nil
}

// EnsureDirForCopy makes sure path is a real directory, not a symlink or
// regular file. If a symlink or file exists at path it is removed so the
// caller can create a directory with independent content.
func EnsureDirForCopy(path string) error {
	info, err := os.Lstat(path)
	if err == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			if err := os.Remove(path); err != nil {
				return err
			}
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}
