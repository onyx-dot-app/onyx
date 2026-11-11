// Package safefs writes files into a checkout without following symlinks the
// checkout may contain.
package safefs

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

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

// CheckNoSymlinks fails if any existing path part of path below base is a
// symlink. Parts that do not exist yet are fine.
func CheckNoSymlinks(base, path string) error {
	rel, err := filepath.Rel(base, path)
	if err != nil || !filepath.IsLocal(rel) {
		return fmt.Errorf("refusing to use %s: not inside %s", path, base)
	}
	cur := base
	for _, part := range strings.Split(rel, string(filepath.Separator)) {
		cur = filepath.Join(cur, part)
		info, err := os.Lstat(cur)
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		if err != nil {
			return err
		}
		if info.Mode()&fs.ModeSymlink != 0 {
			return fmt.Errorf("refusing to use %s: %s is a symlink", path, cur)
		}
	}
	return nil
}
