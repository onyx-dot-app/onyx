package managed

import (
	"archive/zip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Image is one managed drive image on the node.
type Image struct {
	// ID is the SHA256 of the bundle zip.
	ID string `json:"id"`
	// SHA256 and Size of the ext4 file.
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size_bytes"`
	// UUID is the ext4 UUID (UUIDFor(ID)).
	UUID         string    `json:"fs_uuid"`
	Files        int       `json:"files"`
	ContentBytes int64     `json:"content_bytes"`
	BuiltAt      time.Time `json:"built_at"`
	BuildMS      int64     `json:"build_ms"`
	// Path is the ext4 file. Not stored.
	Path string `json:"-"`
}

var idRE = regexp.MustCompile(`^[0-9a-f]{64}$`)

// ValidID reports whether id is a lowercase SHA256.
func ValidID(id string) bool { return idRE.MatchString(id) }

// UUIDFor returns the ext4 UUID of the image of bundle id. The guest daemon
// checks it before it mounts a drive, so a stale or wrong drive is never
// mounted.
func UUIDFor(id string) string {
	sum := sha256.Sum256([]byte("craft-managed-uuid:" + id))
	u := sum[:16]
	u[6] = u[6]&0x0f | 0x40 // version 4
	u[8] = u[8]&0x3f | 0x80 // RFC 4122 variant
	return fmt.Sprintf("%x-%x-%x-%x-%x", u[0:4], u[4:6], u[6:8], u[8:10], u[10:16])
}

// Stager gives a scratch directory for one unpacked bundle. The real one
// mounts a tmpfs of the bundle limit, so the unpacked files stay in memory
// and cannot fill the data disk.
type Stager interface {
	Stage(dir string, maxBytes int64) (path string, cleanup func() error, err error)
}

// DirStager uses a plain directory (tests, and systems without tmpfs).
type DirStager struct{}

// Stage implements Stager.
func (DirStager) Stage(dir string, _ int64) (string, func() error, error) {
	p, err := os.MkdirTemp(dir, ".stage-")
	if err != nil {
		return "", nil, err
	}
	return p, func() error { return os.RemoveAll(p) }, nil
}

// Mkfs makes an ext4 image of size bytes at path with the content of dir.
type Mkfs func(ctx context.Context, path, dir string, size int64, uuid string, inodes int) error

// Store is the image directory of a node: <dir>/<id>.ext4 and <id>.json.
type Store struct {
	Dir    string
	Limits Limits
	Stager Stager
	Mkfs   Mkfs
	Log    *slog.Logger
	Now    func() time.Time
	// MaxBuilds is the most uploads that receive and build at once on the
	// node (0 means 1). The per-bundle limits do not bound their sum.
	MaxBuilds int

	mu sync.Mutex
	// slots holds one token per running upload (MaxBuilds).
	slots chan struct{}
	// building serializes builds of the same image.
	building map[string]*sync.Mutex
	// verified holds the file identity of images whose hash was checked.
	verified map[string]fileID

	// gcMu orders Pin with GC.
	gcMu sync.Mutex
	pins map[string]int
}

// Pin keeps image id from GC until the returned func runs. A swap pins its
// image from before Get until the VMs record it.
func (s *Store) Pin(id string) func() {
	s.gcMu.Lock()
	defer s.gcMu.Unlock()
	if s.pins == nil {
		s.pins = map[string]int{}
	}
	s.pins[id]++
	var once sync.Once
	return func() {
		once.Do(func() {
			s.gcMu.Lock()
			defer s.gcMu.Unlock()
			if s.pins[id]--; s.pins[id] <= 0 {
				delete(s.pins, id)
			}
		})
	}
}

type fileID struct {
	size    int64
	mtime   int64
	inode   uint64
	present bool
}

func (s *Store) now() time.Time {
	if s.Now != nil {
		return s.Now()
	}
	return time.Now()
}

func (s *Store) imagePath(id string) string { return filepath.Join(s.Dir, id+".ext4") }
func (s *Store) metaPath(id string) string  { return filepath.Join(s.Dir, id+".json") }

// ErrMissing means no image with the ID is on the node.
var ErrMissing = errors.New("managed image is not on this node")

// Get returns an image whose file matches its record. The first Get of an
// image in this process hashes the file; later ones compare its identity.
func (s *Store) Get(id string) (Image, error) {
	if !ValidID(id) {
		return Image{}, fmt.Errorf("%w: image ID %q is not a SHA256", ErrMissing, id)
	}
	raw, err := os.ReadFile(s.metaPath(id))
	if errors.Is(err, fs.ErrNotExist) {
		return Image{}, fmt.Errorf("%w: %s", ErrMissing, id)
	}
	if err != nil {
		return Image{}, err
	}
	var img Image
	if err := json.Unmarshal(raw, &img); err != nil || img.ID != id {
		return Image{}, fmt.Errorf("%w: record of %s is not valid", ErrMissing, id)
	}
	img.Path = s.imagePath(id)
	fid, err := statID(img.Path)
	if err != nil {
		return Image{}, fmt.Errorf("%w: %v", ErrMissing, err)
	}
	if fid.size != img.Size {
		return Image{}, fmt.Errorf("%w: %s has %d bytes, its record has %d", ErrMissing, id, fid.size, img.Size)
	}
	s.mu.Lock()
	ok := s.verified[id] == fid
	s.mu.Unlock()
	if !ok {
		sum, err := fileSHA256(img.Path)
		if err != nil {
			return Image{}, err
		}
		if sum != img.SHA256 {
			return Image{}, fmt.Errorf("%w: %s has SHA256 %s, its record has %s", ErrMissing, id, sum, img.SHA256)
		}
		s.markVerified(id, fid)
	}
	return img, nil
}

func (s *Store) markVerified(id string, fid fileID) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.verified == nil {
		s.verified = map[string]fileID{}
	}
	s.verified[id] = fid
}

// Has reports whether a valid image with the ID is on the node.
func (s *Store) Has(id string) bool {
	_, err := s.Get(id)
	return err == nil
}

func (s *Store) lockID(id string) func() {
	s.mu.Lock()
	if s.building == nil {
		s.building = map[string]*sync.Mutex{}
	}
	l := s.building[id]
	if l == nil {
		l = &sync.Mutex{}
		s.building[id] = l
	}
	s.mu.Unlock()
	l.Lock()
	return l.Unlock
}

// acquire waits for a node-wide upload slot or for ctx to end.
func (s *Store) acquire(ctx context.Context) (func(), error) {
	s.mu.Lock()
	if s.slots == nil {
		s.slots = make(chan struct{}, max(s.MaxBuilds, 1))
	}
	slots := s.slots
	s.mu.Unlock()
	select {
	case slots <- struct{}{}:
		return func() { <-slots }, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// Put reads a bundle zip of size bytes with SHA256 id from r and builds its
// image, unless the image is already there. It returns built false then.
// Errors that wrap ErrBundle are the caller's fault.
func (s *Store) Put(ctx context.Context, id string, size int64, r io.Reader) (Image, bool, error) {
	if !ValidID(id) {
		return Image{}, false, bundleErr("sha256 %q is not 64 lowercase hex characters", id)
	}
	if size <= 0 || size > s.Limits.MaxZipBytes {
		return Image{}, false, bundleErr("zip size %d is not between 1 and %d bytes", size, s.Limits.MaxZipBytes)
	}
	unlock := s.lockID(id)
	defer unlock()
	if img, err := s.Get(id); err == nil {
		return img, false, nil
	}
	release, err := s.acquire(ctx)
	if err != nil {
		return Image{}, false, err
	}
	defer release()
	if err := os.MkdirAll(s.Dir, 0o700); err != nil {
		return Image{}, false, err
	}
	t0 := s.now()
	zipPath, err := s.receive(id, size, r)
	if err != nil {
		return Image{}, false, err
	}
	defer func() { _ = os.Remove(zipPath) }()
	img, err := s.build(ctx, id, zipPath, size)
	if err != nil {
		return Image{}, false, err
	}
	img.BuildMS = s.now().Sub(t0).Milliseconds()
	if err := s.writeMeta(img); err != nil {
		_ = os.Remove(img.Path)
		return Image{}, false, err
	}
	if s.Log != nil {
		s.Log.Info("managed image built", "image", id, "files", img.Files, "content_bytes", img.ContentBytes,
			"size_bytes", img.Size, "ms", img.BuildMS)
	}
	return img, true, nil
}

// receive writes the zip to a temporary file and checks its size and hash.
func (s *Store) receive(id string, size int64, r io.Reader) (string, error) {
	f, err := os.CreateTemp(s.Dir, ".upload-*.zip")
	if err != nil {
		return "", err
	}
	ok := false
	defer func() {
		_ = f.Close()
		if !ok {
			_ = os.Remove(f.Name())
		}
	}()
	h := sha256.New()
	n, err := io.Copy(io.MultiWriter(f, h), io.LimitReader(r, size+1))
	if err != nil {
		return "", err
	}
	if n != size {
		return "", bundleErr("got %d bytes, the header says %d", n, size)
	}
	if got := hex.EncodeToString(h.Sum(nil)); got != id {
		return "", bundleErr("the zip has SHA256 %s, the header says %s", got, id)
	}
	ok = true
	return f.Name(), nil
}

func (s *Store) build(ctx context.Context, id, zipPath string, size int64) (Image, error) {
	zf, err := os.Open(zipPath)
	if err != nil {
		return Image{}, err
	}
	defer func() { _ = zf.Close() }()
	zr, err := zip.NewReader(zf, size)
	if err != nil && !errors.Is(err, zip.ErrInsecurePath) {
		return Image{}, bundleErr("not a zip: %v", err)
	}
	if err != nil {
		return Image{}, bundleErr("%v", err)
	}
	stager := s.Stager
	if stager == nil {
		stager = DirStager{}
	}
	stage, cleanup, err := stager.Stage(s.Dir, s.Limits.MaxBytes)
	if err != nil {
		return Image{}, fmt.Errorf("stage: %w", err)
	}
	defer func() {
		if err := cleanup(); err != nil && s.Log != nil {
			s.Log.Error("remove managed bundle stage", "dir", stage, "err", err)
		}
	}()
	// The stage root is the drive root: root-owned 0755.
	if err := os.Chmod(stage, 0o755); err != nil {
		return Image{}, err
	}
	st, err := Extract(zr, stage, s.Limits)
	if err != nil {
		return Image{}, err
	}
	mkfs := s.Mkfs
	if mkfs == nil {
		mkfs = MkfsExt4
	}
	uuid := UUIDFor(id)
	inodes := st.Files + st.Dirs + 64
	imgSize := ImageSize(st, inodes)
	tmp := filepath.Join(s.Dir, ".build-"+id+".ext4")
	_ = os.Remove(tmp)
	// The estimate is generous; a full file system gets two more tries.
	for try := 0; ; try++ {
		err = mkfs(ctx, tmp, stage, imgSize, uuid, inodes)
		if err == nil {
			break
		}
		_ = os.Remove(tmp)
		if try == 2 || ctx.Err() != nil {
			return Image{}, fmt.Errorf("make the managed image: %w", err)
		}
		imgSize = roundMiB(imgSize * 2)
	}
	sum, err := fileSHA256(tmp)
	if err != nil {
		_ = os.Remove(tmp)
		return Image{}, err
	}
	if err := os.Chmod(tmp, 0o644); err != nil {
		_ = os.Remove(tmp)
		return Image{}, err
	}
	if err := os.Rename(tmp, s.imagePath(id)); err != nil {
		_ = os.Remove(tmp)
		return Image{}, err
	}
	fid, err := statID(s.imagePath(id))
	if err != nil {
		return Image{}, err
	}
	s.markVerified(id, fid)
	return Image{
		ID: id, SHA256: sum, Size: fid.size, UUID: uuid, Files: st.Files, ContentBytes: st.Bytes,
		BuiltAt: s.now().UTC(), Path: s.imagePath(id),
	}, nil
}

// ImageSize estimates the ext4 size for a tree: 4 KiB per data block, per
// directory and per 16 inodes, plus 10 % and 4 MiB of metadata, rounded up
// to 1 MiB.
func ImageSize(st Stats, inodes int) int64 {
	b := (st.Blocks + int64(st.Dirs) + 1 + int64(inodes)/16 + 1) * 4096
	return roundMiB(b + b/10 + 4<<20)
}

func roundMiB(n int64) int64 { return (n + (1 << 20) - 1) &^ ((1 << 20) - 1) }

func (s *Store) writeMeta(img Image) error {
	raw, err := json.MarshalIndent(img, "", "  ")
	if err != nil {
		return err
	}
	tmp := s.metaPath(img.ID) + ".tmp"
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(append(raw, '\n')); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmp, s.metaPath(img.ID)); err != nil {
		return err
	}
	d, err := os.Open(s.Dir)
	if err != nil {
		return err
	}
	defer func() { _ = d.Close() }()
	return d.Sync()
}

// List returns every valid image, newest first.
func (s *Store) List() ([]Image, error) {
	ents, err := os.ReadDir(s.Dir)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []Image
	for _, e := range ents {
		id, ok := strings.CutSuffix(e.Name(), ".json")
		if !ok || !ValidID(id) {
			continue
		}
		if img, err := s.Get(id); err == nil {
			out = append(out, img)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if !out[i].BuiltAt.Equal(out[j].BuiltAt) {
			return out[i].BuiltAt.After(out[j].BuiltAt)
		}
		return out[i].ID > out[j].ID
	})
	return out, nil
}

// GC keeps the keep newest images, every pinned image and every image in
// inUse(), and removes the others (also files of broken or unfinished
// images). inUse runs after the pins are frozen. Each removal holds the
// image's Put lock, so an image that a Put publishes during GC is kept. A VM
// chroot has its own reflink copy of an image, so GC never changes a running
// VM's drive.
func (s *Store) GC(keep int, inUse func() map[string]bool) ([]string, error) {
	s.gcMu.Lock()
	defer s.gcMu.Unlock()
	used := inUse()
	imgs, err := s.List()
	if err != nil {
		return nil, err
	}
	valid := map[string]bool{}
	var removed []string
	for i, img := range imgs {
		valid[img.ID] = true
		if i < keep || used[img.ID] || s.pins[img.ID] > 0 {
			continue
		}
		unlock, ok := s.tryLockID(img.ID)
		if !ok {
			continue
		}
		err := s.remove(img.ID)
		unlock()
		if err != nil {
			return removed, err
		}
		removed = append(removed, img.ID)
	}
	ents, err := os.ReadDir(s.Dir)
	if err != nil {
		return removed, err
	}
	for _, e := range ents {
		name := e.Name()
		id := strings.TrimSuffix(strings.TrimSuffix(name, ".json"), ".ext4")
		if !ValidID(id) || valid[id] || used[id] || s.pins[id] > 0 {
			continue
		}
		unlock, ok := s.tryLockID(id)
		if !ok {
			continue // a Put of id runs
		}
		// A Put that ended after List published a valid image: keep it.
		if s.Has(id) {
			unlock()
			continue
		}
		err := os.Remove(filepath.Join(s.Dir, name))
		unlock()
		if err != nil && !errors.Is(err, fs.ErrNotExist) {
			return removed, err
		}
	}
	return removed, nil
}

// RemoveUnused removes image id unless it is pinned, in inUse(), or a Put of
// it runs. It returns false if the image is kept or missing.
func (s *Store) RemoveUnused(id string, inUse func() map[string]bool) (bool, error) {
	if !ValidID(id) {
		return false, fmt.Errorf("invalid managed image id %q", id)
	}
	s.gcMu.Lock()
	defer s.gcMu.Unlock()
	if s.pins[id] > 0 || inUse()[id] || !s.Has(id) {
		return false, nil
	}
	unlock, ok := s.tryLockID(id)
	if !ok {
		return false, nil
	}
	defer unlock()
	return true, s.remove(id)
}

// tryLockID takes the Put lock of id if no Put of id runs.
func (s *Store) tryLockID(id string) (func(), bool) {
	s.mu.Lock()
	if s.building == nil {
		s.building = map[string]*sync.Mutex{}
	}
	l := s.building[id]
	if l == nil {
		l = &sync.Mutex{}
		s.building[id] = l
	}
	s.mu.Unlock()
	if !l.TryLock() {
		return nil, false
	}
	return l.Unlock, true
}

func (s *Store) remove(id string) error {
	s.mu.Lock()
	delete(s.verified, id)
	s.mu.Unlock()
	// The record goes first: an image without a record is not valid.
	for _, p := range []string{s.metaPath(id), s.imagePath(id)} {
		if err := os.Remove(p); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
	}
	return nil
}

// CleanStaging removes uploads, builds and stages that an agent left when it
// stopped. Call it before the first Put. unmount detaches a tmpfs stage.
func (s *Store) CleanStaging(unmount func(string) error) error {
	ents, err := os.ReadDir(s.Dir)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	for _, e := range ents {
		n := e.Name()
		if !strings.HasPrefix(n, ".upload-") && !strings.HasPrefix(n, ".build-") && !strings.HasPrefix(n, ".stage-") &&
			!strings.HasSuffix(n, ".json.tmp") {
			continue
		}
		p := filepath.Join(s.Dir, n)
		if strings.HasPrefix(n, ".stage-") && unmount != nil {
			_ = unmount(p)
		}
		if err := os.RemoveAll(p); err != nil {
			return err
		}
	}
	return nil
}

// MkfsExt4 runs mkfs.ext4 -d: an ext4 with no journal (the drive is
// read-only), root-owned, with the given UUID and inode count.
func MkfsExt4(ctx context.Context, path, dir string, size int64, uuid string, inodes int) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	if err := f.Truncate(size); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	cmd := exec.CommandContext(ctx, "mkfs.ext4", "-q", "-F", "-b", "4096", "-I", "256", "-N", strconv.Itoa(inodes), "-m", "0",
		"-O", "^has_journal", "-E", "root_owner=0:0", "-L", "managed", "-U", uuid, "-d", dir, path)
	if out, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("mkfs.ext4: %v: %s", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func fileSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer func() { _ = f.Close() }()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func statID(path string) (fileID, error) {
	fi, err := os.Lstat(path)
	if err != nil {
		return fileID{}, err
	}
	if !fi.Mode().IsRegular() {
		return fileID{}, fmt.Errorf("%s is not a regular file", path)
	}
	id := fileID{size: fi.Size(), mtime: fi.ModTime().UnixNano(), present: true}
	if st, ok := fi.Sys().(*syscall.Stat_t); ok {
		id.inode = uint64(st.Ino)
	}
	return id, nil
}
