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
	// A root that stays in the trash and is not in the archive would be lost.
	if err := removeLeftovers(root); err != nil {
		return sum, fmt.Errorf("recover an interrupted restore: %w", err)
	}

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
	br := &budgetReader{r: zr}
	x := &extractor{root: st, lim: lim, allowed: setOf(roots), sum: &sum, present: map[string]bool{},
		made: map[string]bool{}, buf: make([]byte, 1<<20), budget: br,
		own: func(name string) error { return s.own(st, name) }}
	if err := x.run(ctx, tar.NewReader(br)); err != nil {
		return sum, err
	}
	// The hash covers the whole stream: read what is left after the tar end,
	// still inside the decoded budget.
	if _, err := io.Copy(io.Discard, br); err != nil {
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
	swap, err := x.liftTopFiles(roots)
	if err != nil {
		return sum, err
	}
	if err := x.finish(); err != nil {
		return sum, err
	}

	if err := swapRoots(root, staging, swap, x.present); err != nil {
		return sum, err
	}
	if x.liftedTop {
		// The files are at the top level now. An empty TopFilesRoot that a
		// daemon without TopFilesRoot restored is left over.
		if fi, err := root.Lstat(TopFilesRoot); err == nil && fi.IsDir() {
			_ = root.Remove(TopFilesRoot)
		}
	}
	for _, r := range roots {
		if x.present[r] || (r == TopFilesRoot && len(x.topFiles) > 0) {
			sum.Roots = append(sum.Roots, r)
		}
	}
	return sum, nil
}

// liftTopFiles moves the files under TopFilesRoot to the top of the staging
// directory, so that the swap puts each one in place as its own root. It
// returns the names to swap.
func (x *extractor) liftTopFiles(roots []string) ([]string, error) {
	swap := make([]string, 0, len(roots)+len(x.topFiles))
	for _, r := range roots {
		if r != TopFilesRoot {
			swap = append(swap, r)
		}
	}
	if !x.present[TopFilesRoot] {
		return swap, nil
	}
	for _, f := range x.topFiles {
		if x.present[f] {
			return nil, fmt.Errorf("%w: %s/%s: the archive also has a root %q", ErrArchive, TopFilesRoot, f, f)
		}
		if err := x.root.Rename(TopFilesRoot+"/"+f, f); err != nil {
			return nil, err
		}
		x.present[f] = true
		swap = append(swap, f)
	}
	delete(x.present, TopFilesRoot)
	x.liftedTop = true
	if err := x.root.Remove(TopFilesRoot); err != nil {
		return nil, err
	}
	return swap, nil
}

// rename is root.Rename; tests replace it to inject failures.
var rename = func(root *os.Root, from, to string) error { return root.Rename(from, to) }

// swapRoots moves each restored root from staging into place. An old root
// goes to a trash directory first. If any step fails, the roots already
// swapped are moved back (best effort). If a rollback rename fails, or the
// daemon stops during the swap, the session can keep a mix of old and new
// roots; the trash then stays, and the next restore (removeLeftovers) puts
// back any old root that has no replacement.
func swapRoots(root *os.Root, staging string, roots []string, present map[string]bool) error {
	trash := randName(oldPrefix)
	if err := root.Mkdir(trash, 0o700); err != nil {
		return err
	}
	type swapped struct {
		name   string
		hadOld bool
	}
	var done []swapped
	// keep is set when a rollback step fails: the trash then holds the only
	// copy of an old root, and removeLeftovers recovers it later.
	keep := false
	defer func() {
		if !keep {
			_ = root.RemoveAll(trash)
		}
	}()
	rollback := func() {
		for i := len(done) - 1; i >= 0; i-- {
			d := done[i]
			if err := rename(root, d.name, staging+"/"+d.name); err != nil {
				keep = true
				continue
			}
			if d.hadOld {
				if err := rename(root, trash+"/"+d.name, d.name); err != nil {
					keep = true
				}
			}
		}
	}
	for _, r := range roots {
		if !present[r] {
			continue
		}
		_, err := root.Lstat(r)
		hadOld := err == nil
		if hadOld {
			if err := rename(root, r, trash+"/"+r); err != nil {
				rollback()
				return fmt.Errorf("move old %s: %w", r, err)
			}
		}
		if err := rename(root, staging+"/"+r, r); err != nil {
			if hadOld {
				if err := rename(root, trash+"/"+r, r); err != nil {
					keep = true
				}
			}
			rollback()
			return fmt.Errorf("move restored %s: %w", r, err)
		}
		done = append(done, swapped{name: r, hadOld: hadOld})
	}
	return nil
}

// removeLeftovers cleans up after a restore that did not finish (the daemon
// stopped, or a rollback rename failed). It moves back each old root whose
// place is empty, then removes the staging directories and each trash
// directory whose recovery succeeded. A trash directory that still holds an
// unrecovered old root stays for the next attempt, and the error names it.
func removeLeftovers(root *os.Root) error {
	ents, err := readDir(root, ".", MaxListEntries)
	if err != nil {
		return err
	}
	var failed []string
	for _, e := range ents {
		n := e.Name()
		if !e.IsDir() {
			continue
		}
		if strings.HasPrefix(n, stagingPrefix) {
			_ = root.RemoveAll(n)
		} else if strings.HasPrefix(n, oldPrefix) {
			if recoverOld(root, n) {
				_ = root.RemoveAll(n)
			} else {
				failed = append(failed, n)
			}
		}
	}
	if len(failed) > 0 {
		return fmt.Errorf("cannot recover old roots from %s", strings.Join(failed, ", "))
	}
	return nil
}

// recoverOld moves each old root in trash back to its place if the place is
// empty. It returns false if an old root could not be moved back.
func recoverOld(root *os.Root, trash string) bool {
	olds, err := readDir(root, trash, MaxListEntries)
	if err != nil {
		return false
	}
	for _, o := range olds {
		_, err := root.Lstat(o.Name())
		if err == nil {
			continue // a restored root replaced it
		}
		if !errors.Is(err, fs.ErrNotExist) {
			return false
		}
		if err := rename(root, trash+"/"+o.Name(), o.Name()); err != nil {
			return false
		}
	}
	return true
}

const (
	// entryOverheadBytes bounds the decoded tar bytes of one member besides
	// its file data: header, PAX header and records, padding.
	entryOverheadBytes = 16 << 10
	// tailBytes bounds the decoded bytes after the tar end marker (record
	// padding).
	tailBytes = 64 << 10
)

// budgetReader fails once more than max decoded bytes were read. The
// extractor raises max as it accepts members, so the whole decoded stream
// stays within the file bytes plus a fixed overhead per member.
type budgetReader struct {
	r   io.Reader
	n   int64
	max int64
}

func (b *budgetReader) Read(p []byte) (int, error) {
	if b.n >= b.max {
		return 0, fmt.Errorf("%w: the archive expands past its members", ErrLimit)
	}
	if rest := b.max - b.n; int64(len(p)) > rest {
		p = p[:rest]
	}
	n, err := b.r.Read(p)
	b.n += int64(n)
	return n, err
}

// restorableName reports whether restore accepts name as one path part.
// Capture leaves out files whose names fail it. A backslash is a normal
// character on Linux, so it is allowed.
func restorableName(name string) bool {
	return name != "" && len(name) <= maxNameBytes && utf8.ValidString(name) && !strings.ContainsRune(name, 0)
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
	// made holds the directories created so far.
	made    map[string]bool
	entries int64
	dirs    []dirMode
	buf     []byte
	budget  *budgetReader
	// own gives a restored file or directory to the configured owner.
	own func(name string) error
	// topFiles are the file names under TopFilesRoot.
	topFiles []string
	// liftedTop is set when the archive had TopFilesRoot.
	liftedTop bool
}

// entry counts one member, or one parent directory that a member needs.
func (x *extractor) entry() error {
	x.entries++
	if x.entries > x.lim.Entries {
		return fmt.Errorf("%w: more than %d entries", ErrLimit, x.lim.Entries)
	}
	return nil
}

// mkdir creates dir if it is missing. The parents of dir must exist.
func (x *extractor) mkdir(dir string) error {
	if x.made[dir] {
		return nil
	}
	if err := x.root.Mkdir(dir, 0o700); err != nil && !errors.Is(err, fs.ErrExist) {
		return archiveErr(err)
	}
	if fi, err := x.root.Lstat(dir); err != nil || !fi.IsDir() {
		return fmt.Errorf("%w: %q is not a directory", ErrArchive, dir)
	}
	if err := x.own(dir); err != nil {
		return err
	}
	x.made[dir] = true
	x.sum.Directories++
	return nil
}

// mkdirParents creates the missing parents of name. Each one it creates
// counts as an entry.
func (x *extractor) mkdirParents(name string) error {
	for i := range len(name) {
		if name[i] != '/' || x.made[name[:i]] {
			continue
		}
		if err := x.entry(); err != nil {
			return err
		}
		if err := x.mkdir(name[:i]); err != nil {
			return err
		}
	}
	return nil
}

// allow sets the decoded budget for entries members so far.
func (x *extractor) allow(entries int64) {
	x.budget.max = x.sum.ExpandedBytes + (entries+1)*entryOverheadBytes + tailBytes
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
	case !utf8.ValidString(n) || strings.ContainsRune(n, 0):
		return "", bad("bad characters")
	case strings.HasPrefix(n, "/"):
		return "", bad("absolute path")
	case path.Clean(n) != n:
		return "", bad("not a clean path")
	}
	parts := strings.Split(n, "/")
	for _, p := range parts {
		if p == ".." || p == "." || !restorableName(p) {
			return "", bad("unsafe path part")
		}
	}
	if !x.allowed[parts[0]] {
		return "", bad("not under a capture root")
	}
	if len(parts) == 1 && h.Typeflag != tar.TypeDir {
		return "", bad("a capture root must be a directory")
	}
	if parts[0] == TopFilesRoot && len(parts) > 1 {
		f := parts[1]
		switch {
		case len(parts) > 2 || h.Typeflag != tar.TypeReg:
			return "", bad("only regular files go in " + TopFilesRoot)
		case f == TopFilesRoot || strings.HasPrefix(f, ".craft-"):
			return "", bad("reserved file name")
		}
	}
	return n, nil
}

func (x *extractor) run(ctx context.Context, tr *tar.Reader) error {
	var entries int64
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		x.allow(entries)
		h, err := tr.Next()
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return archiveErr(err)
		}
		entries++
		if err := x.entry(); err != nil {
			return err
		}
		name, err := x.memberName(h)
		if err != nil {
			return err
		}
		if err := x.mkdirParents(name); err != nil {
			return err
		}
		mode := fs.FileMode(h.Mode) & fs.ModePerm
		switch h.Typeflag {
		case tar.TypeDir:
			if err := x.mkdir(name); err != nil {
				return err
			}
			if name != TopFilesRoot {
				x.dirs = append(x.dirs, dirMode{name: name, mode: mode, hdr: h})
			}
		case tar.TypeReg:
			if h.Size < 0 {
				return fmt.Errorf("%w: member %q: negative size", ErrArchive, h.Name)
			}
			if x.sum.ExpandedBytes+h.Size > x.lim.ExpandedBytes {
				return fmt.Errorf("%w: the files are over %d bytes", ErrLimit, x.lim.ExpandedBytes)
			}
			x.sum.ExpandedBytes += h.Size
			x.allow(entries)
			if err := x.file(name, mode, h, tr); err != nil {
				return err
			}
			x.sum.Files++
			if top, f, ok := strings.Cut(name, "/"); ok && top == TopFilesRoot {
				x.topFiles = append(x.topFiles, f)
			}
		default:
			// Links, devices, FIFOs, sparse and other members.
			return fmt.Errorf("%w: member %q: type %q is not allowed", ErrArchive, h.Name, h.Typeflag)
		}
		x.present[strings.SplitN(name, "/", 2)[0]] = true
	}
}

func (x *extractor) file(name string, mode fs.FileMode, h *tar.Header, tr *tar.Reader) error {
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
	if err := x.own(name); err != nil {
		return err
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
