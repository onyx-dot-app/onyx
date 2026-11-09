// Package fsutil provides filesystem helper functions.
package fsutil

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
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

// WriteFileNoFollow writes data to path, which must be inside base. Every
// path part below base must be a real directory and the destination must be
// absent or a regular file; a symlink anywhere below base is an error. Missing
// directories are created. The write goes to a temp file in the same
// directory that is then renamed over the destination, and an existing file
// keeps its mode.
func WriteFileNoFollow(base, path string, data []byte, perm fs.FileMode) error {
	rel, err := filepath.Rel(base, path)
	if err != nil || !filepath.IsLocal(rel) {
		return fmt.Errorf("refusing to write %s: not inside %s", path, base)
	}
	parts := strings.Split(rel, string(filepath.Separator))

	dir := base
	for _, part := range parts[:len(parts)-1] {
		dir = filepath.Join(dir, part)
		info, err := os.Lstat(dir)
		switch {
		case errors.Is(err, fs.ErrNotExist):
			if err := os.Mkdir(dir, 0o755); err != nil {
				return err
			}
		case err != nil:
			return err
		case !info.IsDir():
			return fmt.Errorf("refusing to write %s: %s is not a directory", path, dir)
		}
	}

	dest := filepath.Join(dir, parts[len(parts)-1])
	info, err := os.Lstat(dest)
	switch {
	case err == nil && !info.Mode().IsRegular():
		return fmt.Errorf("refusing to write %s: not a regular file", dest)
	case err == nil:
		perm = info.Mode().Perm()
	case !errors.Is(err, fs.ErrNotExist):
		return err
	}

	tmp, err := os.CreateTemp(dir, "."+filepath.Base(dest)+".tmp-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer func() { _ = os.Remove(tmpName) }()
	_, writeErr := tmp.Write(data)
	closeErr := tmp.Close()
	if err := errors.Join(writeErr, closeErr); err != nil {
		return err
	}
	if err := os.Chmod(tmpName, perm); err != nil {
		return err
	}
	return os.Rename(tmpName, dest)
}

// CheckResolvesInside fails unless path, or its deepest existing ancestor,
// resolves through any symlinks to a location inside base. A dangling
// symlink on the way is an error.
func CheckResolvesInside(base, path string) error {
	realBase, err := filepath.EvalSymlinks(base)
	if err != nil {
		return err
	}
	for cur := path; ; cur = filepath.Dir(cur) {
		resolved, err := filepath.EvalSymlinks(cur)
		if err == nil {
			rel, err := filepath.Rel(realBase, resolved)
			if err != nil || (rel != "." && !filepath.IsLocal(rel)) {
				return fmt.Errorf("refusing to use %s: it resolves outside %s", path, base)
			}
			return nil
		}
		if !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		if info, lerr := os.Lstat(cur); lerr == nil && info.Mode()&fs.ModeSymlink != 0 {
			return fmt.Errorf("refusing to use %s: %s is a dangling symlink", path, cur)
		}
		if filepath.Dir(cur) == cur {
			return err
		}
	}
}
