package files

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"regexp"
	"slices"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"
)

// Type is the kind of a file.
type Type int

// File kinds.
const (
	TypeUnknown Type = iota
	TypeRegular
	TypeDirectory
	TypeSymlink
	TypeOther
)

// Info describes one file.
type Info struct {
	// Path is session-relative, "/"-separated.
	Path    string
	Name    string
	Type    Type
	Size    int64
	Mode    uint32
	ModTime time.Time
	// LinkTarget is set for a symlink.
	LinkTarget string
}

func typeOf(m fs.FileMode) Type {
	switch {
	case m.IsRegular():
		return TypeRegular
	case m.IsDir():
		return TypeDirectory
	case m&fs.ModeSymlink != 0:
		return TypeSymlink
	default:
		return TypeOther
	}
}

func infoOf(p string, fi fs.FileInfo) Info {
	return Info{
		Path: p, Name: path.Base(p), Type: typeOf(fi.Mode()), Size: fi.Size(),
		Mode: uint32(fi.Mode().Perm()), ModTime: fi.ModTime(),
	}
}

// Read sends a regular file: info first, then the bytes from off. length 0
// sends to the end of the file.
func (s *Store) Read(ctx context.Context, sessionID, p string, off, length int64,
	info func(Info) error, data func([]byte) error) error {
	if off < 0 || length < 0 {
		return fmt.Errorf("%w: offset and length must not be negative", ErrInvalid)
	}
	t, err := s.openRead(sessionID, p)
	if err != nil {
		return err
	}
	defer func() { _ = t.root.Close() }()
	f, fi, err := openRegular(t.root, t.rel, 0)
	if err != nil {
		if errors.Is(err, errNotRegular) {
			return fmt.Errorf("%w: %s is not a regular file", ErrInvalid, p)
		}
		return fsErr(err)
	}
	defer func() { _ = f.Close() }()
	size := fi.Size()
	if off > size {
		return fmt.Errorf("%w: offset %d is past the end (%d bytes)", ErrInvalid, off, size)
	}
	n := size - off
	if length > 0 && length < n {
		n = length
	}
	if n > s.cfg.MaxFileBytes {
		return fmt.Errorf("%w: read of %d bytes is over %d; read a range", ErrLimit, n, s.cfg.MaxFileBytes)
	}
	if err := info(infoOf(t.join(t.rel), fi)); err != nil {
		return err
	}
	buf := make([]byte, ChunkBytes)
	for n > 0 {
		if err := ctx.Err(); err != nil {
			return err
		}
		k, err := f.ReadAt(buf[:min(int64(len(buf)), n)], off)
		if k > 0 {
			if err := data(buf[:k]); err != nil {
				return err
			}
			off += int64(k)
			n -= int64(k)
		}
		if errors.Is(err, io.EOF) {
			// The file shrank after Stat.
			return nil
		}
		if err != nil {
			return err
		}
	}
	return nil
}

var errNotRegular = errors.New("not a regular file")

// openRegular opens rel read-only and returns it only if it is a regular
// file. O_NONBLOCK keeps the open of a FIFO without a writer from blocking;
// it has no effect on reads of a regular file.
func openRegular(root *os.Root, rel string, flags int) (*os.File, fs.FileInfo, error) {
	f, err := root.OpenFile(rel, os.O_RDONLY|syscall.O_NONBLOCK|flags, 0)
	if err != nil {
		return nil, nil, err
	}
	fi, err := f.Stat()
	if err == nil && !fi.Mode().IsRegular() {
		err = errNotRegular
	}
	if err != nil {
		_ = f.Close()
		return nil, nil, err
	}
	return f, fi, nil
}

// WriteSpec is the header of a write.
type WriteSpec struct {
	Path string
	// Size is the exact byte count of the data.
	Size int64
	// SHA256 is optional (hex).
	SHA256      string
	Mode        uint32
	Overwrite   bool
	MakeParents bool
}

var hexSHA256 = regexp.MustCompile(`^[0-9a-f]{64}$`)

func (s *Store) checkData(size int64, sum string) (string, error) {
	if size < 0 || size > s.cfg.MaxFileBytes {
		return "", fmt.Errorf("%w: size must be 0 to %d bytes, got %d", ErrLimit, s.cfg.MaxFileBytes, size)
	}
	sum = strings.ToLower(sum)
	if sum != "" && !hexSHA256.MatchString(sum) {
		return "", fmt.Errorf("%w: sha256 must be 64 hex characters", ErrInvalid)
	}
	return sum, nil
}

// spool writes exactly size bytes of r to a new temporary file in dir and
// checks the SHA-256. It returns the temp name and the hex SHA-256.
func (s *Store) spool(ctx context.Context, root *os.Root, dir string, size int64, want string, mode fs.FileMode, r io.Reader) (string, string, error) {
	tmp := path.Join(dir, randName(writePrefix))
	f, err := root.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return "", "", fsErr(err)
	}
	ok := false
	defer func() {
		if !ok {
			_ = f.Close()
			_ = root.Remove(tmp)
		}
	}()
	h := sha256.New()
	n, err := io.Copy(io.MultiWriter(f, h), &ctxReader{ctx: ctx, r: io.LimitReader(r, size+1)})
	if err != nil {
		return "", "", err
	}
	if n != size {
		return "", "", fmt.Errorf("%w: got %d bytes, the header says %d", ErrInvalid, n, size)
	}
	got := hex.EncodeToString(h.Sum(nil))
	if want != "" && got != want {
		return "", "", fmt.Errorf("%w: sha256 of the data is %s, the header says %s", ErrInvalid, got, want)
	}
	if err := f.Chmod(mode); err != nil {
		return "", "", err
	}
	if err := s.ownFile(f, tmp); err != nil {
		return "", "", err
	}
	if err := f.Close(); err != nil {
		return "", "", err
	}
	ok = true
	return tmp, got, nil
}

type ctxReader struct {
	ctx context.Context
	r   io.Reader
}

func (c *ctxReader) Read(p []byte) (int, error) {
	if err := c.ctx.Err(); err != nil {
		return 0, err
	}
	return c.r.Read(p)
}

// Write stores r at spec.Path. The path changes only if all bytes arrive
// and match the header.
func (s *Store) Write(ctx context.Context, sessionID string, spec WriteSpec, r io.Reader) (Info, string, error) {
	want, err := s.checkData(spec.Size, spec.SHA256)
	if err != nil {
		return Info{}, "", err
	}
	mode := fs.FileMode(spec.Mode) & fs.ModePerm
	if mode == 0 {
		mode = 0o644
	}
	root, rel, shown, err := s.openWrite(sessionID, spec.Path, spec.MakeParents)
	if err != nil {
		return Info{}, "", err
	}
	defer func() { _ = root.Close() }()
	dir := parentOf(rel)
	if err := s.ensureDir(root, dir, spec.MakeParents); err != nil {
		return Info{}, "", err
	}
	if fi, err := root.Lstat(rel); err == nil {
		switch {
		case !spec.Overwrite:
			return Info{}, "", fmt.Errorf("%w: %s", ErrExists, rel)
		case fi.IsDir():
			return Info{}, "", fmt.Errorf("%w: %s is a directory", ErrInvalid, rel)
		}
	}
	tmp, sum, err := s.spool(ctx, root, dir, spec.Size, want, mode, r)
	if err != nil {
		return Info{}, "", err
	}
	if spec.Overwrite {
		err = root.Rename(tmp, rel)
	} else {
		err = linkNoReplace(root, tmp, rel)
	}
	if err != nil {
		_ = root.Remove(tmp)
		return Info{}, "", fsErr(err)
	}
	fi, err := root.Lstat(rel)
	if err != nil {
		return Info{}, "", err
	}
	return infoOf(shown, fi), sum, nil
}

// openWrite opens the root of a write and the path in it, and the path to
// report. With no session ID, p is an absolute VM path.
func (s *Store) openWrite(sessionID, p string, mkParents bool) (*os.Root, string, string, error) {
	if sessionID == "" {
		e, err := s.openVMEntry(p, mkParents, true)
		return e.root, e.name, e.abs, err
	}
	rel, err := cleanPath(p)
	if err != nil {
		return nil, "", "", err
	}
	if rel == "." {
		return nil, "", "", fmt.Errorf("%w: path is required", ErrInvalid)
	}
	root, err := s.openSession(sessionID, true)
	if err != nil {
		return nil, "", "", err
	}
	return root, rel, rel, nil
}

// linkNoReplace moves tmp to name unless name exists.
func linkNoReplace(root *os.Root, tmp, name string) error {
	if err := root.Link(tmp, name); err != nil {
		return err
	}
	return root.Remove(tmp)
}

func (s *Store) ensureDir(root *os.Root, dir string, create bool) error {
	if dir == "." {
		return nil
	}
	if create {
		return s.mkdirAll(root, dir)
	}
	fi, err := root.Stat(dir)
	if err != nil {
		return fsErr(err)
	}
	if !fi.IsDir() {
		return fmt.Errorf("%w: %s is not a directory", ErrInvalid, dir)
	}
	return nil
}

// UploadSpec is the header of an upload.
type UploadSpec struct {
	FileName string
	Size     int64
	SHA256   string
	// Directory is session-relative. Default "attachments".
	Directory string
}

var unsafeName = regexp.MustCompile(`[\x00-\x1f\x7f/\\]`)

// SafeFileName returns name with unsafe characters replaced by "_".
func SafeFileName(name string) (string, error) {
	n := strings.TrimSpace(unsafeName.ReplaceAllString(name, "_"))
	if err := checkName(n); err != nil {
		return "", err
	}
	return n, nil
}

// Upload stores r in the upload directory under a free name: name, then
// stem_1.ext, stem_2.ext, ...
func (s *Store) Upload(ctx context.Context, sessionID string, spec UploadSpec, r io.Reader) (Info, string, error) {
	want, err := s.checkData(spec.Size, spec.SHA256)
	if err != nil {
		return Info{}, "", err
	}
	name, err := SafeFileName(spec.FileName)
	if err != nil {
		return Info{}, "", err
	}
	dirIn := spec.Directory
	if dirIn == "" {
		dirIn = "attachments"
	}
	dir, err := cleanPath(dirIn)
	if err != nil {
		return Info{}, "", err
	}
	root, err := s.openSession(sessionID, true)
	if err != nil {
		return Info{}, "", err
	}
	defer func() { _ = root.Close() }()
	if err := s.ensureDir(root, dir, true); err != nil {
		return Info{}, "", err
	}
	tmp, sum, err := s.spool(ctx, root, dir, spec.Size, want, 0o644, r)
	if err != nil {
		return Info{}, "", err
	}
	defer func() { _ = root.Remove(tmp) }()
	stem, ext := name, ""
	if i := strings.LastIndex(name, "."); i > 0 {
		stem, ext = name[:i], name[i:]
	}
	for i := 0; i < 10_000; i++ {
		cand := name
		if i > 0 {
			cand = fmt.Sprintf("%s_%d%s", stem, i, ext)
			if len(cand) > maxNameBytes {
				break
			}
		}
		rel := path.Join(dir, cand)
		if err := root.Link(tmp, rel); err != nil {
			if errors.Is(err, fs.ErrExist) {
				continue
			}
			return Info{}, "", fsErr(err)
		}
		fi, err := root.Lstat(rel)
		if err != nil {
			return Info{}, "", err
		}
		return infoOf(rel, fi), sum, nil
	}
	return Info{}, "", fmt.Errorf("%w: no free name for %s", ErrExists, name)
}

// ListSpec is one list call.
type ListSpec struct {
	Path       string
	Recursive  bool
	MaxDepth   int
	Exclude    []string
	SkipHidden bool
	MaxEntries int
}

// MaxListEntries caps ListSpec.MaxEntries.
const MaxListEntries = 100_000

// listScanCap caps the entries List reads from one directory.
var listScanCap = MaxListEntries

// List returns the entries of a directory (or a tree), directories first
// and then by name, per directory. truncated is true if a limit cut it.
func (s *Store) List(ctx context.Context, sessionID string, spec ListSpec) ([]Info, bool, error) {
	if spec.MaxEntries < 0 || spec.MaxEntries > MaxListEntries || spec.MaxDepth < 0 {
		return nil, false, fmt.Errorf("%w: max_entries must be 0 to %d", ErrInvalid, MaxListEntries)
	}
	if spec.MaxEntries == 0 {
		spec.MaxEntries = 10_000
	}
	if spec.MaxDepth == 0 {
		spec.MaxDepth = 64
	}
	t, err := s.openRead(sessionID, spec.Path)
	if err != nil {
		return nil, false, err
	}
	defer func() { _ = t.root.Close() }()
	fi, err := t.root.Stat(t.rel)
	if err != nil {
		return nil, false, fsErr(err)
	}
	if !fi.IsDir() {
		return nil, false, fmt.Errorf("%w: %s is not a directory", ErrInvalid, spec.Path)
	}
	l := &lister{s: s, t: t, spec: spec, skip: setOf(spec.Exclude)}
	err = l.dir(ctx, t.rel, 0)
	return l.out, l.truncated, err
}

type lister struct {
	s         *Store
	t         readTarget
	spec      ListSpec
	skip      map[string]bool
	out       []Info
	truncated bool
}

func (l *lister) dir(ctx context.Context, rel string, depth int) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	ents, err := readDir(l.t.root, rel, listScanCap)
	if errors.Is(err, errDirTooBig) {
		// List the entries read before the cap, marked truncated.
		l.truncated = true
	} else if err != nil {
		return fsErr(err)
	}
	var subdirs []string
	for _, e := range ents {
		if len(l.out) >= l.spec.MaxEntries {
			l.truncated = true
			return nil
		}
		name := e.Name()
		// Protobuf strings must be UTF-8; such a name would fail the response.
		if l.skip[name] || (l.spec.SkipHidden && strings.HasPrefix(name, ".")) || !utf8.ValidString(name) {
			continue
		}
		child := name
		if rel != "." {
			child = rel + "/" + name
		}
		if l.t.denied(child) {
			continue
		}
		fi, err := e.Info()
		if err != nil {
			continue
		}
		info := infoOf(l.t.join(child), fi)
		if info.Type == TypeSymlink {
			target, _ := l.t.root.Readlink(child)
			info.LinkTarget = strings.ToValidUTF8(target, "\uFFFD")
		}
		l.out = append(l.out, info)
		if info.Type == TypeDirectory {
			subdirs = append(subdirs, child)
		}
	}
	if !l.spec.Recursive {
		return nil
	}
	for _, d := range subdirs {
		if depth+1 >= l.spec.MaxDepth {
			l.truncated = true
			continue
		}
		if err := l.dir(ctx, d, depth+1); err != nil {
			return err
		}
	}
	return nil
}

// errDirTooBig: a directory has more entries than the scan cap of readDir.
var errDirTooBig = fmt.Errorf("%w: directory has too many entries", ErrLimit)

// readDir returns the entries of dir: directories first, then by name
// (case-insensitive, then exact). It reads in batches, so one huge directory
// cannot use unbounded memory: past max entries it returns the first max
// entries read (sorted) with errDirTooBig. O_DIRECTORY|O_NONBLOCK keeps a
// FIFO that replaced dir from blocking the open.
func readDir(root *os.Root, dir string, max int) ([]fs.DirEntry, error) {
	d, err := root.OpenFile(dir, os.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	defer func() { _ = d.Close() }()
	var ents []fs.DirEntry
	var tooBig error
	for {
		batch, err := d.ReadDir(1024)
		ents = append(ents, batch...)
		if len(ents) > max {
			ents = ents[:max]
			tooBig = fmt.Errorf("%w: %s has more than %d", errDirTooBig, dir, max)
			break
		}
		if errors.Is(err, io.EOF) || (err == nil && len(batch) == 0) {
			break
		}
		if err != nil {
			return nil, err
		}
	}
	slices.SortFunc(ents, func(a, b fs.DirEntry) int {
		if ad, bd := a.IsDir(), b.IsDir(); ad != bd {
			if ad {
				return -1
			}
			return 1
		}
		if c := strings.Compare(strings.ToLower(a.Name()), strings.ToLower(b.Name())); c != 0 {
			return c
		}
		return strings.Compare(a.Name(), b.Name())
	})
	return ents, tooBig
}

func setOf(names []string) map[string]bool {
	m := make(map[string]bool, len(names))
	for _, n := range names {
		m[n] = true
	}
	return m
}

// Delete removes a file or a link, or a directory with recursive. It
// reports false if the path did not exist.
func (s *Store) Delete(sessionID, p string, recursive bool) (bool, error) {
	var root *os.Root
	var rel, vmReal string
	var err error
	if sessionID == "" {
		var e vmEntry
		e, err = s.openVMEntry(p, false, false)
		root, rel, vmReal = e.root, e.name, e.real
	} else {
		root, rel, err = s.openDelete(sessionID, p)
	}
	if errors.Is(err, ErrNotFound) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	defer func() { _ = root.Close() }()
	fi, err := root.Lstat(rel)
	if errors.Is(err, fs.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, fsErr(err)
	}
	if fi.IsDir() {
		if !recursive {
			return false, fmt.Errorf("%w: %s is a directory; set recursive", ErrInvalid, rel)
		}
		if vmReal != "" {
			if err := s.checkVMTree(vmReal); err != nil {
				return false, err
			}
		}
		return true, fsErr(root.RemoveAll(rel))
	}
	return true, fsErr(root.Remove(rel))
}

// Rename moves the absolute path from to the name of to in the same
// directory (no session). Without exchange, nothing may be at to. With
// exchange, both must exist and trade places in one step.
func (s *Store) Rename(sessionID, from, to string, exchange bool) error {
	if sessionID != "" {
		return fmt.Errorf("%w: a rename needs absolute paths and no session_id", ErrInvalid)
	}
	toAbs, err := vmPath(to)
	if err != nil {
		return err
	}
	e, err := s.openVMEntry(from, false, false)
	if err != nil {
		return err
	}
	defer func() { _ = e.root.Close() }()
	if path.Dir(e.abs) != path.Dir(toAbs) || e.abs == toAbs {
		return fmt.Errorf("%w: rename %s to %s: not two names in one directory", ErrInvalid, from, to)
	}
	if e.real != "" {
		if err := s.checkVMPath(path.Join(path.Dir(e.real), path.Base(toAbs))); err != nil {
			return err
		}
	}
	dir, err := e.root.Open(path.Dir(e.name))
	if err != nil {
		return fsErr(err)
	}
	defer func() { _ = dir.Close() }()
	return renameAt(dir, path.Base(e.name), path.Base(toAbs), exchange)
}

// Link makes a symlink at the absolute path p (no session) to target,
// stored as given, owned by the configured owner. It makes missing parents,
// and replaces a link at p in one step. Another entry at p fails with
// ErrExists and is not moved; one that a command puts there during the call
// stays too.
func (s *Store) Link(sessionID, p, target string) error {
	if sessionID != "" {
		return fmt.Errorf("%w: a link needs an absolute path and no session_id", ErrInvalid)
	}
	if target == "" || strings.ContainsRune(target, 0) {
		return fmt.Errorf("%w: link target %q", ErrInvalid, target)
	}
	e, err := s.openVMEntry(p, true, false)
	if err != nil {
		return err
	}
	defer func() { _ = e.root.Close() }()
	// A path in the onyx root opens on that root, with its parents still to
	// make.
	parent := path.Dir(e.name)
	if err := s.mkdirAll(e.root, parent); err != nil {
		return err
	}
	// A folder or file the model made stays where it is: never moved aside
	// to learn its type.
	if fi, err := e.root.Lstat(e.name); err == nil && fi.Mode()&fs.ModeSymlink == 0 {
		return fmt.Errorf("%w: %s is not a link", ErrExists, p)
	} else if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return fsErr(err)
	}
	dir, err := e.root.Open(parent)
	if err != nil {
		return fsErr(err)
	}
	defer func() { _ = dir.Close() }()
	name, tmp := path.Base(e.name), randName(writePrefix)
	if err := e.root.Symlink(target, path.Join(parent, tmp)); err != nil {
		return fsErr(err)
	}
	// Delete the temporary name only while it holds this call's link: a
	// command can move another entry there between the steps below.
	drop := func() {
		if got, err := e.root.Readlink(path.Join(parent, tmp)); err == nil && got == target {
			_ = e.root.Remove(path.Join(parent, tmp))
		}
	}
	if o := s.cfg.Owner; o != nil {
		if err := e.root.Lchown(path.Join(parent, tmp), o.UID, o.GID); err != nil {
			drop()
			return fmt.Errorf("set the owner of %s: %w", p, err)
		}
	}
	if s.linkChecked != nil {
		s.linkChecked()
	}
	// Nothing at p: the link goes in, unless an entry appears first.
	err = renameAt(dir, tmp, name, false)
	if err == nil || !errors.Is(err, ErrExists) {
		if err != nil {
			drop()
		}
		return err
	}
	// A link at p: swap, and keep the swap only if it took out a link (a
	// command can replace the link after the check above).
	if err := renameAt(dir, tmp, name, true); err != nil {
		drop()
		return err
	}
	if s.linkSwapped != nil {
		s.linkSwapped()
	}
	fi, err := e.root.Lstat(path.Join(parent, tmp))
	if err == nil && fi.Mode()&fs.ModeSymlink != 0 {
		_ = e.root.Remove(path.Join(parent, tmp))
		return nil
	}
	if err := renameAt(dir, tmp, name, true); err != nil {
		return fmt.Errorf("put back the entry at %s: %w", p, err)
	}
	drop()
	return fmt.Errorf("%w: %s is not a link", ErrExists, p)
}

func (s *Store) openDelete(sessionID, p string) (*os.Root, string, error) {
	rel, err := cleanPath(p)
	if err != nil {
		return nil, "", err
	}
	if rel == "." {
		return nil, "", fmt.Errorf("%w: cannot delete the session directory", ErrInvalid)
	}
	root, err := s.openSession(sessionID, false)
	return root, rel, err
}

// Stat limits: paths per call, and their bytes in all, so the request fits
// the daemon's gRPC message limit (4 MiB) and the answer, with a link
// target of at most 4,096 bytes per path, the 16 MiB pass-through limit.
const (
	MaxStatPaths     = 1000
	MaxStatPathBytes = 1 << 20
)

// StatErr is why a path's target has no facts.
type StatErr int

// Stat target errors.
const (
	StatOK StatErr = iota
	// StatMissing: the path or a link on it leads to nothing.
	StatMissing
	// StatEscapes: a link on the path leads out of the session directory.
	StatEscapes
	// StatLoop: the links on the path loop.
	StatLoop
	// StatOther: another error, such as a file used as a directory.
	StatOther
)

// PathStat is what Stat reports for one path: its own entry (Lstat) and,
// through its links inside the session directory, its target (Stat).
type PathStat struct {
	Path string
	// The entry itself (a broken link exists).
	Exists bool
	Type   Type
	Mode   uint32
	// LinkTarget is the stored target of a link; bytes that are not valid
	// UTF-8 become U+FFFD.
	LinkTarget string
	// The target, set when TargetErr is StatOK.
	TargetErr  StatErr
	TargetType Type
	TargetMode uint32
	// Device and Inode identify the target: two paths with the same
	// identity name one file.
	Device, Inode uint64
}

// Stat reports what os.Root knows of session paths, one at a time. It reads
// no content and fails only for the whole request (a bad path, a limit, a
// cancel); a missing path or a link that leaves the session is a per-path
// answer. A session that has no directory yet has only missing paths.
func (s *Store) Stat(ctx context.Context, sessionID string, paths []string) ([]PathStat, error) {
	if sessionID == "" {
		return nil, fmt.Errorf("%w: StatFiles needs a session_id", ErrInvalid)
	}
	if len(paths) > MaxStatPaths {
		return nil, fmt.Errorf("%w: %d paths; at most %d per call", ErrLimit, len(paths), MaxStatPaths)
	}
	size := 0
	for _, p := range paths {
		size += len(p)
	}
	if size > MaxStatPathBytes {
		return nil, fmt.Errorf("%w: %d bytes of paths; at most %d per call", ErrLimit, size, MaxStatPathBytes)
	}
	rels := make([]string, len(paths))
	for i, p := range paths {
		rel, err := cleanPath(p)
		if err != nil {
			return nil, err
		}
		rels[i] = rel
	}
	out := make([]PathStat, len(rels))
	sr, err := s.openSession(sessionID, false)
	if errors.Is(err, ErrNotFound) {
		for i, rel := range rels {
			out[i] = PathStat{Path: rel, TargetErr: StatMissing}
		}
		return out, nil
	}
	if err != nil {
		return nil, err
	}
	defer func() { _ = sr.Close() }()
	for i, rel := range rels {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		out[i] = statPath(sr, rel)
	}
	return out, nil
}

func statPath(root *os.Root, rel string) PathStat {
	st := PathStat{Path: rel}
	if fi, err := root.Lstat(rel); err == nil {
		st.Exists = true
		st.Type = typeOf(fi.Mode())
		st.Mode = uint32(fi.Mode().Perm())
		if st.Type == TypeSymlink {
			if target, err := root.Readlink(rel); err == nil {
				st.LinkTarget = strings.ToValidUTF8(target, "\uFFFD")
			}
		}
	}
	fi, err := root.Stat(rel)
	if err != nil {
		st.TargetErr = statErr(err)
		return st
	}
	st.TargetType = typeOf(fi.Mode())
	st.TargetMode = uint32(fi.Mode().Perm())
	if sys, ok := fi.Sys().(*syscall.Stat_t); ok {
		st.Device, st.Inode = uint64(sys.Dev), uint64(sys.Ino) //nolint:unconvert // Dev is int32 on darwin
	}
	return st
}

// errPathEscapes is the error that os.Root wraps for a path that leaves the
// root (absolute link targets included). The os package does not export it.
var errPathEscapes = func() error {
	root, err := os.OpenRoot("/")
	if err != nil {
		return nil
	}
	defer func() { _ = root.Close() }()
	_, err = root.Lstat("..")
	var pathErr *fs.PathError
	if errors.As(err, &pathErr) {
		return pathErr.Err
	}
	return nil
}()

func statErr(err error) StatErr {
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return StatMissing
	case errors.Is(err, syscall.ELOOP):
		return StatLoop
	case errPathEscapes != nil && errors.Is(err, errPathEscapes):
		return StatEscapes
	default:
		return StatOther
	}
}
