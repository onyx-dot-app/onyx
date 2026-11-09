package template

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

var testKey = Key{
	ImageRef: "onyxdotapp/sandbox:v5.1.0", FirecrackerVersion: "v1.17.0", CPUModel: "Intel Xeon 6975P-C",
	HostKernel: "6.18.56", GuestKernelSHA256: strings.Repeat("1", 64), CAFingerprint: strings.Repeat("c", 64),
	VCPUs: 2, MemMiB: 4096, ScratchGiB: 1,
}

var testNode = NodeKey{
	FirecrackerVersion: "v1.17.0", CPUModel: "Intel Xeon 6975P-C", HostKernel: "6.18.56",
	GuestKernelSHA256: strings.Repeat("1", 64), CAFingerprint: strings.Repeat("c", 64),
}

func fake(t *testing.T, dir, version string, built time.Time) {
	t.Helper()
	if _, err := WriteFake(dir, version, testKey); err != nil {
		t.Fatal(err)
	}
	m := readManifest(t, dir, version)
	m.BuiltAt = built
	if err := WriteManifest(filepath.Join(dir, version), m); err != nil {
		t.Fatal(err)
	}
}

func readManifest(t *testing.T, dir, version string) Manifest {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(dir, version, ManifestFile))
	if err != nil {
		t.Fatal(err)
	}
	var m Manifest
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	return m
}

func TestStoreGetAndList(t *testing.T) {
	dir := t.TempDir()
	fake(t, dir, "b-2", time.Now())
	fake(t, dir, "a-1", time.Now())
	if err := os.MkdirAll(filepath.Join(dir, "broken"), 0o755); err != nil {
		t.Fatal(err)
	}
	s := &Store{Dir: dir}

	tpl, err := s.Get("a-1")
	if err != nil || tpl.VCPUs != 2 || tpl.Path(MemFile) != filepath.Join(dir, "a-1", MemFile) {
		t.Fatalf("get: %+v %v", tpl, err)
	}
	if tpl.KeySHA256 != tpl.Hash() || tpl.LayoutVersion != LayoutVersion || tpl.RootfsSHA256 != tpl.Files[RootfsFile] || len(tpl.Files) != len(Files) {
		t.Fatalf("manifest: %+v", tpl.Manifest)
	}
	for name, want := range map[string]pb.ErrorReason{
		"broken": pb.ErrorReason_TEMPLATE_MISSING, "nope": pb.ErrorReason_TEMPLATE_MISSING, "../a-1": pb.ErrorReason_INVALID_ARGUMENT,
	} {
		if _, err := s.Get(name); apierr.ReasonOf(err) != want {
			t.Errorf("%s: %v, want %s", name, err, want)
		}
	}
	if err := os.Remove(filepath.Join(dir, "b-2", UploadBFile)); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Get("b-2"); apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_MISSING {
		t.Fatalf("missing upload slot: %v", err)
	}
	list, err := s.List()
	if err != nil || len(list) != 1 || list[0].Version != "a-1" {
		t.Fatalf("list: %v %v", list, err)
	}
}

// A manifest that does not hash to itself is refused: an edit of the key
// without the matching key hash, or of a file hash without the snapshot hash.
func TestManifestSelfCheck(t *testing.T) {
	for name, edit := range map[string]func(m *Manifest){
		"cpu model edited":    func(m *Manifest) { m.CPUModel = "Other CPU" },
		"mem hash edited":     func(m *Manifest) { m.Files[MemFile] = strings.Repeat("0", 64) },
		"snapshot hash":       func(m *Manifest) { m.SnapshotSHA256 = strings.Repeat("0", 64) },
		"rootfs differs":      func(m *Manifest) { m.RootfsSHA256 = strings.Repeat("0", 64); m.KeySHA256 = m.Hash() },
		"older layout":        func(m *Manifest) { m.Schema = 1 },
		"file missing":        func(m *Manifest) { delete(m.Files, UploadAFile) },
		"version is not name": func(m *Manifest) { m.Version = "other" },
	} {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			fake(t, dir, "t1", time.Now())
			m := readManifest(t, dir, "t1")
			edit(&m)
			if err := WriteManifest(filepath.Join(dir, "t1"), m); err != nil {
				t.Fatal(err)
			}
			_, err := (&Store{Dir: dir}).Get("t1")
			if apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE {
				t.Fatalf("got %v, want TEMPLATE_INCOMPATIBLE", err)
			}
		})
	}
}

func TestCheckNode(t *testing.T) {
	k := testKey
	k.LayoutVersion = LayoutVersion
	if err := k.CheckNode(testNode); err != nil {
		t.Fatal(err)
	}
	noCA := testNode
	noCA.CAFingerprint = ""
	if err := k.CheckNode(noCA); err != nil {
		t.Fatalf("a node without a CA setting must not check it: %v", err)
	}
	for name, edit := range map[string]func(n *NodeKey){
		"firecracker":  func(n *NodeKey) { n.FirecrackerVersion = "v1.18.0" },
		"cpu model":    func(n *NodeKey) { n.CPUModel = "AMD EPYC 9R14" },
		"host kernel":  func(n *NodeKey) { n.HostKernel = "6.12.1" },
		"guest kernel": func(n *NodeKey) { n.GuestKernelSHA256 = strings.Repeat("2", 64) },
		"egress CA":    func(n *NodeKey) { n.CAFingerprint = strings.Repeat("d", 64) },
	} {
		n := testNode
		edit(&n)
		err := k.CheckNode(n)
		if apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE || !strings.Contains(err.Error(), name) {
			t.Errorf("%s: %v", name, err)
		}
	}
	old := k
	old.LayoutVersion = 1
	if err := old.CheckNode(testNode); apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE {
		t.Errorf("old layout: %v", err)
	}
}

func TestVerifyDetectsTampering(t *testing.T) {
	dir := t.TempDir()
	fake(t, dir, "t1", time.Now())
	s := &Store{Dir: dir}
	get := func() *Template {
		t.Helper()
		tpl, err := s.Get("t1")
		if err != nil {
			t.Fatal(err)
		}
		return tpl
	}
	tpl := get()
	if err := s.Verify(tpl); err != nil {
		t.Fatal(err)
	}
	if err := tpl.CheckUnchanged(); err != nil {
		t.Fatal(err)
	}
	// Same size and mtime, other content: the ctime (or inode) changes, so the
	// fingerprint misses and the hash runs again.
	vm := filepath.Join(dir, "t1", VMStateFile)
	st, _ := os.Stat(vm)
	if err := os.WriteFile(vm, []byte("vmstatX"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(vm, st.ModTime(), st.ModTime()); err != nil {
		t.Fatal(err)
	}
	if err := tpl.CheckUnchanged(); apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE {
		t.Fatalf("CheckUnchanged after a write: %v", err)
	}
	err := s.Verify(get())
	if apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE || !strings.Contains(err.Error(), VMStateFile) {
		t.Fatalf("verify after a write: %v", err)
	}
	// Putting the content back makes it valid again (after a full hash).
	if err := os.WriteFile(vm, []byte(VMStateFile), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := s.Verify(get()); err != nil {
		t.Fatalf("restored file: %v", err)
	}
	// A replaced file (new inode, same content) is hashed again and passes.
	if err := os.Remove(vm); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(vm, []byte(VMStateFile), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := s.Verify(get()); err != nil {
		t.Fatalf("replaced file: %v", err)
	}
	if err := (&Template{Manifest: tpl.Manifest, Dir: tpl.Dir}).CheckUnchanged(); err == nil {
		t.Fatal("CheckUnchanged of a template that was not verified")
	}
}

func TestSealAndMarkVerified(t *testing.T) {
	dir := t.TempDir()
	d := filepath.Join(dir, "t1")
	if err := os.MkdirAll(d, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, f := range Files {
		if err := os.WriteFile(filepath.Join(d, f), []byte(f+"-data"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	rootSum, _ := FileSHA256(filepath.Join(d, RootfsFile))
	m, prints, err := Seal(d, Manifest{Version: "t1", Key: testKey}, map[string]string{RootfsFile: rootSum})
	if err != nil {
		t.Fatal(err)
	}
	memSum, _ := FileSHA256(filepath.Join(d, MemFile))
	if m.Files[MemFile] != memSum || m.RootfsSHA256 != rootSum || m.SnapshotSHA256 != SnapshotHash(LayoutVersion, m.KeySHA256, m.Files) {
		t.Fatalf("sealed %+v", m)
	}
	s := &Store{Dir: dir}
	tpl, err := s.Get("t1")
	if err != nil {
		t.Fatal(err)
	}
	if err := s.MarkVerified(tpl, prints); err != nil {
		t.Fatal(err)
	}
	if err := s.Verify(tpl); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(d, ScratchFile), []byte("changed"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := s.MarkVerified(tpl, prints); err == nil {
		t.Fatal("MarkVerified accepted a changed file")
	}
}

func TestSnapshotHashOrderAndCoverage(t *testing.T) {
	files := map[string]string{}
	for _, f := range Files {
		files[f] = strings.Repeat("a", 64)
	}
	base := SnapshotHash(LayoutVersion, "k", files)
	for _, f := range Files {
		c := map[string]string{}
		for k, v := range files {
			c[k] = v
		}
		c[f] = strings.Repeat("b", 64)
		if SnapshotHash(LayoutVersion, "k", c) == base {
			t.Errorf("snapshot hash does not cover %s", f)
		}
	}
	if SnapshotHash(LayoutVersion, "other key", files) == base {
		t.Error("snapshot hash does not cover the key")
	}
}

func TestGCKeepsNewestAndInUse(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	fake(t, dir, "v1", now.Add(-4*time.Hour))
	fake(t, dir, "v2", now.Add(-3*time.Hour))
	fake(t, dir, "v3", now.Add(-2*time.Hour))
	fake(t, dir, "v4", now.Add(-1*time.Hour))
	// An older layout and a build in progress.
	if err := os.MkdirAll(filepath.Join(dir, "old-layout"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "old-layout", ManifestFile), []byte(`{"version":"old-layout"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(dir, ".build-v5"), 0o755); err != nil {
		t.Fatal(err)
	}
	s := &Store{Dir: dir}
	removed, err := s.GC(2, func() map[string]bool { return map[string]bool{"v1": true} })
	if err != nil {
		t.Fatal(err)
	}
	got := strings.Join(removed, ",")
	if got != "v2,old-layout" {
		t.Fatalf("removed %q, want v2,old-layout (keep v4, v3 and v1 in use)", got)
	}
	for _, d := range []string{"v1", "v3", "v4", ".build-v5"} {
		if _, err := os.Stat(filepath.Join(dir, d)); err != nil {
			t.Errorf("%s removed: %v", d, err)
		}
	}
	// v1 is no longer in use: the next GC removes it.
	removed, err = s.GC(2, noneInUse)
	if err != nil || strings.Join(removed, ",") != "v1" {
		t.Fatalf("second GC removed %v %v", removed, err)
	}
	list, _ := s.List()
	if len(list) != 2 {
		t.Fatalf("%d templates left, want 2", len(list))
	}
}

func noneInUse() map[string]bool { return nil }

func TestPinKeepsTemplateFromGCAndRemove(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	fake(t, dir, "v1", now.Add(-2*time.Hour))
	fake(t, dir, "v2", now.Add(-1*time.Hour))
	s := &Store{Dir: dir}
	unpin := s.Pin("v1")
	removed, err := s.GC(1, noneInUse)
	if err != nil || len(removed) != 0 {
		t.Fatalf("GC of a pinned template removed %v %v", removed, err)
	}
	if ok, err := s.RemoveUnused("v1", noneInUse); ok || err != nil {
		t.Fatalf("RemoveUnused of a pinned template: %v %v", ok, err)
	}
	// A second unpin call does nothing.
	unpin()
	unpin()
	removed, err = s.GC(1, noneInUse)
	if err != nil || strings.Join(removed, ",") != "v1" {
		t.Fatalf("GC after unpin removed %v %v", removed, err)
	}
	if ok, err := s.RemoveUnused("v2", func() map[string]bool { return map[string]bool{"v2": true} }); ok || err != nil {
		t.Fatalf("RemoveUnused of a template in use: %v %v", ok, err)
	}
	if ok, err := s.RemoveUnused("v2", noneInUse); !ok || err != nil {
		t.Fatalf("RemoveUnused: %v %v", ok, err)
	}
	if ok, _ := s.Exists("v2"); ok {
		t.Fatal("v2 still there")
	}
}

func TestVerifyCacheDoesNotCoverANewManifest(t *testing.T) {
	dir := t.TempDir()
	fake(t, dir, "t1", time.Now())
	s := &Store{Dir: dir}
	tpl, err := s.Get("t1")
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Verify(tpl); err != nil {
		t.Fatal(err)
	}
	// A self-consistent manifest that claims another mem hash, with the
	// same data files: the cached check must not pass it.
	m := tpl.Manifest
	m.Files = map[string]string{}
	for k, v := range tpl.Files {
		m.Files[k] = v
	}
	m.Files[MemFile] = strings.Repeat("e", 64)
	m.SnapshotSHA256 = SnapshotHash(m.Schema, m.KeySHA256, m.Files)
	if err := WriteManifest(tpl.Dir, m); err != nil {
		t.Fatal(err)
	}
	other, err := s.Get("t1")
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Verify(other); apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE || !strings.Contains(err.Error(), MemFile) {
		t.Fatalf("verify of a changed manifest: %v", err)
	}
}

// Layout 2 templates (no managed slot B) still load, verify and restore. The
// layout 2 snapshot hash is the one that the layout 2 agent wrote.
func TestLayout2StillRestores(t *testing.T) {
	files := map[string]string{}
	for _, f := range FilesFor(2) {
		files[f] = strings.Repeat("a", 64)
	}
	if got := SnapshotHash(2, "k", files); got != "49823fc19879179bd4251cc5d836357557aa7010e308cb18dbb057852d40b288" {
		t.Fatalf("layout 2 snapshot hash changed: %s", got)
	}
	dir := t.TempDir()
	if _, err := WriteFakeLayout(dir, "old", testKey, 2); err != nil {
		t.Fatal(err)
	}
	if _, err := WriteFake(dir, "new", testKey); err != nil {
		t.Fatal(err)
	}
	s := &Store{Dir: dir}
	for name, want := range map[string]int{"old": 1, "new": 2} {
		tpl, err := s.Get(name)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if err := tpl.CheckNode(testNode); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if err := s.Verify(tpl); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if err := tpl.CheckUnchanged(); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if got := tpl.ManagedSlots(); got != want {
			t.Errorf("%s: %d managed slots, want %d", name, got, want)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "old", ManagedBFile)); err == nil {
		t.Error("a layout 2 template has a slot B file")
	}
	if d := DrivesFor(LayoutVersion); d[len(d)-1].ID != ManagedBDriveID || len(d) != 6 {
		t.Errorf("slot B must be the last drive (vdf): %+v", d)
	}
	for i, d := range DrivesFor(2) {
		if DrivesFor(LayoutVersion)[i] != d {
			t.Errorf("drive %d moved: %+v", i, DrivesFor(LayoutVersion)[i])
		}
	}
	k := testKey
	k.LayoutVersion = 1
	if err := k.CheckNode(testNode); apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE {
		t.Errorf("layout 1: %v", err)
	}
}
