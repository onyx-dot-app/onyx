// Package files serves the file calls and the session saves of the guest
// daemon. Every path is relative to the session directory
// <SessionsRoot>/<session_id>, which is opened as an os.Root: a path that
// leaves it (with "..", an absolute path or a symlink) fails.
package files

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"unicode/utf8"

	"github.com/klauspost/compress/zstd"
)

// Errors of this package. Calls wrap them; test with errors.Is.
var (
	ErrInvalid  = errors.New("invalid argument")
	ErrNotFound = errors.New("not found")
	ErrExists   = errors.New("already exists")
	ErrLimit    = errors.New("limit exceeded")
	ErrArchive  = errors.New("invalid archive")
)

const (
	// DefaultSessionsRoot holds one directory per session.
	DefaultSessionsRoot = "/workspace/sessions"
	// GiB is 1 << 30 bytes.
	GiB = int64(1) << 30
	// ChunkBytes is the size of a data message the daemon sends.
	ChunkBytes = 64 << 10
	// maxPathBytes and maxNameBytes are the Linux limits.
	maxPathBytes = 4096
	maxNameBytes = 255
	// Names that the daemon makes in a session directory or in a target
	// directory. Capture skips them.
	stagingPrefix = ".craft-restore-"
	oldPrefix     = ".craft-old-"
	writePrefix   = ".craft-write-"
)

// DefaultCaptureRoots are the session directories that a save holds.
var DefaultCaptureRoots = []string{"attachments"}

// DefaultCaptureExclude are names that a save leaves out at any depth:
// dependencies, build output and caches. A directory with pyvenv.cfg is
// always left out too.
var DefaultCaptureExclude = []string{
	"node_modules", ".venv", "venv", "__pycache__", ".next", ".cache", ".npm", ".pnpm-store", ".yarn", ".bun",
	".pytest_cache", ".mypy_cache", ".ruff_cache", ".turbo", ".parcel-cache",
}

// Limits bound one capture or restore. 0 means the default.
type Limits struct {
	// StoredBytes caps the archive (zstd) bytes.
	StoredBytes int64
	// ExpandedBytes caps the total bytes of the files.
	ExpandedBytes int64
	// Entries caps files plus directories.
	Entries int64
}

// DefaultLimits are 1 GiB stored, 4 GiB expanded and 500,000 entries.
var DefaultLimits = Limits{StoredBytes: GiB, ExpandedBytes: 4 * GiB, Entries: 500_000}

// Config configures a Store. Zero values take the defaults.
type Config struct {
	SessionsRoot string
	// ReadLinkRoots: a top-level link of a session (for example
	// user_library) that points into one of these directories can be
	// followed by Read, List and Zip.
	ReadLinkRoots []string
	// MaxFileBytes caps one Read, Write or Upload. Default 1 GiB.
	MaxFileBytes int64
	// MaxZipBytes caps the input of one Zip. Default 1 GiB.
	MaxZipBytes int64
	// MaxZipEntries caps the files of one Zip. Default 100,000.
	MaxZipEntries int
	CaptureRoots  []string
	// CaptureExclude: nil means DefaultCaptureExclude.
	CaptureExclude []string
	// Limits are the daemon's own capture and restore limits. A request may
	// only lower them.
	Limits Limits
	// ZstdLevel of a capture. 0 means zstd.SpeedFastest (about zstd -1): on
	// 2 vCPUs it is ~9x faster than SpeedDefault and only a few percent larger.
	ZstdLevel zstd.EncoderLevel
}

// Store runs the file calls.
type Store struct {
	cfg Config

	mu    sync.Mutex
	locks map[string]chan struct{}
}

// New checks cfg and returns a Store.
func New(cfg Config) (*Store, error) {
	if cfg.SessionsRoot == "" {
		cfg.SessionsRoot = DefaultSessionsRoot
	}
	if !filepath.IsAbs(cfg.SessionsRoot) {
		return nil, fmt.Errorf("sessions root %q is not absolute", cfg.SessionsRoot)
	}
	for _, r := range cfg.ReadLinkRoots {
		if !filepath.IsAbs(r) {
			return nil, fmt.Errorf("read link root %q is not absolute", r)
		}
	}
	if cfg.MaxFileBytes == 0 {
		cfg.MaxFileBytes = GiB
	}
	if cfg.MaxZipBytes == 0 {
		cfg.MaxZipBytes = GiB
	}
	if cfg.MaxZipEntries == 0 {
		cfg.MaxZipEntries = 100_000
	}
	if cfg.CaptureRoots == nil {
		cfg.CaptureRoots = DefaultCaptureRoots
	}
	if cfg.CaptureExclude == nil {
		cfg.CaptureExclude = DefaultCaptureExclude
	}
	if err := checkNames(cfg.CaptureRoots); err != nil {
		return nil, fmt.Errorf("capture roots: %w", err)
	}
	if len(cfg.CaptureRoots) == 0 {
		return nil, errors.New("no capture roots")
	}
	if cfg.ZstdLevel == 0 {
		cfg.ZstdLevel = zstd.SpeedFastest
	}
	if cfg.Limits.StoredBytes == 0 {
		cfg.Limits.StoredBytes = DefaultLimits.StoredBytes
	}
	if cfg.Limits.ExpandedBytes == 0 {
		cfg.Limits.ExpandedBytes = DefaultLimits.ExpandedBytes
	}
	if cfg.Limits.Entries == 0 {
		cfg.Limits.Entries = DefaultLimits.Entries
	}
	if cfg.MaxFileBytes < 0 || cfg.MaxZipBytes < 0 || cfg.MaxZipEntries < 0 ||
		cfg.Limits.StoredBytes < 0 || cfg.Limits.ExpandedBytes < 0 || cfg.Limits.Entries < 0 {
		return nil, errors.New("limits must not be negative")
	}
	return &Store{cfg: cfg, locks: map[string]chan struct{}{}}, nil
}

// Config returns the effective configuration.
func (s *Store) Config() Config { return s.cfg }

// limits merges request limits with the daemon's own.
func (s *Store) limits(req Limits) (Limits, error) {
	out := s.cfg.Limits
	pick := func(name string, v, max int64, dst *int64) error {
		switch {
		case v < 0:
			return fmt.Errorf("%w: %s must not be negative", ErrInvalid, name)
		case v > max:
			return fmt.Errorf("%w: %s %d is over the daemon limit %d", ErrInvalid, name, v, max)
		case v > 0:
			*dst = v
		}
		return nil
	}
	if err := pick("max_stored_bytes", req.StoredBytes, s.cfg.Limits.StoredBytes, &out.StoredBytes); err != nil {
		return out, err
	}
	if err := pick("max_expanded_bytes", req.ExpandedBytes, s.cfg.Limits.ExpandedBytes, &out.ExpandedBytes); err != nil {
		return out, err
	}
	if err := pick("max_entries", req.Entries, s.cfg.Limits.Entries, &out.Entries); err != nil {
		return out, err
	}
	return out, nil
}

// ValidSessionID applies the Init rules for a session ID.
func ValidSessionID(id string) error {
	if id == "" || len(id) > 128 || strings.ContainsAny(id, "/\\\x00") || id == "." || id == ".." ||
		strings.HasPrefix(id, ".") {
		return fmt.Errorf("%w: bad session id %q", ErrInvalid, id)
	}
	return nil
}

// checkNames requires single path components.
func checkNames(names []string) error {
	seen := map[string]bool{}
	for _, n := range names {
		if err := checkName(n); err != nil {
			return err
		}
		if seen[n] {
			return fmt.Errorf("%w: duplicate name %q", ErrInvalid, n)
		}
		seen[n] = true
	}
	return nil
}

func checkName(n string) error {
	if n == "" || n == "." || n == ".." || len(n) > maxNameBytes || strings.ContainsAny(n, "/\x00") || !utf8.ValidString(n) {
		return fmt.Errorf("%w: bad name %q", ErrInvalid, n)
	}
	return nil
}

// cleanPath makes a session-relative path: "/"-separated, no "." parts.
// A leading "/" is dropped (the pod runtime accepts it). ".." fails.
// The session directory itself is ".".
func cleanPath(p string) (string, error) {
	if strings.ContainsRune(p, 0) || !utf8.ValidString(p) || len(p) > maxPathBytes {
		return "", fmt.Errorf("%w: bad path %q", ErrInvalid, p)
	}
	var parts []string
	for _, c := range strings.Split(strings.TrimLeft(p, "/"), "/") {
		switch c {
		case "", ".":
			continue
		case "..":
			return "", fmt.Errorf("%w: path %q has \"..\"", ErrInvalid, p)
		}
		if len(c) > maxNameBytes {
			return "", fmt.Errorf("%w: a name in %q is too long", ErrInvalid, p)
		}
		parts = append(parts, c)
	}
	if len(parts) == 0 {
		return ".", nil
	}
	return strings.Join(parts, "/"), nil
}

// openSession opens the session directory. With create, a missing one is
// made (mode 0755). The session directory must not be a symlink.
func (s *Store) openSession(id string, create bool) (*os.Root, error) {
	if err := ValidSessionID(id); err != nil {
		return nil, err
	}
	if create {
		if err := os.MkdirAll(s.cfg.SessionsRoot, 0o755); err != nil {
			return nil, err
		}
	}
	base, err := os.OpenRoot(s.cfg.SessionsRoot)
	if err != nil {
		return nil, fsErr(err)
	}
	defer func() { _ = base.Close() }()
	fi, err := base.Lstat(id)
	if errors.Is(err, fs.ErrNotExist) && create {
		if err := base.Mkdir(id, 0o755); err != nil && !errors.Is(err, fs.ErrExist) {
			return nil, err
		}
		fi, err = base.Lstat(id)
	}
	if err != nil {
		return nil, fsErr(err)
	}
	if !fi.IsDir() {
		return nil, fmt.Errorf("%w: session %s is not a directory", ErrInvalid, id)
	}
	r, err := base.OpenRoot(id)
	if err != nil {
		return nil, fsErr(err)
	}
	return r, nil
}

// readTarget is where a read call looks: a root and a path in it. display
// is the session-relative path of the root's top.
type readTarget struct {
	root    *os.Root
	rel     string
	display string
}

// openRead opens the session for a read call. A path whose first part is a
// link into a ReadLinkRoots directory resolves in that directory.
func (s *Store) openRead(id, p string) (readTarget, error) {
	rel, err := cleanPath(p)
	if err != nil {
		return readTarget{}, err
	}
	sr, err := s.openSession(id, false)
	if err != nil {
		return readTarget{}, err
	}
	if rel != "." {
		first, rest, _ := strings.Cut(rel, "/")
		if ar := s.linkRoot(sr, first); ar != nil {
			_ = sr.Close()
			if rest == "" {
				rest = "."
			}
			return readTarget{root: ar, rel: rest, display: first}, nil
		}
	}
	return readTarget{root: sr, rel: rel}, nil
}

// linkRoot opens the target of a top-level session link if it is inside a
// ReadLinkRoots directory. Otherwise nil.
func (s *Store) linkRoot(sr *os.Root, name string) *os.Root {
	if len(s.cfg.ReadLinkRoots) == 0 {
		return nil
	}
	fi, err := sr.Lstat(name)
	if err != nil || fi.Mode()&fs.ModeSymlink == 0 {
		return nil
	}
	target, err := sr.Readlink(name)
	if err != nil || !filepath.IsAbs(target) {
		return nil
	}
	real, err := filepath.EvalSymlinks(target)
	if err != nil {
		return nil
	}
	for _, allowed := range s.cfg.ReadLinkRoots {
		ra, err := filepath.EvalSymlinks(allowed)
		if err != nil {
			continue
		}
		if real == ra || strings.HasPrefix(real, ra+string(filepath.Separator)) {
			r, err := os.OpenRoot(real)
			if err != nil {
				return nil
			}
			return r
		}
	}
	return nil
}

func (t readTarget) join(rel string) string {
	switch {
	case t.display == "":
		return rel
	case rel == ".":
		return t.display
	default:
		return t.display + "/" + rel
	}
}

// fsErr maps an os error to this package's errors.
func fsErr(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, fs.ErrNotExist):
		return fmt.Errorf("%w: %v", ErrNotFound, err)
	case errors.Is(err, fs.ErrExist):
		return fmt.Errorf("%w: %v", ErrExists, err)
	case errors.Is(err, syscall.ENOTDIR), errors.Is(err, syscall.ELOOP), strings.Contains(err.Error(), "path escapes from parent"):
		return fmt.Errorf("%w: %v", ErrInvalid, err)
	default:
		return err
	}
}

// lock serializes capture and restore of one session.
func (s *Store) lock(ctx context.Context, id string) (func(), error) {
	s.mu.Lock()
	ch := s.locks[id]
	if ch == nil {
		ch = make(chan struct{}, 1)
		s.locks[id] = ch
	}
	s.mu.Unlock()
	select {
	case ch <- struct{}{}:
		return func() { <-ch }, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func randName(prefix string) string {
	var b [8]byte
	_, _ = rand.Read(b[:])
	return prefix + hex.EncodeToString(b[:])
}

func parentOf(rel string) string {
	d := path.Dir(rel)
	if d == "" {
		return "."
	}
	return d
}
