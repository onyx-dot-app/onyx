package files

import (
	"archive/tar"
	"context"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"syscall"
	"testing"
)

// chownLog records the owner changes of a Store.
type chownLog struct {
	mu    sync.Mutex
	names []string
	fail  bool
}

func (c *chownLog) use(s *Store) {
	s.chown = func(_ *os.Root, name string, uid, gid int) error {
		c.mu.Lock()
		defer c.mu.Unlock()
		if uid != 1000 || gid != 1001 {
			return errors.New("wrong owner")
		}
		if c.fail {
			return syscall.EPERM
		}
		c.names = append(c.names, name)
		return nil
	}
}

// got returns the recorded names; temp names lose their random suffix.
func (c *chownLog) got() []string {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]string, 0, len(c.names))
	for _, n := range c.names {
		if i := strings.Index(n, writePrefix); i >= 0 {
			n = n[:i] + writePrefix + "*"
		}
		out = append(out, n)
	}
	return out
}

func ownedStore(t *testing.T) (*Store, string, *chownLog) {
	t.Helper()
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(dir, "workspace", "sessions")
	s, err := New(Config{SessionsRoot: root, CaptureRoots: []string{"work", "attachments"}, Owner: &Owner{UID: 1000, GID: 1001}})
	if err != nil {
		t.Fatal(err)
	}
	log := &chownLog{}
	log.use(s)
	return s, root, log
}

func TestWriteGivesNewFilesAndDirectoriesToTheOwner(t *testing.T) {
	s, root, log := ownedStore(t)
	ctx := context.Background()
	// The sessions root, the session and the new parents; "workspace" (above
	// the sessions root) keeps its owner.
	if _, _, err := s.Write(ctx, sid, WriteSpec{Path: "a/b/c.txt", Size: 1, MakeParents: true}, strings.NewReader("x")); err != nil {
		t.Fatal(err)
	}
	want := []string{".", sid, "a", "a/b", "a/b/" + writePrefix + "*"}
	if got := log.got(); !slices.Equal(got, want) {
		t.Fatalf("chown %v, want %v", got, want)
	}
	// Existing directories keep their owner; an overwrite gets a new file.
	log.names = nil
	if _, _, err := s.Write(ctx, sid, WriteSpec{Path: "a/b/c.txt", Size: 1, Overwrite: true}, strings.NewReader("y")); err != nil {
		t.Fatal(err)
	}
	if got := log.got(); !slices.Equal(got, []string{"a/b/" + writePrefix + "*"}) {
		t.Fatalf("overwrite chown %v", got)
	}
	if _, err := os.Stat(filepath.Join(root, sid, "a/b/c.txt")); err != nil {
		t.Fatal(err)
	}
}

func TestUploadGivesTheFileAndItsDirectoryToTheOwner(t *testing.T) {
	s, _, log := ownedStore(t)
	if _, _, err := s.Upload(context.Background(), sid, UploadSpec{FileName: "r.pdf", Size: 2}, strings.NewReader("pd")); err != nil {
		t.Fatal(err)
	}
	want := []string{".", sid, "attachments", "attachments/" + writePrefix + "*"}
	if got := log.got(); !slices.Equal(got, want) {
		t.Fatalf("chown %v, want %v", got, want)
	}
}

func TestRestoreGivesEveryMemberToTheOwner(t *testing.T) {
	s, root, log := ownedStore(t)
	ms := []member{
		{h: tar.Header{Typeflag: tar.TypeDir, Name: "work/", Mode: 0o755}},
		{h: tar.Header{Typeflag: tar.TypeReg, Name: "work/d/f.txt"}, data: "x"},
	}
	if _, err := restore(s, sid, makeArchive(t, ms), RestoreSpec{}); err != nil {
		t.Fatal(err)
	}
	want := []string{".", sid, "work", "work/d", "work/d/f.txt"}
	if got := log.got(); !slices.Equal(got, want) {
		t.Fatalf("chown %v, want %v", got, want)
	}
	if b, err := os.ReadFile(filepath.Join(root, sid, "work/d/f.txt")); err != nil || string(b) != "x" {
		t.Fatalf("restored %q %v", b, err)
	}
}

func TestOwnerFailureFailsTheCallAndLeavesNoFile(t *testing.T) {
	s, root, log := ownedStore(t)
	if err := os.MkdirAll(filepath.Join(root, sid), 0o755); err != nil {
		t.Fatal(err)
	}
	log.fail = true
	if _, _, err := s.Write(context.Background(), sid, WriteSpec{Path: "f.txt", Size: 1}, strings.NewReader("x")); !errors.Is(err, syscall.EPERM) {
		t.Fatalf("err = %v", err)
	}
	ents, err := os.ReadDir(filepath.Join(root, sid))
	if err != nil || len(ents) != 0 {
		t.Fatalf("left %v %v", ents, err)
	}
}

func TestNoOwnerChangesNothing(t *testing.T) {
	s, _ := newStore(t, Config{})
	s.chown = func(*os.Root, string, int, int) error { t.Fatal("chown without an owner"); return nil }
	if _, _, err := s.Write(context.Background(), sid, WriteSpec{Path: "x/y.txt", Size: 1, MakeParents: true}, strings.NewReader("x")); err != nil {
		t.Fatal(err)
	}
	if _, err := New(Config{Owner: &Owner{UID: -1}}); err == nil {
		t.Fatal("accepted a negative uid")
	}
}

// TestOwnerOnDisk needs root (the guest daemon runs as root).
func TestOwnerOnDisk(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("needs root")
	}
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	ws := filepath.Join(dir, "workspace")
	s, err := New(Config{SessionsRoot: filepath.Join(ws, "sessions"), Owner: &Owner{UID: 1000, GID: 1000}})
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if _, _, err := s.Write(ctx, sid, WriteSpec{Path: "a/b.txt", Size: 1, MakeParents: true}, strings.NewReader("x")); err != nil {
		t.Fatal(err)
	}
	if _, _, err := s.Upload(ctx, sid, UploadSpec{FileName: "u.txt", Size: 1}, strings.NewReader("u")); err != nil {
		t.Fatal(err)
	}
	owner := func(p string) (uint32, uint32) {
		fi, err := os.Lstat(p)
		if err != nil {
			t.Fatal(err)
		}
		st := fi.Sys().(*syscall.Stat_t)
		return st.Uid, st.Gid
	}
	for _, p := range []string{"sessions", "sessions/" + sid, "sessions/" + sid + "/a", "sessions/" + sid + "/a/b.txt",
		"sessions/" + sid + "/attachments", "sessions/" + sid + "/attachments/u.txt"} {
		if uid, gid := owner(filepath.Join(ws, p)); uid != 1000 || gid != 1000 {
			t.Errorf("%s owned by %d:%d", p, uid, gid)
		}
	}
	if uid, _ := owner(ws); uid != 0 {
		t.Errorf("workspace owned by %d; directories above the sessions root keep their owner", uid)
	}
}

func TestParseOwner(t *testing.T) {
	if o, err := ParseOwner(""); o != nil || err != nil {
		t.Fatalf("empty = %v %v", o, err)
	}
	if o, err := ParseOwner(DefaultOwner); err != nil || *o != (Owner{UID: 1000, GID: 1000}) {
		t.Fatalf("default = %v %v", o, err)
	}
	for _, bad := range []string{"1000", "a:b", "-1:0", "1000:", ":1000", "1:2:3", "4294967296:0"} {
		if _, err := ParseOwner(bad); err == nil {
			t.Errorf("accepted %q", bad)
		}
	}
}
