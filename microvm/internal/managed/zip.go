// Package managed builds the read-only managed drive images of a node:
// a bundle zip becomes an ext4 image that the agent puts behind
// a VM's idle managed slot.
package managed

import (
	"archive/zip"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"strings"
)

// ErrBundle marks a bundle that is not a safe zip or is over a limit.
var ErrBundle = errors.New("bad managed bundle")

func bundleErr(format string, args ...any) error {
	return fmt.Errorf("%w: %s", ErrBundle, fmt.Sprintf(format, args...))
}

// Limits bound one bundle.
type Limits struct {
	// MaxZipBytes is the largest zip.
	MaxZipBytes int64
	// MaxBytes is the most file content after unzip (all files).
	MaxBytes int64
	// MaxEntries is the most files and directories.
	MaxEntries int
}

// DefaultLimits are the agent defaults.
var DefaultLimits = Limits{MaxZipBytes: 256 << 20, MaxBytes: 512 << 20, MaxEntries: 50000}

// Stats describe an unpacked bundle.
type Stats struct {
	Files, Dirs int
	// Bytes is the file content; Blocks counts 4 KiB blocks of it.
	Bytes  int64
	Blocks int64
}

const (
	maxPath = 4096
	maxName = 255
)

// cleanName checks one zip entry name and returns it without a trailing
// slash. Only plain relative paths are allowed: no absolute path, no "..",
// "." or empty part, no backslash or NUL.
func cleanName(name string) (string, bool, error) {
	dir := strings.HasSuffix(name, "/")
	n := strings.TrimSuffix(name, "/")
	switch {
	case n == "":
		return "", false, bundleErr("an entry has an empty name")
	case len(n) > maxPath:
		return "", false, bundleErr("entry name is longer than %d bytes", maxPath)
	case strings.ContainsAny(n, "\\\x00"):
		return "", false, bundleErr("entry %q has a backslash or NUL", n)
	case strings.HasPrefix(n, "/"):
		return "", false, bundleErr("entry %q is an absolute path", n)
	}
	for _, part := range strings.Split(n, "/") {
		if part == "" || part == "." || part == ".." {
			return "", false, bundleErr("entry %q has an empty, . or .. part", n)
		}
		if len(part) > maxName {
			return "", false, bundleErr("entry %q has a part longer than %d bytes", n, maxName)
		}
	}
	if path.Clean(n) != n {
		return "", false, bundleErr("entry %q is not a clean path", n)
	}
	return n, dir, nil
}

// Extract unpacks zr into dst (an empty directory). It makes only regular
// files and directories: a symlink, device, FIFO or socket entry, a path
// out of dst, a duplicate name or a file over the limits fails the whole
// bundle. File modes become 0644 (0755 if any execute bit is set), and
// directories 0755; set-ID bits are dropped. Content is counted as it is
// read, so a zip bomb stops at the limit.
func Extract(zr *zip.Reader, dst string, lim Limits) (Stats, error) {
	var st Stats
	if len(zr.File) > lim.MaxEntries {
		return st, bundleErr("%d entries, the limit is %d", len(zr.File), lim.MaxEntries)
	}
	// seen: every name so far; dirs: the directories among them.
	seen, dirs := map[string]bool{}, map[string]bool{}
	entries := 0
	// count adds one file or directory, before it is made.
	count := func() error {
		if entries >= lim.MaxEntries {
			return bundleErr("more than %d files and directories", lim.MaxEntries)
		}
		entries++
		return nil
	}
	mkdir := func(rel string) error {
		if dirs[rel] {
			return nil
		}
		if seen[rel] {
			return bundleErr("%q is a file and a directory", rel)
		}
		if err := count(); err != nil {
			return err
		}
		if err := os.Mkdir(filepath.Join(dst, filepath.FromSlash(rel)), 0o755); err != nil {
			if errors.Is(err, fs.ErrExist) {
				return bundleErr("directory %q is also a file", rel)
			}
			return err
		}
		seen[rel], dirs[rel] = true, true
		st.Dirs++
		return nil
	}
	parents := func(rel string) error {
		parts := strings.Split(rel, "/")
		for i := 1; i < len(parts); i++ {
			if err := mkdir(strings.Join(parts[:i], "/")); err != nil {
				return err
			}
		}
		return nil
	}
	for _, f := range zr.File {
		name, isDir, err := cleanName(f.Name)
		if err != nil {
			return st, err
		}
		mode := f.Mode()
		isDir = isDir || mode.IsDir()
		if !isDir && !mode.IsRegular() {
			return st, bundleErr("entry %q is a %v, only files and directories are allowed", name, mode.Type())
		}
		if err := parents(name); err != nil {
			return st, err
		}
		if isDir {
			if err := mkdir(name); err != nil {
				return st, err
			}
			continue
		}
		if seen[name] {
			return st, bundleErr("entry %q is in the bundle twice", name)
		}
		seen[name] = true
		if err := count(); err != nil {
			return st, err
		}
		perm := os.FileMode(0o644)
		if mode.Perm()&0o111 != 0 {
			perm = 0o755
		}
		n, err := writeEntry(f, filepath.Join(dst, filepath.FromSlash(name)), perm, lim.MaxBytes-st.Bytes)
		if err != nil {
			return st, err
		}
		st.Files++
		st.Bytes += n
		st.Blocks += (n + 4095) / 4096
	}
	return st, nil
}

func writeEntry(f *zip.File, dst string, perm os.FileMode, left int64) (int64, error) {
	rc, err := f.Open()
	if err != nil {
		return 0, bundleErr("entry %q: %v", f.Name, err)
	}
	defer func() { _ = rc.Close() }()
	// O_EXCL: a name that exists (a duplicate, or a directory) fails.
	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_EXCL, perm)
	if err != nil {
		if errors.Is(err, fs.ErrExist) {
			return 0, bundleErr("entry %q is in the bundle twice", f.Name)
		}
		return 0, err
	}
	n, err := io.Copy(out, io.LimitReader(rc, left+1))
	if cerr := out.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		if errors.Is(err, zip.ErrChecksum) || errors.Is(err, zip.ErrFormat) || errors.Is(err, io.ErrUnexpectedEOF) {
			return 0, bundleErr("entry %q: %v", f.Name, err)
		}
		return 0, err
	}
	if n > left {
		return 0, bundleErr("the files are larger than the limit")
	}
	// The umask can clear bits that OpenFile set.
	return n, os.Chmod(dst, perm)
}
