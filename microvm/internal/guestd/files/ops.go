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
	"time"
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
	f, err := t.root.Open(t.rel)
	if err != nil {
		return fsErr(err)
	}
	defer func() { _ = f.Close() }()
	fi, err := f.Stat()
	if err != nil {
		return err
	}
	if !fi.Mode().IsRegular() {
		return fmt.Errorf("%w: %s is not a regular file", ErrInvalid, p)
	}
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
func spool(ctx context.Context, root *os.Root, dir string, size int64, want string, mode fs.FileMode, r io.Reader) (string, string, error) {
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
	rel, err := cleanPath(spec.Path)
	if err != nil {
		return Info{}, "", err
	}
	if rel == "." {
		return Info{}, "", fmt.Errorf("%w: path is required", ErrInvalid)
	}
	mode := fs.FileMode(spec.Mode) & fs.ModePerm
	if mode == 0 {
		mode = 0o644
	}
	root, err := s.openSession(sessionID, true)
	if err != nil {
		return Info{}, "", err
	}
	defer func() { _ = root.Close() }()
	dir := parentOf(rel)
	if err := ensureDir(root, dir, spec.MakeParents); err != nil {
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
	tmp, sum, err := spool(ctx, root, dir, spec.Size, want, mode, r)
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
	return infoOf(rel, fi), sum, nil
}

// linkNoReplace moves tmp to name unless name exists.
func linkNoReplace(root *os.Root, tmp, name string) error {
	if err := root.Link(tmp, name); err != nil {
		return err
	}
	return root.Remove(tmp)
}

func ensureDir(root *os.Root, dir string, create bool) error {
	if dir == "." {
		return nil
	}
	if create {
		return fsErr(root.MkdirAll(dir, 0o755))
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
	if err := ensureDir(root, dir, true); err != nil {
		return Info{}, "", err
	}
	tmp, sum, err := spool(ctx, root, dir, spec.Size, want, 0o644, r)
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
	ents, err := readDir(l.t.root, rel)
	if err != nil {
		return fsErr(err)
	}
	var subdirs []string
	for _, e := range ents {
		if len(l.out) >= l.spec.MaxEntries {
			l.truncated = true
			return nil
		}
		name := e.Name()
		if l.skip[name] || (l.spec.SkipHidden && strings.HasPrefix(name, ".")) {
			continue
		}
		child := name
		if rel != "." {
			child = rel + "/" + name
		}
		fi, err := e.Info()
		if err != nil {
			continue
		}
		info := infoOf(l.t.join(child), fi)
		if info.Type == TypeSymlink {
			info.LinkTarget, _ = l.t.root.Readlink(child)
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

// readDir returns the entries of dir: directories first, then by name
// (case-insensitive, then exact).
func readDir(root *os.Root, dir string) ([]fs.DirEntry, error) {
	d, err := root.Open(dir)
	if err != nil {
		return nil, err
	}
	defer func() { _ = d.Close() }()
	ents, err := d.ReadDir(-1)
	if err != nil {
		return nil, err
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
	return ents, nil
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
	rel, err := cleanPath(p)
	if err != nil {
		return false, err
	}
	if rel == "." {
		return false, fmt.Errorf("%w: cannot delete the session directory", ErrInvalid)
	}
	root, err := s.openSession(sessionID, false)
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
		return true, fsErr(root.RemoveAll(rel))
	}
	return true, fsErr(root.Remove(rel))
}
