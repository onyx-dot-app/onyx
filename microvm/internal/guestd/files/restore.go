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
	"path"
	"slices"
	"strings"
	"unicode/utf8"

	"github.com/klauspost/compress/zstd"
)

// MaxZstdWindow caps the zstd window a restore accepts (capture uses 8 MiB).
const MaxZstdWindow = 64 << 20

// RestoreSpec is the header of a restore.
type RestoreSpec struct {
	SessionID string
	// Size and SHA256 (hex) of the archive.
	Size   int64
	SHA256 string
	// Roots: nil means the configured capture roots.
	Roots  []string
	Limits Limits
}

// RestoreSummary describes a restore.
type RestoreSummary struct {
	Files         int64
	Directories   int64
	ExpandedBytes int64
	Roots         []string
}

// hashReader counts and hashes what it reads, and fails past max.
type hashReader struct {
	r   io.Reader
	h   hash.Hash
	n   int64
	max int64
}

func (h *hashReader) Read(p []byte) (int, error) {
	n, err := h.r.Read(p)
	h.h.Write(p[:n])
	h.n += int64(n)
	if h.n > h.max {
		return n, fmt.Errorf("%w: more than the %d bytes in the header", ErrArchive, h.max)
	}
	return n, err
}

// Restore extracts a capture archive from r into the session. Nothing in
// the session changes unless the whole archive is valid and matches the
// size and SHA-256 of spec.
func (s *Store) Restore(ctx context.Context, spec RestoreSpec, r io.Reader) (RestoreSummary, error) {
	var sum RestoreSummary
	lim, err := s.limits(spec.Limits)
	if err != nil {
		return sum, err
	}
	want := strings.ToLower(spec.SHA256)
	if !hexSHA256.MatchString(want) {
		return sum, fmt.Errorf("%w: sha256 must be 64 hex characters", ErrInvalid)
	}
	if spec.Size <= 0 {
		return sum, fmt.Errorf("%w: size_bytes must be positive", ErrInvalid)
	}
	if spec.Size > lim.StoredBytes {
		return sum, fmt.Errorf("%w: archive of %d bytes is over %d", ErrLimit, spec.Size, lim.StoredBytes)
	}
	roots, err := s.roots(spec.Roots)
	if err != nil {
		return sum, err
	}
	unlock, err := s.lock(ctx, spec.SessionID)
	if err != nil {
		return sum, err
	}
	defer unlock()
	root, err := s.openSession(spec.SessionID, true)
	if err != nil {
		return sum, err
	}
	defer func() { _ = root.Close() }()
	removeLeftovers(root)

	staging := randName(stagingPrefix)
	if err := root.Mkdir(staging, 0o700); err != nil {
		return sum, err
	}
	defer func() { _ = root.RemoveAll(staging) }()
	st, err := root.OpenRoot(staging)
	if err != nil {
		return sum, err
	}
	defer func() { _ = st.Close() }()

	hr := &hashReader{r: &ctxReader{ctx: ctx, r: r}, h: sha256.New(), max: spec.Size}
	zr, err := zstd.NewReader(hr, zstd.WithDecoderMaxWindow(MaxZstdWindow), zstd.WithDecoderConcurrency(0))
	if err != nil {
		return sum, err
	}
	defer zr.Close()
	x := &extractor{root: st, lim: lim, allowed: setOf(roots), sum: &sum, present: map[string]bool{},
		buf: make([]byte, 1<<20)}
	if err := x.run(ctx, tar.NewReader(zr)); err != nil {
		return sum, err
	}
	// The hash covers the whole stream: read what is left after the tar end.
	if _, err := io.Copy(io.Discard, zr); err != nil {
		return sum, archiveErr(err)
	}
	if _, err := io.Copy(io.Discard, hr); err != nil {
		return sum, archiveErr(err)
	}
	got := hex.EncodeToString(hr.h.Sum(nil))
	if hr.n != spec.Size || got != want {
		return sum, fmt.Errorf("%w: got %d bytes with sha256 %s, the header says %d bytes with %s",
			ErrArchive, hr.n, got, spec.Size, want)
	}
	if err := x.finish(); err != nil {
		return sum, err
	}

	// Swap each root of the archive into place. The old tree goes to a
	// trash directory first, so a failed swap can move it back.
	trash := randName(oldPrefix)
	if err := root.Mkdir(trash, 0o700); err != nil {
		return sum, err
	}
	defer func() { _ = root.RemoveAll(trash) }()
	for _, r := range roots {
		if !x.present[r] {
			continue
		}
		_, err := root.Lstat(r)
		hadOld := err == nil
		if hadOld {
			if err := root.Rename(r, trash+"/"+r); err != nil {
				return sum, fmt.Errorf("move old %s: %w", r, err)
			}
		}
		if err := root.Rename(staging+"/"+r, r); err != nil {
			if hadOld {
				_ = root.Rename(trash+"/"+r, r)
			}
			return sum, fmt.Errorf("move restored %s: %w", r, err)
		}
		sum.Roots = append(sum.Roots, r)
	}
	return sum, nil
}

// removeLeftovers removes staging and trash directories of an earlier
// restore that did not finish (the daemon restarted).
func removeLeftovers(root *os.Root) {
	ents, err := readDir(root, ".")
	if err != nil {
		return
	}
	for _, e := range ents {
		if n := e.Name(); e.IsDir() && (strings.HasPrefix(n, stagingPrefix) || strings.HasPrefix(n, oldPrefix)) {
			_ = root.RemoveAll(n)
		}
	}
}

func archiveErr(err error) error {
	if errors.Is(err, ErrArchive) || errors.Is(err, ErrLimit) || errors.Is(err, context.Canceled) ||
		errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	return fmt.Errorf("%w: %v", ErrArchive, err)
}

type extractor struct {
	root    *os.Root
	lim     Limits
	allowed map[string]bool
	sum     *RestoreSummary
	present map[string]bool
	dirs    []dirMode
	buf     []byte
}

type dirMode struct {
	name string
	mode fs.FileMode
	hdr  *tar.Header
}

// memberName checks a tar member name and returns it without a trailing
// "/".
func (x *extractor) memberName(h *tar.Header) (string, error) {
	n := h.Name
	if h.Typeflag == tar.TypeDir {
		n = strings.TrimSuffix(n, "/")
	}
	bad := func(why string) error { return fmt.Errorf("%w: member %q: %s", ErrArchive, h.Name, why) }
	switch {
	case n == "" || len(n) > maxPathBytes:
		return "", bad("bad length")
	case !utf8.ValidString(n) || strings.ContainsRune(n, 0) || strings.Contains(n, "\\"):
		return "", bad("bad characters")
	case strings.HasPrefix(n, "/"):
		return "", bad("absolute path")
	case path.Clean(n) != n:
		return "", bad("not a clean path")
	}
	parts := strings.Split(n, "/")
	for _, p := range parts {
		if p == ".." || p == "." || len(p) > maxNameBytes {
			return "", bad("unsafe path part")
		}
	}
	if !x.allowed[parts[0]] {
		return "", bad("not under a capture root")
	}
	if len(parts) == 1 && h.Typeflag != tar.TypeDir {
		return "", bad("a capture root must be a directory")
	}
	return n, nil
}

func (x *extractor) run(ctx context.Context, tr *tar.Reader) error {
	var entries int64
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		h, err := tr.Next()
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return archiveErr(err)
		}
		entries++
		if entries > x.lim.Entries {
			return fmt.Errorf("%w: more than %d entries", ErrLimit, x.lim.Entries)
		}
		name, err := x.memberName(h)
		if err != nil {
			return err
		}
		mode := fs.FileMode(h.Mode) & fs.ModePerm
		switch h.Typeflag {
		case tar.TypeDir:
			if err := x.root.MkdirAll(name, 0o700); err != nil {
				return archiveErr(err)
			}
			fi, err := x.root.Lstat(name)
			if err != nil || !fi.IsDir() {
				return fmt.Errorf("%w: member %q: not a directory", ErrArchive, h.Name)
			}
			x.dirs = append(x.dirs, dirMode{name: name, mode: mode, hdr: h})
			x.sum.Directories++
		case tar.TypeReg:
			if h.Size < 0 {
				return fmt.Errorf("%w: member %q: negative size", ErrArchive, h.Name)
			}
			if x.sum.ExpandedBytes+h.Size > x.lim.ExpandedBytes {
				return fmt.Errorf("%w: the files are over %d bytes", ErrLimit, x.lim.ExpandedBytes)
			}
			x.sum.ExpandedBytes += h.Size
			if err := x.file(name, mode, h, tr); err != nil {
				return err
			}
			x.sum.Files++
		default:
			// Links, devices, FIFOs, sparse and other members.
			return fmt.Errorf("%w: member %q: type %q is not allowed", ErrArchive, h.Name, h.Typeflag)
		}
		x.present[strings.SplitN(name, "/", 2)[0]] = true
	}
}

func (x *extractor) file(name string, mode fs.FileMode, h *tar.Header, tr *tar.Reader) error {
	if d := parentOf(name); d != "." {
		if err := x.root.MkdirAll(d, 0o700); err != nil {
			return archiveErr(err)
		}
	}
	f, err := x.root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		if errors.Is(err, fs.ErrExist) {
			return fmt.Errorf("%w: member %q: duplicate", ErrArchive, h.Name)
		}
		return archiveErr(err)
	}
	n, err := io.CopyBuffer(f, tr, x.buf)
	if err == nil && n != h.Size {
		err = fmt.Errorf("%w: member %q: short data", ErrArchive, h.Name)
	}
	if err == nil {
		err = f.Chmod(mode)
	}
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		return archiveErr(err)
	}
	_ = x.root.Chtimes(name, h.ModTime, h.ModTime)
	return nil
}

// finish applies the directory modes and times, deepest first, so that a
// read-only directory does not stop the extraction of its files.
func (x *extractor) finish() error {
	slices.SortFunc(x.dirs, func(a, b dirMode) int { return strings.Count(b.name, "/") - strings.Count(a.name, "/") })
	for _, d := range x.dirs {
		if err := x.root.Chmod(d.name, d.mode); err != nil {
			return err
		}
		_ = x.root.Chtimes(d.name, d.hdr.ModTime, d.hdr.ModTime)
	}
	return nil
}
