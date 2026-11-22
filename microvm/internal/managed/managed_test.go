package managed

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"
)

type entry struct {
	name string
	mode fs.FileMode
	data string
}

func makeZip(t *testing.T, entries ...entry) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for _, e := range entries {
		h := &zip.FileHeader{Name: e.name, Method: zip.Deflate}
		mode := e.mode
		if mode == 0 {
			mode = 0o644
		}
		h.SetMode(mode)
		w, err := zw.CreateHeader(h)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := w.Write([]byte(e.data)); err != nil {
			t.Fatal(err)
		}
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func extract(t *testing.T, raw []byte, lim Limits) (string, Stats, error) {
	t.Helper()
	zr, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil {
		t.Fatal(err)
	}
	dst := t.TempDir()
	st, err := Extract(zr, dst, lim)
	return dst, st, err
}

func tree(t *testing.T, root string) []string {
	t.Helper()
	var out []string
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil || p == root {
			return err
		}
		fi, _ := d.Info()
		rel, _ := filepath.Rel(root, p)
		out = append(out, rel+" "+fi.Mode().String())
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(out)
	return out
}

func TestExtractSafeBundle(t *testing.T) {
	raw := makeZip(t,
		entry{name: "skills/"},
		entry{name: "skills/pdf/SKILL.md", data: "# pdf"},
		entry{name: "skills/pdf/run.sh", mode: 0o4755, data: "#!/bin/sh\necho hi\n"},
		entry{name: "deep/a/b/c.txt", mode: 0o600, data: "x"},
	)
	dst, st, err := extract(t, raw, DefaultLimits)
	if err != nil {
		t.Fatal(err)
	}
	got := strings.Join(tree(t, dst), "\n")
	want := strings.Join([]string{
		"deep drwxr-xr-x", "deep/a drwxr-xr-x", "deep/a/b drwxr-xr-x", "deep/a/b/c.txt -rw-r--r--",
		"skills drwxr-xr-x", "skills/pdf drwxr-xr-x", "skills/pdf/SKILL.md -rw-r--r--", "skills/pdf/run.sh -rwxr-xr-x",
	}, "\n")
	if got != want {
		t.Fatalf("tree:\n%s\nwant:\n%s", got, want)
	}
	if st.Files != 3 || st.Dirs != 5 || st.Bytes != int64(len("# pdf")+len("#!/bin/sh\necho hi\n")+1) || st.Blocks != 3 {
		t.Fatalf("stats %+v", st)
	}
}

func TestExtractRejectsUnsafeBundles(t *testing.T) {
	for name, entries := range map[string][]entry{
		"zip slip":         {{name: "../evil", data: "x"}},
		"zip slip nested":  {{name: "a/../../evil", data: "x"}},
		"absolute":         {{name: "/etc/passwd", data: "x"}},
		"dot part":         {{name: "a/./b", data: "x"}},
		"empty part":       {{name: "a//b", data: "x"}},
		"backslash":        {{name: "a\\..\\b", data: "x"}},
		"symlink":          {{name: "link", mode: fs.ModeSymlink | 0o777, data: "/etc/shadow"}},
		"device":           {{name: "dev", mode: fs.ModeDevice | 0o600}},
		"char device":      {{name: "tty", mode: fs.ModeDevice | fs.ModeCharDevice | 0o600}},
		"fifo":             {{name: "fifo", mode: fs.ModeNamedPipe | 0o600}},
		"socket":           {{name: "sock", mode: fs.ModeSocket | 0o600}},
		"duplicate":        {{name: "a", data: "1"}, {name: "a", data: "2"}},
		"file then dir":    {{name: "a", data: "1"}, {name: "a/b", data: "2"}},
		"dir then file":    {{name: "a/b", data: "1"}, {name: "a", data: "2"}},
		"long part":        {{name: strings.Repeat("x", 256), data: "1"}},
		"symlink in path?": {{name: "ok/", mode: fs.ModeDir | 0o755}, {name: "ok", mode: fs.ModeSymlink | 0o777, data: "/"}},
	} {
		t.Run(name, func(t *testing.T) {
			dst, _, err := extract(t, makeZip(t, entries...), DefaultLimits)
			if !errors.Is(err, ErrBundle) {
				t.Fatalf("got %v, want ErrBundle", err)
			}
			// Nothing was written outside dst, and no link exists in it.
			_ = filepath.WalkDir(dst, func(p string, d fs.DirEntry, _ error) error {
				if d != nil && d.Type()&fs.ModeSymlink != 0 {
					t.Errorf("link %s", p)
				}
				return nil
			})
			if _, err := os.Lstat(filepath.Join(filepath.Dir(dst), "evil")); err == nil {
				t.Error("wrote outside the stage")
			}
		})
	}
}

func TestExtractLimits(t *testing.T) {
	big := strings.Repeat("0", 1<<20) // compresses to almost nothing
	lim := Limits{MaxZipBytes: 1 << 30, MaxBytes: 512 << 10, MaxEntries: 10}
	if _, _, err := extract(t, makeZip(t, entry{name: "bomb", data: big}), lim); !errors.Is(err, ErrBundle) {
		t.Fatalf("bomb: %v", err)
	}
	if _, _, err := extract(t, makeZip(t, entry{name: "a", data: big[:300<<10]}, entry{name: "b", data: big[:300<<10]}), lim); !errors.Is(err, ErrBundle) {
		t.Fatalf("total over limit: %v", err)
	}
	var many []entry
	for i := range 11 {
		many = append(many, entry{name: "f" + strings.Repeat("x", i), data: "1"})
	}
	if _, _, err := extract(t, makeZip(t, many...), lim); !errors.Is(err, ErrBundle) {
		t.Fatalf("too many entries: %v", err)
	}
	// Implied parent directories count too.
	if _, _, err := extract(t, makeZip(t, entry{name: "a/b/c/d/e/f/g/h/i/j/k", data: "1"}), lim); !errors.Is(err, ErrBundle) {
		t.Fatalf("too many implied dirs: %v", err)
	}
	// Directory entries count, also with no file in the bundle.
	dirsOnly := makeZip(t, entry{name: "a/b/c/", mode: fs.ModeDir | 0o755})
	if _, _, err := extract(t, dirsOnly, Limits{MaxZipBytes: 1 << 30, MaxBytes: 1 << 20, MaxEntries: 2}); !errors.Is(err, ErrBundle) {
		t.Fatalf("directory-only bundle over the limit: %v", err)
	}
	if _, st, err := extract(t, dirsOnly, Limits{MaxZipBytes: 1 << 30, MaxBytes: 1 << 20, MaxEntries: 3}); err != nil || st.Dirs != 3 {
		t.Fatalf("directory-only bundle at the limit: %+v %v", st, err)
	}
}

var uuidRE = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func TestUUIDFor(t *testing.T) {
	a, b := UUIDFor(strings.Repeat("a", 64)), UUIDFor(strings.Repeat("b", 64))
	if !uuidRE.MatchString(a) || !uuidRE.MatchString(b) || a == b || UUIDFor(strings.Repeat("a", 64)) != a {
		t.Fatalf("%s %s", a, b)
	}
}

// fakeMkfs writes the tree listing into an image of the given size.
func fakeMkfs(calls *[]string) Mkfs {
	return func(_ context.Context, path, dir string, size int64, uuid string, inodes int) error {
		*calls = append(*calls, uuid)
		var list []string
		_ = filepath.WalkDir(dir, func(p string, _ fs.DirEntry, _ error) error {
			rel, _ := filepath.Rel(dir, p)
			list = append(list, rel)
			return nil
		})
		data := []byte(uuid + "\n" + strings.Join(list, "\n"))
		if int64(len(data)) > size || inodes < len(list) {
			return errors.New("no space")
		}
		f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if err != nil {
			return err
		}
		if _, err := f.Write(data); err != nil {
			return err
		}
		if err := f.Truncate(size); err != nil {
			return err
		}
		return f.Close()
	}
}

func sum(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

func TestStorePutGetGC(t *testing.T) {
	var calls []string
	now := time.Date(2026, 11, 9, 0, 0, 0, 0, time.UTC)
	s := &Store{Dir: t.TempDir(), Limits: DefaultLimits, Mkfs: fakeMkfs(&calls), Now: func() time.Time { now = now.Add(time.Minute); return now }}
	ctx := context.Background()
	z1 := makeZip(t, entry{name: "s/SKILL.md", data: "v1"})
	id1 := sum(z1)

	// Bad header: wrong hash, wrong size, bad ID.
	if _, _, err := s.Put(ctx, sum([]byte("x")), int64(len(z1)), bytes.NewReader(z1)); !errors.Is(err, ErrBundle) {
		t.Fatalf("hash mismatch: %v", err)
	}
	if _, _, err := s.Put(ctx, id1, int64(len(z1))+1, bytes.NewReader(z1)); !errors.Is(err, ErrBundle) {
		t.Fatalf("short body: %v", err)
	}
	if _, _, err := s.Put(ctx, "ABC", 1, bytes.NewReader(nil)); !errors.Is(err, ErrBundle) {
		t.Fatalf("bad id: %v", err)
	}
	notZip := []byte("not a zip at all")
	if _, _, err := s.Put(ctx, sum(notZip), int64(len(notZip)), bytes.NewReader(notZip)); !errors.Is(err, ErrBundle) {
		t.Fatalf("not a zip: %v", err)
	}
	if len(calls) != 0 {
		t.Fatalf("mkfs ran for a bad bundle")
	}

	img, built, err := s.Put(ctx, id1, int64(len(z1)), bytes.NewReader(z1))
	if err != nil || !built || img.ID != id1 || img.UUID != UUIDFor(id1) || img.Files != 1 || img.Size%(1<<20) != 0 {
		t.Fatalf("put: %+v %v %v", img, built, err)
	}
	if st, _ := os.Stat(img.Path); st.Mode().Perm() != 0o644 {
		t.Fatalf("image mode %v", st.Mode())
	}
	// Again: no build, and the body is not needed.
	img2, built, err := s.Put(ctx, id1, int64(len(z1)), bytes.NewReader(nil))
	if err != nil || built || img2.SHA256 != img.SHA256 || len(calls) != 1 {
		t.Fatalf("repeat put: %+v %v %v calls %d", img2, built, err, len(calls))
	}
	if left, _ := filepath.Glob(filepath.Join(s.Dir, ".*")); len(left) != 0 {
		t.Fatalf("left over: %v", left)
	}

	// A changed image is not valid.
	if err := os.WriteFile(img.Path, append([]byte("X"), make([]byte, img.Size-1)...), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Get(id1); !errors.Is(err, ErrMissing) {
		t.Fatalf("tampered image: %v", err)
	}
	if err := os.Remove(img.Path); err != nil {
		t.Fatal(err)
	}
	if _, built, err = s.Put(ctx, id1, int64(len(z1)), bytes.NewReader(z1)); err != nil || !built {
		t.Fatalf("rebuild: %v %v", built, err)
	}

	// GC: keep the 2 newest and the ones in use.
	var ids []string
	for i := range 3 {
		z := makeZip(t, entry{name: "s/SKILL.md", data: "v" + strings.Repeat("x", i+2)})
		if _, _, err := s.Put(ctx, sum(z), int64(len(z)), bytes.NewReader(z)); err != nil {
			t.Fatal(err)
		}
		ids = append(ids, sum(z))
	}
	removed, err := s.GC(2, func() map[string]bool { return map[string]bool{id1: true} })
	if err != nil || len(removed) != 1 || removed[0] != ids[0] {
		t.Fatalf("gc removed %v %v, want %s", removed, err, ids[0])
	}
	list, _ := s.List()
	if len(list) != 3 || list[0].ID != ids[2] || list[1].ID != ids[1] || list[2].ID != id1 {
		t.Fatalf("list %v", list)
	}
	if _, err := os.Stat(filepath.Join(s.Dir, ids[0]+".ext4")); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("GC left the image file: %v", err)
	}
}

func TestStoreGCKeepsPinnedAndBuildingImages(t *testing.T) {
	var calls []string
	now := time.Date(2026, 11, 9, 0, 0, 0, 0, time.UTC)
	s := &Store{Dir: t.TempDir(), Limits: DefaultLimits, Mkfs: fakeMkfs(&calls), Now: func() time.Time { now = now.Add(time.Minute); return now }}
	ctx := context.Background()
	var ids []string
	for i := range 2 {
		z := makeZip(t, entry{name: "s/SKILL.md", data: "v" + strings.Repeat("x", i+2)})
		if _, _, err := s.Put(ctx, sum(z), int64(len(z)), bytes.NewReader(z)); err != nil {
			t.Fatal(err)
		}
		ids = append(ids, sum(z))
	}
	none := func() map[string]bool { return nil }
	// A swap pins the older image: GC with keep 0 removes only the other.
	unpin := s.Pin(ids[0])
	removed, err := s.GC(0, none)
	if err != nil || len(removed) != 1 || removed[0] != ids[1] {
		t.Fatalf("gc with a pin removed %v %v, want %s", removed, err, ids[1])
	}
	unpin()
	unpin()
	// A Put of an ID runs (its lock is held): its files stay.
	building := strings.Repeat("c", 64)
	stray := filepath.Join(s.Dir, building+".ext4")
	if err := os.WriteFile(stray, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	unlock := s.lockID(building)
	removed, err = s.GC(0, none)
	if err != nil || len(removed) != 1 || removed[0] != ids[0] {
		t.Fatalf("gc after unpin removed %v %v, want %s", removed, err, ids[0])
	}
	if _, err := os.Stat(stray); err != nil {
		t.Fatalf("GC removed the file of a running Put: %v", err)
	}
	unlock()
	if _, err := s.GC(0, none); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(stray); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("GC left an unfinished image file: %v", err)
	}
}

type signalReader struct {
	r    *bytes.Reader
	read chan struct{}
	once sync.Once
}

func (r *signalReader) Read(p []byte) (int, error) {
	r.once.Do(func() { close(r.read) })
	return r.r.Read(p)
}

// Uploads of different bundles share one node-wide slot: the second does
// not read its data while the first builds.
func TestStorePutSharesNodeLimit(t *testing.T) {
	var calls []string
	mkfs := fakeMkfs(&calls)
	inMkfs, finish := make(chan struct{}), make(chan struct{})
	var once sync.Once
	s := &Store{Dir: t.TempDir(), Limits: DefaultLimits, Mkfs: func(ctx context.Context, path, dir string, size int64, uuid string, inodes int) error {
		once.Do(func() { close(inMkfs); <-finish })
		return mkfs(ctx, path, dir, size, uuid, inodes)
	}}
	z1 := makeZip(t, entry{name: "a", data: "1"})
	z2 := makeZip(t, entry{name: "b", data: "2"})
	first := make(chan error, 1)
	go func() {
		_, _, err := s.Put(context.Background(), sum(z1), int64(len(z1)), bytes.NewReader(z1))
		first <- err
	}()
	<-inMkfs
	r2 := &signalReader{r: bytes.NewReader(z2), read: make(chan struct{})}
	second := make(chan error, 1)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() {
		_, _, err := s.Put(ctx, sum(z2), int64(len(z2)), r2)
		second <- err
	}()
	select {
	case <-r2.read:
		t.Fatal("the second upload read its data while the first one built")
	case <-time.After(100 * time.Millisecond):
	}
	close(finish)
	if err := <-first; err != nil {
		t.Fatal(err)
	}
	if err := <-second; err != nil {
		t.Fatal(err)
	}
	// A waiting upload ends with its context.
	release, err := s.acquire(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	cctx, ccancel := context.WithCancel(context.Background())
	ccancel()
	z3 := makeZip(t, entry{name: "c", data: "3"})
	if _, _, err := s.Put(cctx, sum(z3), int64(len(z3)), bytes.NewReader(z3)); !errors.Is(err, context.Canceled) {
		t.Fatalf("waiting upload with a cancelled context: %v", err)
	}
}

func TestStoreRetriesMkfsWithMoreSpace(t *testing.T) {
	var sizes []int64
	s := &Store{Dir: t.TempDir(), Limits: DefaultLimits, Mkfs: func(_ context.Context, path, _ string, size int64, _ string, _ int) error {
		sizes = append(sizes, size)
		if len(sizes) < 3 {
			return errors.New("No space left on device")
		}
		return os.WriteFile(path, make([]byte, size), 0o600)
	}}
	z := makeZip(t, entry{name: "a", data: "1"})
	img, _, err := s.Put(context.Background(), sum(z), int64(len(z)), bytes.NewReader(z))
	if err != nil || len(sizes) != 3 || sizes[1] != 2*sizes[0] || img.Size != sizes[2] {
		t.Fatalf("%v sizes %v img %+v", err, sizes, img)
	}
}

func TestCleanStaging(t *testing.T) {
	dir := t.TempDir()
	for _, n := range []string{".upload-1.zip", ".build-x.ext4", ".stage-1/a", strings.Repeat("a", 64) + ".json.tmp"} {
		p := filepath.Join(dir, n)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	keep := filepath.Join(dir, strings.Repeat("b", 64)+".ext4")
	if err := os.WriteFile(keep, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	var unmounted []string
	if err := (&Store{Dir: dir}).CleanStaging(func(p string) error { unmounted = append(unmounted, filepath.Base(p)); return nil }); err != nil {
		t.Fatal(err)
	}
	ents, _ := os.ReadDir(dir)
	if len(ents) != 1 || ents[0].Name() != filepath.Base(keep) || len(unmounted) != 1 || unmounted[0] != ".stage-1" {
		t.Fatalf("left %v, unmounted %v", ents, unmounted)
	}
}

// With e2fsprogs (Linux CI, the agent image), the real mkfs makes an image
// whose UUID and content debugfs can read.
func TestMkfsExt4Real(t *testing.T) {
	if _, err := exec.LookPath("mkfs.ext4"); err != nil {
		t.Skip("no mkfs.ext4")
	}
	if _, err := exec.LookPath("debugfs"); err != nil {
		t.Skip("no debugfs")
	}
	s := &Store{Dir: t.TempDir(), Limits: DefaultLimits}
	z := makeZip(t, entry{name: "skills/pdf/SKILL.md", data: "# pdf skill"}, entry{name: "skills/run.sh", mode: 0o755, data: "#!/bin/sh\n"})
	img, _, err := s.Put(context.Background(), sum(z), int64(len(z)), bytes.NewReader(z))
	if err != nil {
		t.Fatal(err)
	}
	out, err := exec.Command("debugfs", "-R", "cat /skills/pdf/SKILL.md", img.Path).Output()
	if err != nil || string(out) != "# pdf skill" {
		t.Fatalf("debugfs cat: %q %v", out, err)
	}
	out, err = exec.Command("debugfs", "-R", "stats", img.Path).Output()
	if err != nil || !strings.Contains(string(out), img.UUID) || strings.Contains(string(out), "has_journal") {
		t.Fatalf("debugfs stats: %v\n%s", err, out)
	}
}

func TestStoreRemoveUnused(t *testing.T) {
	var calls []string
	s := &Store{Dir: t.TempDir(), Limits: DefaultLimits, Mkfs: fakeMkfs(&calls)}
	z := makeZip(t, entry{name: "s/SKILL.md", data: "v1"})
	id := sum(z)
	if _, _, err := s.Put(context.Background(), id, int64(len(z)), bytes.NewReader(z)); err != nil {
		t.Fatal(err)
	}
	none := func() map[string]bool { return nil }

	if ok, err := s.RemoveUnused(id, func() map[string]bool { return map[string]bool{id: true} }); ok || err != nil {
		t.Fatalf("removed an image in use: %v %v", ok, err)
	}
	unpin := s.Pin(id)
	if ok, err := s.RemoveUnused(id, none); ok || err != nil {
		t.Fatalf("removed a pinned image: %v %v", ok, err)
	}
	unpin()
	unlock, _ := s.tryLockID(id)
	if ok, _ := s.RemoveUnused(id, none); ok {
		t.Fatal("removed an image during its Put")
	}
	unlock()
	if ok, err := s.RemoveUnused(id, none); !ok || err != nil || s.Has(id) {
		t.Fatalf("RemoveUnused = %v %v, has %v", ok, err, s.Has(id))
	}
	if ok, err := s.RemoveUnused(id, none); ok || err != nil {
		t.Fatalf("second remove = %v %v", ok, err)
	}
	if _, err := s.RemoveUnused("../x", none); err == nil {
		t.Fatal("accepted a bad id")
	}
}
