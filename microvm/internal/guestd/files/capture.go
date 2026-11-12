package files

import (
	"archive/tar"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"hash"
	"io"
	"io/fs"
	"os"
	"runtime"
	"strings"
	"syscall"
	"time"

	"github.com/klauspost/compress/zstd"
)

// CaptureSpec is one capture call.
type CaptureSpec struct {
	SessionID string
	// Roots: nil means the configured capture roots.
	Roots []string
	// Exclude: nil means the configured exclude names.
	Exclude []string
	Limits  Limits
}

// CaptureSummary describes a capture archive.
type CaptureSummary struct {
	StoredBytes   int64
	SHA256        string
	Files         int64
	Directories   int64
	ExpandedBytes int64
	Excluded      int64
	Skipped       int64
	Changed       int64
	Roots         []string
}

// limitWriter counts and hashes what it writes, and fails over max.
type limitWriter struct {
	w   io.Writer
	h   hash.Hash
	n   int64
	max int64
}

func (l *limitWriter) Write(p []byte) (int, error) {
	if l.n+int64(len(p)) > l.max {
		return 0, fmt.Errorf("%w: the archive is over %d bytes", ErrLimit, l.max)
	}
	n, err := l.w.Write(p)
	l.h.Write(p[:n])
	l.n += int64(n)
	return n, err
}

func (s *Store) roots(names []string) ([]string, error) {
	if len(names) == 0 {
		return s.cfg.CaptureRoots, nil
	}
	if err := checkNames(names); err != nil {
		return nil, err
	}
	for _, n := range names {
		if strings.HasPrefix(n, ".craft-") {
			return nil, fmt.Errorf("%w: bad root %q", ErrInvalid, n)
		}
	}
	return names, nil
}

// Capture writes a tar + zstd archive of the session's capture roots (top-level
// directories or regular files) to w. A regular-file root goes in the archive
// as TopFilesRoot/<name>, and the summary names TopFilesRoot as its root.
// It returns an error, and the caller must drop what w got, if a limit is
// reached or the session cannot be read.
func (s *Store) Capture(ctx context.Context, spec CaptureSpec, w io.Writer) (CaptureSummary, error) {
	var sum CaptureSummary
	lim, err := s.limits(spec.Limits)
	if err != nil {
		return sum, err
	}
	roots, err := s.roots(spec.Roots)
	if err != nil {
		return sum, err
	}
	exclude := spec.Exclude
	if exclude == nil {
		exclude = s.cfg.CaptureExclude
	}
	unlock, err := s.lock(ctx, spec.SessionID)
	if err != nil {
		return sum, err
	}
	defer unlock()
	root, err := s.openSession(spec.SessionID, false)
	if err != nil {
		return sum, err
	}
	defer func() { _ = root.Close() }()
	// An interrupted restore can leave an old root only in the trash; an
	// archive without it would lose those files.
	if err := removeLeftovers(root); err != nil {
		return sum, fmt.Errorf("recover an interrupted restore: %w", err)
	}

	lw := &limitWriter{w: w, h: sha256.New(), max: lim.StoredBytes}
	zw, err := zstd.NewWriter(lw, zstd.WithEncoderLevel(s.cfg.ZstdLevel),
		zstd.WithEncoderConcurrency(runtime.GOMAXPROCS(0)))
	if err != nil {
		return sum, err
	}
	c := &capturer{ctx: ctx, root: root, tw: tar.NewWriter(zw), lim: lim, skip: setOf(exclude), sum: &sum,
		buf: make([]byte, 1<<20)}
	var topFiles []string
	for _, r := range roots {
		if r == TopFilesRoot {
			sum.Skipped++
			continue
		}
		fi, err := root.Lstat(r)
		if errors.Is(err, fs.ErrNotExist) {
			continue
		}
		if err != nil {
			sum.Skipped++
			continue
		}
		switch {
		case fi.IsDir():
			if err := c.dir(r, fi, 0); err != nil {
				_ = zw.Close()
				return sum, err
			}
			sum.Roots = append(sum.Roots, r)
		case fi.Mode().IsRegular():
			topFiles = append(topFiles, r)
		default:
			sum.Skipped++
		}
	}
	if len(topFiles) > 0 {
		// Top-level files go under TopFilesRoot: a single-part file member
		// fails the restore of older daemons.
		if err := c.topFiles(topFiles); err != nil {
			_ = zw.Close()
			return sum, err
		}
		sum.Roots = append(sum.Roots, TopFilesRoot)
	}
	if err := c.tw.Close(); err != nil {
		_ = zw.Close()
		return sum, err
	}
	if err := zw.Close(); err != nil {
		return sum, err
	}
	sum.StoredBytes = lw.n
	sum.SHA256 = hex.EncodeToString(lw.h.Sum(nil))
	return sum, nil
}

type capturer struct {
	ctx  context.Context
	root *os.Root
	tw   *tar.Writer
	lim  Limits
	skip map[string]bool
	sum  *CaptureSummary
	buf  []byte
}

const maxDepth = 256

func (c *capturer) entry() error {
	if c.sum.Files+c.sum.Directories >= c.lim.Entries {
		return fmt.Errorf("%w: more than %d files and directories", ErrLimit, c.lim.Entries)
	}
	return nil
}

func (c *capturer) dir(rel string, fi fs.FileInfo, depth int) error {
	if err := c.ctx.Err(); err != nil {
		return err
	}
	if depth > maxDepth {
		c.sum.Skipped++
		return nil
	}
	ents, err := readDir(c.root, rel, int(c.lim.Entries))
	if errors.Is(err, errDirTooBig) {
		return err
	}
	if err != nil {
		c.sum.Skipped++
		return nil
	}
	if err := c.entry(); err != nil {
		return err
	}
	if err := c.tw.WriteHeader(&tar.Header{
		Typeflag: tar.TypeDir, Name: rel + "/", Mode: int64(fi.Mode().Perm()), ModTime: fi.ModTime(), Format: tar.FormatPAX,
	}); err != nil {
		return err
	}
	c.sum.Directories++
	for _, e := range ents {
		name := e.Name()
		child := rel + "/" + name
		if c.skip[name] || strings.HasPrefix(name, writePrefix) {
			c.sum.Excluded++
			continue
		}
		if !restorableName(name) || len(child) > maxPathBytes {
			// Restore would refuse the member, so the save leaves it out.
			c.sum.Skipped++
			continue
		}
		info, err := e.Info()
		if err != nil {
			c.sum.Skipped++
			continue
		}
		switch typeOf(info.Mode()) {
		case TypeDirectory:
			if v, err := c.root.Lstat(child + "/pyvenv.cfg"); err == nil && v.Mode().IsRegular() {
				c.sum.Excluded++
				continue
			}
			if err := c.dir(child, info, depth+1); err != nil {
				return err
			}
		case TypeRegular:
			if err := c.file(child, child); err != nil {
				return err
			}
		default:
			c.sum.Skipped++
		}
	}
	return nil
}

// topFiles writes the TopFilesRoot directory and the top-level files in it.
func (c *capturer) topFiles(names []string) error {
	if err := c.entry(); err != nil {
		return err
	}
	if err := c.tw.WriteHeader(&tar.Header{
		Typeflag: tar.TypeDir, Name: TopFilesRoot + "/", Mode: 0o755, ModTime: time.Now(), Format: tar.FormatPAX,
	}); err != nil {
		return err
	}
	c.sum.Directories++
	for _, n := range names {
		if err := c.file(n, TopFilesRoot+"/"+n); err != nil {
			return err
		}
	}
	return nil
}

// file writes the regular file rel of the session as the member name.
func (c *capturer) file(rel, name string) error {
	if err := c.ctx.Err(); err != nil {
		return err
	}
	f, fi, err := openRegular(c.root, rel, syscall.O_NOFOLLOW)
	if err != nil {
		c.sum.Skipped++
		return nil
	}
	defer func() { _ = f.Close() }()
	size := fi.Size()
	if c.sum.ExpandedBytes+size > c.lim.ExpandedBytes {
		return fmt.Errorf("%w: the files are over %d bytes", ErrLimit, c.lim.ExpandedBytes)
	}
	if err := c.entry(); err != nil {
		return err
	}
	if err := c.tw.WriteHeader(&tar.Header{
		Typeflag: tar.TypeReg, Name: name, Size: size, Mode: int64(fi.Mode().Perm()), ModTime: fi.ModTime(), Format: tar.FormatPAX,
	}); err != nil {
		return err
	}
	n, err := io.CopyBuffer(c.tw, io.LimitReader(f, size), c.buf)
	if err != nil {
		return err
	}
	if n < size {
		// The file shrank after the header: fill the rest with zeros.
		c.sum.Changed++
		if _, err := io.CopyN(c.tw, zeroReader{}, size-n); err != nil {
			return err
		}
	}
	c.sum.Files++
	c.sum.ExpandedBytes += size
	return nil
}

type zeroReader struct{}

func (zeroReader) Read(p []byte) (int, error) {
	clear(p)
	return len(p), nil
}
