package files

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/klauspost/compress/zstd"
)

const sid = "6f1c5c1e-2d3b-4c4d-9e5f-0a1b2c3d4e5f"

func newStore(t *testing.T, cfg Config) (*Store, string) {
	t.Helper()
	dir := t.TempDir()
	// macOS TempDir is under a /var -> /private/var link.
	dir, err := filepath.EvalSymlinks(dir)
	if err != nil {
		t.Fatal(err)
	}
	cfg.SessionsRoot = filepath.Join(dir, "sessions")
	if cfg.CaptureRoots == nil {
		// Two roots, to test the swap and rollback of more than one.
		cfg.CaptureRoots = []string{"work", "attachments"}
	}
	s, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(cfg.SessionsRoot, sid), 0o755); err != nil {
		t.Fatal(err)
	}
	return s, filepath.Join(cfg.SessionsRoot, sid)
}

func put(t *testing.T, base, rel, data string) {
	t.Helper()
	p := filepath.Join(base, rel)
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(data), 0o644); err != nil {
		t.Fatal(err)
	}
}

func sum(b []byte) string {
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

func read(t *testing.T, s *Store, p string, off, n int64) ([]byte, Info, error) {
	t.Helper()
	var buf bytes.Buffer
	var info Info
	err := s.Read(context.Background(), sid, p, off, n,
		func(i Info) error { info = i; return nil },
		func(b []byte) error { buf.Write(b); return nil })
	return buf.Bytes(), info, err
}

func TestReadBoundsAndRanges(t *testing.T) {
	s, base := newStore(t, Config{MaxFileBytes: 10})
	put(t, base, "work/a.txt", "0123456789")
	put(t, base, "work/big.txt", "0123456789X")

	got, info, err := read(t, s, "work/a.txt", 0, 0)
	if err != nil || string(got) != "0123456789" || info.Size != 10 || info.Path != "work/a.txt" {
		t.Fatalf("read = %q %+v %v", got, info, err)
	}
	got, _, err = read(t, s, "/work/a.txt", 3, 4)
	if err != nil || string(got) != "3456" {
		t.Fatalf("range = %q %v", got, err)
	}
	if _, _, err := read(t, s, "work/big.txt", 0, 0); !errors.Is(err, ErrLimit) {
		t.Fatalf("over the limit: %v", err)
	}
	// A range of a big file is fine.
	if got, _, err := read(t, s, "work/big.txt", 5, 6); err != nil || string(got) != "56789X" {
		t.Fatalf("range of big = %q %v", got, err)
	}
	if _, _, err := read(t, s, "work", 0, 0); !errors.Is(err, ErrInvalid) {
		t.Fatalf("directory: %v", err)
	}
	if _, _, err := read(t, s, "work/missing", 0, 0); !errors.Is(err, ErrNotFound) {
		t.Fatalf("missing: %v", err)
	}
	if _, _, err := read(t, s, "work/a.txt", 11, 0); !errors.Is(err, ErrInvalid) {
		t.Fatalf("offset past end: %v", err)
	}
}

func TestPathEscapes(t *testing.T) {
	s, base := newStore(t, Config{})
	outside := filepath.Join(filepath.Dir(filepath.Dir(base)), "secret")
	put(t, filepath.Dir(outside), "secret", "top secret")
	if err := os.MkdirAll(filepath.Join(base, "work"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(base, "work", "link")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Dir(outside), filepath.Join(base, "work", "dirlink")); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{"../secret", "work/../../secret", "work/link", "work/dirlink/secret"} {
		if _, _, err := read(t, s, p, 0, 0); err == nil {
			t.Errorf("read %q: no error", p)
		}
	}
	ctx := context.Background()
	// Write through a link that leaves the session fails.
	_, _, err := s.Write(ctx, sid, WriteSpec{Path: "work/dirlink/new", Size: 1}, strings.NewReader("x"))
	if err == nil {
		t.Fatal("write through an escaping link worked")
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(outside), "new")); err == nil {
		t.Fatal("file written outside the session")
	}
	// Delete of the link removes the link, not the target.
	if ok, err := s.Delete(sid, "work/link", false); !ok || err != nil {
		t.Fatalf("delete link = %v %v", ok, err)
	}
	if _, err := os.Stat(outside); err != nil {
		t.Fatal("link target was removed")
	}
	if _, _, err := s.List(ctx, sid, ListSpec{Path: "work/dirlink"}); err == nil {
		t.Fatal("list through an escaping link worked")
	}
	for _, bad := range []string{"", "..", ".hidden", "a/b"} {
		if _, _, err := s.List(ctx, bad, ListSpec{}); !errors.Is(err, ErrInvalid) {
			t.Errorf("session id %q: %v", bad, err)
		}
	}
}

func TestReadLinkRoots(t *testing.T) {
	dir := t.TempDir()
	dir, _ = filepath.EvalSymlinks(dir)
	managed := filepath.Join(dir, "managed")
	put(t, managed, "user_library/doc.md", "library")
	s, base := newStore(t, Config{ReadLinkRoots: []string{managed}})
	if err := os.Symlink(filepath.Join(managed, "user_library"), filepath.Join(base, "user_library")); err != nil {
		t.Fatal(err)
	}
	got, info, err := read(t, s, "user_library/doc.md", 0, 0)
	if err != nil || string(got) != "library" || info.Path != "user_library/doc.md" {
		t.Fatalf("read via link root = %q %+v %v", got, info, err)
	}
	ents, _, err := s.List(context.Background(), sid, ListSpec{Path: "user_library"})
	if err != nil || len(ents) != 1 || ents[0].Path != "user_library/doc.md" {
		t.Fatalf("list via link root = %+v %v", ents, err)
	}
	// Writes never follow it.
	if _, _, err := s.Write(context.Background(), sid, WriteSpec{Path: "user_library/x", Size: 1}, strings.NewReader("x")); err == nil {
		t.Fatal("write through the read link worked")
	}
	// A link to a directory outside the allowed roots is not followed.
	s2, base2 := newStore(t, Config{ReadLinkRoots: []string{filepath.Join(dir, "other")}})
	if err := os.Symlink(filepath.Join(managed, "user_library"), filepath.Join(base2, "user_library")); err != nil {
		t.Fatal(err)
	}
	if _, _, err := read(t, s2, "user_library/doc.md", 0, 0); err == nil {
		t.Fatal("followed a link outside the read link roots")
	}
}

func TestWrite(t *testing.T) {
	s, base := newStore(t, Config{MaxFileBytes: 100})
	ctx := context.Background()
	data := "hello"
	info, got, err := s.Write(ctx, sid, WriteSpec{Path: "work/x/a.txt", Size: 5, SHA256: sum([]byte(data)), MakeParents: true, Mode: 0o4755},
		strings.NewReader(data))
	if err != nil || got != sum([]byte(data)) || info.Size != 5 || info.Mode != 0o755 {
		t.Fatalf("write = %+v %s %v", info, got, err)
	}
	if b, _ := os.ReadFile(filepath.Join(base, "work/x/a.txt")); string(b) != data {
		t.Fatalf("content %q", b)
	}
	// Without overwrite an existing file stays.
	if _, _, err := s.Write(ctx, sid, WriteSpec{Path: "work/x/a.txt", Size: 3}, strings.NewReader("new")); !errors.Is(err, ErrExists) {
		t.Fatalf("no overwrite: %v", err)
	}
	if _, _, err := s.Write(ctx, sid, WriteSpec{Path: "work/x/a.txt", Size: 3, Overwrite: true}, strings.NewReader("new")); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(filepath.Join(base, "work/x/a.txt")); string(b) != "new" {
		t.Fatalf("content after overwrite %q", b)
	}
	// Short data, long data, a wrong hash and an over-limit size change nothing.
	cases := []struct {
		spec WriteSpec
		data string
		want error
	}{
		{WriteSpec{Path: "work/x/a.txt", Size: 10, Overwrite: true}, "short", ErrInvalid},
		{WriteSpec{Path: "work/x/a.txt", Size: 2, Overwrite: true}, "toolong", ErrInvalid},
		{WriteSpec{Path: "work/x/a.txt", Size: 3, Overwrite: true, SHA256: sum([]byte("abc"))}, "xyz", ErrInvalid},
		{WriteSpec{Path: "work/x/a.txt", Size: 101, Overwrite: true}, strings.Repeat("a", 101), ErrLimit},
		{WriteSpec{Path: "work/missing/a.txt", Size: 1}, "a", ErrNotFound},
		{WriteSpec{Path: "work/x", Size: 1, Overwrite: true}, "a", ErrInvalid},
	}
	for i, c := range cases {
		if _, _, err := s.Write(ctx, sid, c.spec, strings.NewReader(c.data)); !errors.Is(err, c.want) {
			t.Errorf("case %d: %v, want %v", i, err, c.want)
		}
	}
	if b, _ := os.ReadFile(filepath.Join(base, "work/x/a.txt")); string(b) != "new" {
		t.Fatalf("content changed by a failed write: %q", b)
	}
	ents, _ := os.ReadDir(filepath.Join(base, "work/x"))
	if len(ents) != 1 {
		t.Fatalf("temp files left: %v", ents)
	}
}

func TestUploadNames(t *testing.T) {
	s, base := newStore(t, Config{})
	ctx := context.Background()
	var paths []string
	for _, name := range []string{"report.pdf", "report.pdf", "report.pdf", "../evil\n.txt", "noext", "noext"} {
		info, _, err := s.Upload(ctx, sid, UploadSpec{FileName: name, Size: 1}, strings.NewReader("x"))
		if err != nil {
			t.Fatalf("upload %q: %v", name, err)
		}
		paths = append(paths, info.Path)
	}
	want := []string{"attachments/report.pdf", "attachments/report_1.pdf", "attachments/report_2.pdf",
		"attachments/.._evil_.txt", "attachments/noext", "attachments/noext_1"}
	if strings.Join(paths, ",") != strings.Join(want, ",") {
		t.Fatalf("paths = %v, want %v", paths, want)
	}
	for _, bad := range []string{"", "..", "  "} {
		if _, _, err := s.Upload(ctx, sid, UploadSpec{FileName: bad, Size: 0}, strings.NewReader("")); !errors.Is(err, ErrInvalid) {
			t.Errorf("name %q: %v", bad, err)
		}
	}
	ents, _ := os.ReadDir(filepath.Join(base, "attachments"))
	for _, e := range ents {
		if strings.HasPrefix(e.Name(), writePrefix) {
			t.Fatalf("temp file left: %s", e.Name())
		}
	}
}

func TestListAndDelete(t *testing.T) {
	s, base := newStore(t, Config{})
	ctx := context.Background()
	put(t, base, "work/b.txt", "b")
	put(t, base, "work/A.txt", "a")
	put(t, base, "work/sub/c.txt", "c")
	put(t, base, "work/node_modules/x/y.js", "y")
	put(t, base, "work/.hidden", "h")
	if err := os.Symlink("b.txt", filepath.Join(base, "work", "ln")); err != nil {
		t.Fatal(err)
	}
	ents, trunc, err := s.List(ctx, sid, ListSpec{Path: "work"})
	if err != nil || trunc {
		t.Fatal(err, trunc)
	}
	var names []string
	for _, e := range ents {
		names = append(names, e.Name)
	}
	if strings.Join(names, ",") != "node_modules,sub,.hidden,A.txt,b.txt,ln" {
		t.Fatalf("order = %v", names)
	}
	if ents[5].Type != TypeSymlink || ents[5].LinkTarget != "b.txt" {
		t.Fatalf("link entry %+v", ents[5])
	}
	ents, _, err = s.List(ctx, sid, ListSpec{Path: "work", Recursive: true, Exclude: []string{"node_modules"}, SkipHidden: true})
	if err != nil {
		t.Fatal(err)
	}
	var paths []string
	for _, e := range ents {
		paths = append(paths, e.Path)
	}
	if strings.Join(paths, ",") != "work/sub,work/A.txt,work/b.txt,work/ln,work/sub/c.txt" {
		t.Fatalf("recursive = %v", paths)
	}
	_, trunc, _ = s.List(ctx, sid, ListSpec{Path: "work", MaxEntries: 2})
	if !trunc {
		t.Fatal("not truncated at max_entries")
	}
	if _, _, err := s.List(ctx, sid, ListSpec{Path: "work/b.txt"}); !errors.Is(err, ErrInvalid) {
		t.Fatalf("list a file: %v", err)
	}
	if _, _, err := s.List(ctx, sid, ListSpec{Path: "nope"}); !errors.Is(err, ErrNotFound) {
		t.Fatalf("list missing: %v", err)
	}
	if _, err := s.Delete(sid, "work/sub", false); !errors.Is(err, ErrInvalid) {
		t.Fatalf("delete dir without recursive: %v", err)
	}
	if ok, err := s.Delete(sid, "work/sub", true); !ok || err != nil {
		t.Fatal(ok, err)
	}
	if ok, err := s.Delete(sid, "work/sub", true); ok || err != nil {
		t.Fatalf("second delete = %v %v", ok, err)
	}
	if _, err := s.Delete(sid, "", true); !errors.Is(err, ErrInvalid) {
		t.Fatalf("delete the session: %v", err)
	}
}

func TestListLargeDirectory(t *testing.T) {
	s, base := newStore(t, Config{})
	for _, n := range []string{"e", "d", "c", "b", "a"} {
		put(t, base, "work/"+n+".txt", n)
	}
	orig := listScanCap
	t.Cleanup(func() { listScanCap = orig })
	listScanCap = 3
	ents, trunc, err := s.List(context.Background(), sid, ListSpec{Path: "work", MaxEntries: 10})
	if err != nil || !trunc {
		t.Fatalf("err %v truncated %v", err, trunc)
	}
	if len(ents) != 3 {
		t.Fatalf("got %d entries, want the 3 scanned", len(ents))
	}
}

func TestReadDirFIFO(t *testing.T) {
	_, base := newStore(t, Config{})
	put(t, base, "work/a.txt", "a")
	if err := syscall.Mkfifo(filepath.Join(base, "work", "pipe"), 0o600); err != nil {
		t.Fatal(err)
	}
	root, err := os.OpenRoot(base)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = root.Close() })
	done := make(chan error, 1)
	go func() {
		_, err := readDir(root, "work/pipe", 10)
		done <- err
	}()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("readDir of a FIFO did not fail")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("readDir blocked on a FIFO")
	}
}

func TestZip(t *testing.T) {
	s, base := newStore(t, Config{MaxZipBytes: 20})
	ctx := context.Background()
	put(t, base, "work/web/a.txt", "aaaa")
	put(t, base, "work/web/src/b.txt", "bbbb")
	put(t, base, "work/web/node_modules/c.txt", "cccc")
	if err := os.Symlink("/etc/passwd", filepath.Join(base, "work/web/pw")); err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	zs, err := s.Zip(ctx, sid, ZipSpec{Path: "work/web", Exclude: []string{"node_modules"}}, &buf)
	if err != nil {
		t.Fatal(err)
	}
	if zs.Files != 2 || zs.InputBytes != 8 || zs.Skipped != 1 || zs.ZipBytes != int64(buf.Len()) {
		t.Fatalf("summary %+v", zs)
	}
	zr, err := zip.NewReader(bytes.NewReader(buf.Bytes()), int64(buf.Len()))
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, f := range zr.File {
		names = append(names, f.Name)
	}
	sort.Strings(names)
	if strings.Join(names, ",") != "a.txt,src/b.txt" {
		t.Fatalf("zip names %v", names)
	}
	put(t, base, "work/web/big.txt", strings.Repeat("z", 20))
	buf.Reset()
	if _, err := s.Zip(ctx, sid, ZipSpec{Path: "work/web"}, &buf); !errors.Is(err, ErrLimit) || buf.Len() != 0 {
		t.Fatalf("zip over the limit: %v, %d bytes written", err, buf.Len())
	}
}

func buildSession(t *testing.T, base string) {
	t.Helper()
	put(t, base, "work/report.md", "# report")
	put(t, base, "work/web/package.json", "{}")
	put(t, base, "work/web/node_modules/react/index.js", "dep")
	put(t, base, "work/web/.next/cache/x", "build")
	put(t, base, "work/data/__pycache__/m.pyc", "pyc")
	put(t, base, "work/myenv/pyvenv.cfg", "home = /usr")
	put(t, base, "work/myenv/lib/site.py", "venv")
	put(t, base, "attachments/in.pdf", "pdf")
	put(t, base, "AGENTS.md", "not saved")
	if err := os.Symlink("/etc/passwd", filepath.Join(base, "work", "pw")); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(filepath.Join(base, "work/report.md"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func capture(t *testing.T, s *Store, spec CaptureSpec) ([]byte, CaptureSummary) {
	t.Helper()
	var buf bytes.Buffer
	cs, err := s.Capture(context.Background(), spec, &buf)
	if err != nil {
		t.Fatal(err)
	}
	if cs.StoredBytes != int64(buf.Len()) || cs.SHA256 != sum(buf.Bytes()) {
		t.Fatalf("summary size/hash do not match the stream: %+v", cs)
	}
	return buf.Bytes(), cs
}

func tarNames(t *testing.T, archive []byte) []string {
	t.Helper()
	zr, err := zstd.NewReader(bytes.NewReader(archive))
	if err != nil {
		t.Fatal(err)
	}
	defer zr.Close()
	tr := tar.NewReader(zr)
	var names []string
	for {
		h, err := tr.Next()
		if errors.Is(err, io.EOF) {
			return names
		}
		if err != nil {
			t.Fatal(err)
		}
		names = append(names, h.Name)
	}
}

func TestCaptureExcludes(t *testing.T) {
	s, base := newStore(t, Config{})
	buildSession(t, base)
	archive, cs := capture(t, s, CaptureSpec{SessionID: sid})
	names := tarNames(t, archive)
	want := []string{"work/", "work/data/", "work/web/", "work/web/package.json", "work/report.md",
		"attachments/", "attachments/in.pdf"}
	if strings.Join(names, ",") != strings.Join(want, ",") {
		t.Fatalf("archive = %v\nwant %v", names, want)
	}
	// node_modules, .next, __pycache__, the venv; the symlink.
	if cs.Files != 3 || cs.Excluded != 4 || cs.Skipped != 1 || strings.Join(cs.Roots, ",") != "work,attachments" {
		t.Fatalf("summary %+v", cs)
	}
	// A request exclude list replaces the default one.
	archive, _ = capture(t, s, CaptureSpec{SessionID: sid, Roots: []string{"work"}, Exclude: []string{"web"}})
	for _, n := range tarNames(t, archive) {
		if strings.HasPrefix(n, "work/web") || strings.HasPrefix(n, "attachments") || strings.Contains(n, "myenv/lib") {
			t.Fatalf("unexpected member %s", n)
		}
	}
	if _, err := s.Capture(context.Background(), CaptureSpec{SessionID: sid, Roots: []string{"../x"}}, io.Discard); !errors.Is(err, ErrInvalid) {
		t.Fatalf("bad root: %v", err)
	}
}

func TestDefaultCaptureRoots(t *testing.T) {
	sessions := filepath.Join(t.TempDir(), "sessions")
	s, err := New(Config{SessionsRoot: sessions})
	if err != nil {
		t.Fatal(err)
	}
	base := filepath.Join(sessions, sid)
	put(t, base, "attachments/in.pdf", "pdf")
	put(t, base, "outputs/report.md", "not saved")
	archive, cs := capture(t, s, CaptureSpec{SessionID: sid})
	if got := strings.Join(tarNames(t, archive), ","); got != "attachments/,attachments/in.pdf" {
		t.Fatalf("archive = %s", got)
	}
	if strings.Join(cs.Roots, ",") != "attachments" {
		t.Fatalf("roots %v", cs.Roots)
	}
}

func TestCaptureLimits(t *testing.T) {
	s, base := newStore(t, Config{Limits: Limits{StoredBytes: 1 << 20, ExpandedBytes: 1000, Entries: 10}})
	put(t, base, "work/a", strings.Repeat("a", 600))
	put(t, base, "work/b", strings.Repeat("b", 600))
	ctx := context.Background()
	if _, err := s.Capture(ctx, CaptureSpec{SessionID: sid}, io.Discard); !errors.Is(err, ErrLimit) {
		t.Fatalf("expanded limit: %v", err)
	}
	if _, err := s.Capture(ctx, CaptureSpec{SessionID: sid, Limits: Limits{ExpandedBytes: 2000}}, io.Discard); !errors.Is(err, ErrInvalid) {
		t.Fatalf("raise over the daemon limit: %v", err)
	}
	if err := os.Remove(filepath.Join(base, "work/b")); err != nil {
		t.Fatal(err)
	}
	for i := range 12 {
		put(t, base, "work/d/"+string(rune('a'+i)), "")
	}
	if _, err := s.Capture(ctx, CaptureSpec{SessionID: sid}, io.Discard); !errors.Is(err, ErrLimit) {
		t.Fatalf("entry limit: %v", err)
	}
	if err := os.RemoveAll(filepath.Join(base, "work/d")); err != nil {
		t.Fatal(err)
	}
	// Random data does not compress: the stored limit stops it.
	rnd := make([]byte, 900)
	for i := range rnd {
		rnd[i] = byte(i*7919 + i*i)
	}
	put(t, base, "work/a", string(rnd))
	if _, err := s.Capture(ctx, CaptureSpec{SessionID: sid, Limits: Limits{StoredBytes: 100}}, io.Discard); !errors.Is(err, ErrLimit) {
		t.Fatalf("stored limit: %v", err)
	}
	if _, err := s.Capture(ctx, CaptureSpec{SessionID: "missing"}, io.Discard); !errors.Is(err, ErrNotFound) {
		t.Fatalf("missing session: %v", err)
	}
}

func restore(s *Store, id string, archive []byte, spec RestoreSpec) (RestoreSummary, error) {
	spec.SessionID = id
	if spec.Size == 0 {
		spec.Size = int64(len(archive))
	}
	if spec.SHA256 == "" {
		spec.SHA256 = sum(archive)
	}
	return s.Restore(context.Background(), spec, bytes.NewReader(archive))
}

func TestCaptureRestoreRoundTrip(t *testing.T) {
	s, base := newStore(t, Config{})
	buildSession(t, base)
	archive, cs := capture(t, s, CaptureSpec{SessionID: sid})

	other := "a6f1b1a2-0000-4000-8000-000000000001"
	// An old file in the target root is replaced; other files stay.
	put(t, filepath.Join(filepath.Dir(base), other), "work/stale.txt", "old")
	put(t, filepath.Join(filepath.Dir(base), other), "keep.txt", "keep")
	rs, err := restore(s, other, archive, RestoreSpec{})
	if err != nil {
		t.Fatal(err)
	}
	if rs.Files != cs.Files || rs.ExpandedBytes != cs.ExpandedBytes || strings.Join(rs.Roots, ",") != "work,attachments" {
		t.Fatalf("restore %+v vs capture %+v", rs, cs)
	}
	ob := filepath.Join(filepath.Dir(base), other)
	if b, _ := os.ReadFile(filepath.Join(ob, "work/report.md")); string(b) != "# report" {
		t.Fatalf("report = %q", b)
	}
	if fi, _ := os.Stat(filepath.Join(ob, "work/report.md")); fi.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", fi.Mode())
	}
	for _, gone := range []string{"work/stale.txt", "work/web/node_modules", "work/pw"} {
		if _, err := os.Lstat(filepath.Join(ob, gone)); err == nil {
			t.Errorf("%s exists after restore", gone)
		}
	}
	if _, err := os.Stat(filepath.Join(ob, "keep.txt")); err != nil {
		t.Fatal("a file outside the capture roots was removed")
	}
	ents, _ := os.ReadDir(ob)
	for _, e := range ents {
		if strings.HasPrefix(e.Name(), ".craft-") {
			t.Fatalf("leftover %s", e.Name())
		}
	}
	// A second capture of the restored session is the same archive content.
	again, _ := capture(t, s, CaptureSpec{SessionID: other})
	if strings.Join(tarNames(t, again), ",") != strings.Join(tarNames(t, archive), ",") {
		t.Fatal("capture after restore differs")
	}
}

func TestCaptureRestoreFileRoots(t *testing.T) {
	s, base := newStore(t, Config{})
	put(t, base, "work/a.txt", "a")
	put(t, base, "report.py", "print(1)")
	put(t, base, "notes.md", "n")
	if err := os.Chmod(filepath.Join(base, "report.py"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("/etc/passwd", filepath.Join(base, "pw")); err != nil {
		t.Fatal(err)
	}
	put(t, base, TopFilesRoot+"/x.txt", "a session directory with the reserved name")
	roots := []string{"work", "report.py", "notes.md", "pw", "missing.txt", TopFilesRoot}
	archive, cs := capture(t, s, CaptureSpec{SessionID: sid, Roots: roots})
	want := "work/,work/a.txt,.onyx-top-level/,.onyx-top-level/report.py,.onyx-top-level/notes.md"
	if got := strings.Join(tarNames(t, archive), ","); got != want {
		t.Fatalf("archive = %s", got)
	}
	if strings.Join(cs.Roots, ",") != "work,"+TopFilesRoot || cs.Files != 3 || cs.Skipped != 2 {
		t.Fatalf("summary %+v", cs)
	}

	// A daemon without TopFilesRoot restores it as a directory root.
	if got := strings.Join(oldRestoreFiles(t, archive, cs.Roots), ","); got != "work/a.txt,.onyx-top-level/report.py,.onyx-top-level/notes.md" {
		t.Fatalf("old restore = %s", got)
	}

	// A top-level file replaces an old file or directory of the same name.
	other := "a6f1b1a2-0000-4000-8000-000000000009"
	ob := filepath.Join(filepath.Dir(base), other)
	put(t, ob, "report.py/old.txt", "old dir")
	put(t, ob, "notes.md", "old")
	put(t, ob, "keep.txt", "keep")
	rs, err := restore(s, other, archive, RestoreSpec{Roots: cs.Roots})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(rs.Roots, ",") != "work,"+TopFilesRoot || rs.Files != 3 {
		t.Fatalf("restore %+v", rs)
	}
	fi, err := os.Lstat(filepath.Join(ob, "report.py"))
	if err != nil || !fi.Mode().IsRegular() || fi.Mode().Perm() != 0o700 {
		t.Fatalf("report.py %v %v", fi, err)
	}
	for rel, data := range map[string]string{"report.py": "print(1)", "notes.md": "n", "keep.txt": "keep", "work/a.txt": "a"} {
		if b, _ := os.ReadFile(filepath.Join(ob, rel)); string(b) != data {
			t.Fatalf("%s = %q", rel, b)
		}
	}
	ents, _ := os.ReadDir(ob)
	var names []string
	for _, e := range ents {
		names = append(names, e.Name())
	}
	if got := strings.Join(names, ","); got != "keep.txt,notes.md,report.py,work" {
		t.Fatalf("session = %s", got)
	}
	// TopFilesRoot must be in the request's roots.
	if _, err := restore(s, other, archive, RestoreSpec{Roots: []string{"work"}}); !errors.Is(err, ErrArchive) {
		t.Fatalf("top files not requested: %v", err)
	}
}

// oldRestoreFiles applies the member rules of a daemon before TopFilesRoot
// (each member under a requested root, a single-part member is a directory,
// only directories and regular files) and returns the files it would write.
func oldRestoreFiles(t *testing.T, archive []byte, roots []string) []string {
	t.Helper()
	allowed := setOf(roots)
	zr, err := zstd.NewReader(bytes.NewReader(archive))
	if err != nil {
		t.Fatal(err)
	}
	defer zr.Close()
	tr := tar.NewReader(zr)
	var files []string
	for {
		h, err := tr.Next()
		if errors.Is(err, io.EOF) {
			return files
		}
		if err != nil {
			t.Fatal(err)
		}
		n := strings.TrimSuffix(h.Name, "/")
		parts := strings.Split(n, "/")
		if !allowed[parts[0]] {
			t.Fatalf("old daemon: %q is not under a capture root", h.Name)
		}
		if len(parts) == 1 && h.Typeflag != tar.TypeDir {
			t.Fatalf("old daemon: a capture root must be a directory: %q", h.Name)
		}
		switch h.Typeflag {
		case tar.TypeDir:
		case tar.TypeReg:
			files = append(files, n)
		default:
			t.Fatalf("old daemon: type %q", h.Typeflag)
		}
	}
}

func TestRestoreTopFilesRules(t *testing.T) {
	s, base := newStore(t, Config{CaptureRoots: []string{"work", TopFilesRoot}})
	dir := func(n string) member { return member{h: tar.Header{Typeflag: tar.TypeDir, Name: n}} }
	reg := func(n, d string) member { return member{h: tar.Header{Typeflag: tar.TypeReg, Name: n}, data: d} }
	top := TopFilesRoot + "/"
	cases := map[string][]member{
		"file root":        {reg("work", "x")},
		"top files a file": {reg(TopFilesRoot, "x")},
		"nested":           {dir(top), dir(top + "d/"), reg(top+"d/a", "x")},
		"dir in top":       {dir(top), dir(top + "d/")},
		"reserved name":    {dir(top), reg(top+TopFilesRoot, "x")},
		"craft name":       {dir(top), reg(top+".craft-old-1", "x")},
		"also a root":      {dir("work/"), reg("work/a", "x"), dir(top), reg(top+"work", "x")},
	}
	other := "a6f1b1a2-0000-4000-8000-00000000000a"
	for name, ms := range cases {
		if _, err := restore(s, other, makeArchive(t, ms), RestoreSpec{}); !errors.Is(err, ErrArchive) {
			t.Errorf("%s: %v, want ErrArchive", name, err)
		}
	}
	ents, _ := os.ReadDir(filepath.Join(filepath.Dir(base), other))
	if len(ents) != 0 {
		t.Fatalf("failed restores left %v", ents)
	}
	// A read-only TopFilesRoot mode does not stop the move of its files.
	ok := makeArchive(t, []member{{h: tar.Header{Typeflag: tar.TypeDir, Name: top, Mode: 0o500}}, reg(top+"a", "x")})
	if _, err := restore(s, other, ok, RestoreSpec{}); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(filepath.Join(filepath.Dir(base), other, "a")); string(b) != "x" {
		t.Fatalf("a = %q", b)
	}
}

func TestRestoreRejectsMismatch(t *testing.T) {
	s, base := newStore(t, Config{})
	buildSession(t, base)
	archive, _ := capture(t, s, CaptureSpec{SessionID: sid})
	other := "a6f1b1a2-0000-4000-8000-000000000002"
	ob := filepath.Join(filepath.Dir(base), other)
	put(t, ob, "work/old.txt", "old")
	bad := append([]byte(nil), archive...)
	bad[len(bad)/2] ^= 0xff
	for name, spec := range map[string]RestoreSpec{
		"wrong sha":    {SHA256: sum([]byte("x"))},
		"short header": {Size: int64(len(archive)) - 1},
		"long header":  {Size: int64(len(archive)) + 1},
	} {
		if _, err := restore(s, other, archive, spec); !errors.Is(err, ErrArchive) {
			t.Errorf("%s: %v", name, err)
		}
	}
	if _, err := restore(s, other, bad, RestoreSpec{}); !errors.Is(err, ErrArchive) {
		t.Errorf("corrupt: %v", err)
	}
	if _, err := restore(s, other, archive, RestoreSpec{Limits: Limits{StoredBytes: 10}}); !errors.Is(err, ErrLimit) {
		t.Errorf("stored limit: %v", err)
	}
	if b, _ := os.ReadFile(filepath.Join(ob, "work/old.txt")); string(b) != "old" {
		t.Fatal("a failed restore changed the session")
	}
}

type member struct {
	h    tar.Header
	data string
}

func makeArchive(t *testing.T, ms []member) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw, _ := zstd.NewWriter(&buf)
	tw := tar.NewWriter(zw)
	for _, m := range ms {
		h := m.h
		if h.Typeflag == tar.TypeReg && h.Size == 0 {
			h.Size = int64(len(m.data))
		}
		if h.Mode == 0 {
			h.Mode = 0o644
		}
		if err := tw.WriteHeader(&h); err != nil {
			t.Fatal(err)
		}
		if m.data != "" {
			if _, err := tw.Write([]byte(m.data)); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func TestRestoreSafety(t *testing.T) {
	s, base := newStore(t, Config{Limits: Limits{ExpandedBytes: 1000, Entries: 5}})
	victim := filepath.Join(filepath.Dir(filepath.Dir(base)), "victim")
	dir := func(n string) member { return member{h: tar.Header{Typeflag: tar.TypeDir, Name: n}} }
	reg := func(n, d string) member { return member{h: tar.Header{Typeflag: tar.TypeReg, Name: n}, data: d} }
	cases := map[string]struct {
		ms   []member
		want error
	}{
		"dotdot":         {[]member{dir("work/"), reg("work/../../victim", "x")}, ErrArchive},
		"absolute":       {[]member{reg("/tmp/victim", "x")}, ErrArchive},
		"unclean":        {[]member{reg("work//a", "x")}, ErrArchive},
		"other root":     {[]member{reg("etc/passwd", "x")}, ErrArchive},
		"root is a file": {[]member{reg("work", "x")}, ErrArchive},
		"symlink":        {[]member{dir("work/"), {h: tar.Header{Typeflag: tar.TypeSymlink, Name: "work/l", Linkname: victim}}}, ErrArchive},
		"hardlink":       {[]member{dir("work/"), {h: tar.Header{Typeflag: tar.TypeLink, Name: "work/l", Linkname: "work/a"}}}, ErrArchive},
		"char device":    {[]member{dir("work/"), {h: tar.Header{Typeflag: tar.TypeChar, Name: "work/null", Devmajor: 1, Devminor: 3}}}, ErrArchive},
		"block device":   {[]member{dir("work/"), {h: tar.Header{Typeflag: tar.TypeBlock, Name: "work/sda", Devmajor: 8}}}, ErrArchive},
		"fifo":           {[]member{dir("work/"), {h: tar.Header{Typeflag: tar.TypeFifo, Name: "work/f"}}}, ErrArchive},
		"duplicate":      {[]member{reg("work/a", "1"), reg("work/a", "2")}, ErrArchive},
		"size bomb":      {[]member{reg("work/a", strings.Repeat("a", 600)), reg("work/b", strings.Repeat("b", 600))}, ErrLimit},
		"entry bomb": {[]member{dir("work/"), reg("work/1", ""), reg("work/2", ""), reg("work/3", ""),
			reg("work/4", ""), reg("work/5", "")}, ErrLimit},
	}
	other := "a6f1b1a2-0000-4000-8000-000000000003"
	for name, c := range cases {
		archive := makeArchive(t, c.ms)
		if _, err := restore(s, other, archive, RestoreSpec{}); !errors.Is(err, c.want) {
			t.Errorf("%s: %v, want %v", name, err, c.want)
		}
	}
	if _, err := os.Lstat(victim); err == nil {
		t.Fatal("restore wrote outside the session")
	}
	ents, _ := os.ReadDir(filepath.Join(filepath.Dir(base), other))
	if len(ents) != 0 {
		t.Fatalf("failed restores left %v", ents)
	}
	// Not a zstd stream at all.
	if _, err := restore(s, other, []byte("not zstd at all"), RestoreSpec{}); !errors.Is(err, ErrArchive) {
		t.Fatalf("garbage: %v", err)
	}
	// Setuid bits are dropped.
	ok := makeArchive(t, []member{{h: tar.Header{Typeflag: tar.TypeReg, Name: "work/s", Mode: 0o4755}, data: "x"}})
	if _, err := restore(s, other, ok, RestoreSpec{}); err != nil {
		t.Fatal(err)
	}
	fi, err := os.Stat(filepath.Join(filepath.Dir(base), other, "work/s"))
	if err != nil || fi.Mode()&os.ModeSetuid != 0 || fi.Mode().Perm() != 0o755 {
		t.Fatalf("mode %v %v", fi.Mode(), err)
	}
}

func TestRestoreZstdWindowBomb(t *testing.T) {
	s, _ := newStore(t, Config{})
	var buf bytes.Buffer
	zw, _ := zstd.NewWriter(&buf, zstd.WithWindowSize(256<<20), zstd.WithEncoderLevel(zstd.SpeedFastest))
	tw := tar.NewWriter(zw)
	_ = tw.WriteHeader(&tar.Header{Typeflag: tar.TypeReg, Name: "work/a", Size: 1, Mode: 0o644})
	_, _ = tw.Write([]byte("a"))
	_ = tw.Close()
	_ = zw.Close()
	// The frame asks for a 256 MiB window. Single-segment frames carry the
	// content size instead, so only check that a restore never fails open.
	if _, err := restore(s, "a6f1b1a2-0000-4000-8000-000000000004", buf.Bytes(), RestoreSpec{}); err != nil &&
		!errors.Is(err, ErrArchive) {
		t.Fatalf("window bomb: %v", err)
	}
}

func TestRestoreCreatesSession(t *testing.T) {
	s, base := newStore(t, Config{})
	put(t, base, "work/a.txt", "a")
	archive, _ := capture(t, s, CaptureSpec{SessionID: sid})
	fresh := "a6f1b1a2-0000-4000-8000-000000000005"
	if _, err := restore(s, fresh, archive, RestoreSpec{}); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(filepath.Join(filepath.Dir(base), fresh, "work/a.txt")); string(b) != "a" {
		t.Fatalf("content %q", b)
	}
}

func TestRestoreRollsBackEveryRoot(t *testing.T) {
	s, base := newStore(t, Config{})
	put(t, base, "work/a.txt", "new a")
	put(t, base, "attachments/b.txt", "new b")
	archive, _ := capture(t, s, CaptureSpec{SessionID: sid})
	other := "a6f1b1a2-0000-4000-8000-000000000006"
	ob := filepath.Join(filepath.Dir(base), other)
	put(t, ob, "work/a.txt", "old a")
	put(t, ob, "attachments/b.txt", "old b")

	// work swaps, then attachments fails to move into place.
	orig := rename
	t.Cleanup(func() { rename = orig })
	rename = func(root *os.Root, from, to string) error {
		if to == "attachments" && strings.HasPrefix(from, stagingPrefix) {
			return errors.New("injected")
		}
		return orig(root, from, to)
	}
	if _, err := restore(s, other, archive, RestoreSpec{}); err == nil {
		t.Fatal("restore did not fail")
	}
	for rel, want := range map[string]string{"work/a.txt": "old a", "attachments/b.txt": "old b"} {
		if b, err := os.ReadFile(filepath.Join(ob, rel)); err != nil || string(b) != want {
			t.Errorf("%s = %q %v, want %q", rel, b, err, want)
		}
	}
	ents, _ := os.ReadDir(ob)
	for _, e := range ents {
		if strings.HasPrefix(e.Name(), ".craft-") {
			t.Fatalf("leftover %s", e.Name())
		}
	}
}

func TestRestoreRecoversInterruptedSwap(t *testing.T) {
	s, base := newStore(t, Config{})
	// The daemon stopped after it moved work to the trash and before it
	// moved the new tree in.
	put(t, base, oldPrefix+"x/work/a.txt", "old a")
	put(t, base, stagingPrefix+"y/work/a.txt", "new a")
	put(t, base, "attachments/b.txt", "b")
	put(t, base, oldPrefix+"x/attachments/b.txt", "older b")
	if _, err := restore(s, sid, []byte("not zstd at all"), RestoreSpec{}); !errors.Is(err, ErrArchive) {
		t.Fatalf("garbage: %v", err)
	}
	if b, err := os.ReadFile(filepath.Join(base, "work/a.txt")); err != nil || string(b) != "old a" {
		t.Fatalf("work/a.txt = %q %v", b, err)
	}
	// A root that is in place is not replaced by its trash copy.
	if b, _ := os.ReadFile(filepath.Join(base, "attachments/b.txt")); string(b) != "b" {
		t.Fatalf("attachments/b.txt = %q", b)
	}
	ents, _ := os.ReadDir(base)
	for _, e := range ents {
		if strings.HasPrefix(e.Name(), ".craft-") {
			t.Fatalf("leftover %s", e.Name())
		}
	}
}

func TestRestoreKeepsTrashWhenRecoveryFails(t *testing.T) {
	s, base := newStore(t, Config{})
	trash := oldPrefix + "x"
	put(t, base, trash+"/work/a.txt", "old a")
	orig := rename
	t.Cleanup(func() { rename = orig })
	rename = func(root *os.Root, from, to string) error {
		if strings.HasPrefix(from, oldPrefix) {
			return errors.New("injected")
		}
		return orig(root, from, to)
	}
	// A valid archive without work fails: success would leave work
	// only in the trash.
	other := "a6f1b1a2-0000-4000-8000-000000000009"
	put(t, filepath.Join(filepath.Dir(base), other), "attachments/b.txt", "b")
	archive, _ := capture(t, s, CaptureSpec{SessionID: other})
	if _, err := restore(s, sid, archive, RestoreSpec{}); err == nil || errors.Is(err, ErrArchive) {
		t.Fatalf("restore with an unrecovered root: %v", err)
	}
	if b, err := os.ReadFile(filepath.Join(base, trash, "work/a.txt")); err != nil || string(b) != "old a" {
		t.Fatalf("trash copy = %q %v", b, err)
	}
	if _, err := os.Stat(filepath.Join(base, "attachments")); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("restore changed the session: %v", err)
	}
	rename = orig
	_, _ = restore(s, sid, []byte("not zstd at all"), RestoreSpec{})
	if b, err := os.ReadFile(filepath.Join(base, "work/a.txt")); err != nil || string(b) != "old a" {
		t.Fatalf("work/a.txt = %q %v", b, err)
	}
	if _, err := os.Stat(filepath.Join(base, trash)); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("trash not removed: %v", err)
	}
}

func TestCaptureRecoversInterruptedSwap(t *testing.T) {
	s, base := newStore(t, Config{})
	trash := oldPrefix + "x"
	put(t, base, trash+"/work/a.txt", "old a")
	orig := rename
	t.Cleanup(func() { rename = orig })
	rename = func(root *os.Root, from, to string) error {
		if strings.HasPrefix(from, oldPrefix) {
			return errors.New("injected")
		}
		return orig(root, from, to)
	}
	if _, err := s.Capture(context.Background(), CaptureSpec{SessionID: sid}, io.Discard); err == nil {
		t.Fatal("capture did not fail with an unrecovered root")
	}
	rename = orig
	archive, _ := capture(t, s, CaptureSpec{SessionID: sid})
	other := "a6f1b1a2-0000-4000-8000-000000000008"
	if _, err := restore(s, other, archive, RestoreSpec{}); err != nil {
		t.Fatal(err)
	}
	if b, err := os.ReadFile(filepath.Join(filepath.Dir(base), other, "work/a.txt")); err != nil || string(b) != "old a" {
		t.Fatalf("work/a.txt = %q %v", b, err)
	}
	if _, err := os.Stat(filepath.Join(base, trash)); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("trash not removed: %v", err)
	}
}

func TestRestoreTailBomb(t *testing.T) {
	s, _ := newStore(t, Config{})
	var buf bytes.Buffer
	zw, _ := zstd.NewWriter(&buf)
	tw := tar.NewWriter(zw)
	_ = tw.WriteHeader(&tar.Header{Typeflag: tar.TypeReg, Name: "work/a", Size: 1, Mode: 0o644})
	_, _ = tw.Write([]byte("a"))
	_ = tw.Close()
	// A small archive whose stream goes on long after the tar end.
	if _, err := zw.Write(make([]byte, 8<<20)); err != nil {
		t.Fatal(err)
	}
	_ = zw.Close()
	if buf.Len() > 64<<10 {
		t.Fatalf("tail did not compress: %d bytes", buf.Len())
	}
	if _, err := restore(s, "a6f1b1a2-0000-4000-8000-000000000007", buf.Bytes(), RestoreSpec{}); !errors.Is(err, ErrLimit) {
		t.Fatalf("tail bomb: %v", err)
	}
}

func TestRestoreUnusualNames(t *testing.T) {
	s, base := newStore(t, Config{})
	ctx := context.Background()
	// A backslash is a normal character on Linux: write, save and restore.
	if _, _, err := s.Write(ctx, sid, WriteSpec{Path: `work/a\b.txt`, Size: 1, MakeParents: true},
		strings.NewReader("x")); err != nil {
		t.Fatal(err)
	}
	// A name that is not UTF-8 is left out of the save, so the save still
	// restores. Some file systems (APFS) refuse such names.
	badName := filepath.Join(base, "work", "bad\xff.txt")
	madeBad := os.WriteFile(badName, []byte("y"), 0o644) == nil
	archive, cs := capture(t, s, CaptureSpec{SessionID: sid})
	if madeBad && cs.Skipped != 1 {
		t.Fatalf("summary %+v", cs)
	}
	other := "a6f1b1a2-0000-4000-8000-000000000008"
	if _, err := restore(s, other, archive, RestoreSpec{}); err != nil {
		t.Fatal(err)
	}
	if b, err := os.ReadFile(filepath.Join(filepath.Dir(base), other, `work/a\b.txt`)); err != nil || string(b) != "x" {
		t.Fatalf("backslash file = %q %v", b, err)
	}
}

func TestFIFOsDoNotBlock(t *testing.T) {
	s, base := newStore(t, Config{})
	put(t, base, "work/a.txt", "a")
	fifo := filepath.Join(base, "work", "pipe")
	if err := syscall.Mkfifo(fifo, 0o644); err != nil {
		t.Skipf("mkfifo: %v", err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		if _, _, err := read(t, s, "work/pipe", 0, 0); !errors.Is(err, ErrInvalid) {
			t.Errorf("read fifo: %v", err)
		}
		root, err := os.OpenRoot(base)
		if err != nil {
			t.Error(err)
			return
		}
		defer func() { _ = root.Close() }()
		// Capture and Zip open through openRegular, so a file that became
		// a FIFO after the walk is refused, not waited on.
		if _, _, err := openRegular(root, "work/pipe", syscall.O_NOFOLLOW); !errors.Is(err, errNotRegular) {
			t.Errorf("openRegular fifo: %v", err)
		}
		if _, cs := capture(t, s, CaptureSpec{SessionID: sid}); cs.Skipped != 1 || cs.Files != 1 {
			t.Errorf("capture %+v", cs)
		}
		if zs, err := s.Zip(context.Background(), sid, ZipSpec{Path: "work"}, io.Discard); err != nil || zs.Files != 1 {
			t.Errorf("zip %+v %v", zs, err)
		}
	}()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("a FIFO blocked a file call")
	}
}

func TestReadDirCap(t *testing.T) {
	_, base := newStore(t, Config{})
	for i := range 30 {
		put(t, base, fmt.Sprintf("work/f%02d", i), "")
	}
	root, err := os.OpenRoot(base)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = root.Close() }()
	if _, err := readDir(root, "work", 10); !errors.Is(err, errDirTooBig) || !errors.Is(err, ErrLimit) {
		t.Fatalf("over the cap: %v", err)
	}
	ents, err := readDir(root, "work", 30)
	if err != nil || len(ents) != 30 || ents[0].Name() != "f00" || ents[29].Name() != "f29" {
		t.Fatalf("at the cap: %d entries, %v", len(ents), err)
	}
	// Capture fails on a directory over the entry limit.
	s, base2 := newStore(t, Config{Limits: Limits{Entries: 10}})
	for i := range 30 {
		put(t, base2, fmt.Sprintf("work/f%02d", i), "")
	}
	if _, err := s.Capture(context.Background(), CaptureSpec{SessionID: sid}, io.Discard); !errors.Is(err, ErrLimit) {
		t.Fatalf("capture: %v", err)
	}
}

func TestZipCountsDirectoriesAndDepth(t *testing.T) {
	ctx := context.Background()
	s, base := newStore(t, Config{MaxZipEntries: 3})
	// Each directory holds one entry, under the per-directory read cap.
	if err := os.MkdirAll(filepath.Join(base, "work/e/1/2/3/4"), 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Zip(ctx, sid, ZipSpec{Path: "work/e"}, io.Discard); !errors.Is(err, ErrLimit) {
		t.Fatalf("empty directories over the limit: %v", err)
	}

	s, base = newStore(t, Config{})
	deep := "work/z" + strings.Repeat("/d", maxDepth+1)
	put(t, base, "work/z/top.txt", "t")
	put(t, base, deep+"/f.txt", "f")
	var buf bytes.Buffer
	zs, err := s.Zip(ctx, sid, ZipSpec{Path: "work/z"}, &buf)
	if err != nil {
		t.Fatal(err)
	}
	if zs.Files != 1 || zs.Skipped != 1 {
		t.Fatalf("summary %+v", zs)
	}
}

func TestRestoreCountsParentDirectories(t *testing.T) {
	ms := []member{{h: tar.Header{Typeflag: tar.TypeReg, Name: "work/a/b/c/d/f"}, data: "x"}}
	other := "a6f1b1a2-0000-4000-8000-000000000008"
	s, _ := newStore(t, Config{Limits: Limits{Entries: 5}})
	// One member and five parents.
	if _, err := restore(s, other, makeArchive(t, ms), RestoreSpec{}); !errors.Is(err, ErrLimit) {
		t.Fatalf("parents over the limit: %v", err)
	}
	s, _ = newStore(t, Config{Limits: Limits{Entries: 6}})
	rs, err := restore(s, other, makeArchive(t, ms), RestoreSpec{})
	if err != nil {
		t.Fatal(err)
	}
	if rs.Files != 1 || rs.Directories != 5 {
		t.Fatalf("summary %+v", rs)
	}
	// A parent that is a file is refused.
	ms = []member{{h: tar.Header{Typeflag: tar.TypeReg, Name: "work/a"}, data: "x"},
		{h: tar.Header{Typeflag: tar.TypeReg, Name: "work/a/b"}, data: "y"}}
	if _, err := restore(s, other, makeArchive(t, ms), RestoreSpec{}); !errors.Is(err, ErrArchive) {
		t.Fatalf("file as a parent: %v", err)
	}
}
