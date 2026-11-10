package tplbuild

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// fakeVMM copies the files into a chroot like the real launcher, and
// "snapshots" by writing vmstate and mem there.
type fakeVMM struct {
	mu      sync.Mutex
	root    string
	boots   int
	cfgs    []BootConfig
	files   [][]File
	killed  int
	memData string
}

type fakeVM struct {
	v   *fakeVMM
	dir string
}

func (v *fakeVMM) Boot(_ context.Context, id string, _ uint32, files []File, cfg BootConfig) (VM, error) {
	v.mu.Lock()
	defer v.mu.Unlock()
	v.boots++
	v.cfgs = append(v.cfgs, cfg)
	v.files = append(v.files, files)
	dir := filepath.Join(v.root, id)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	for _, f := range files {
		if _, err := scratch.CopyFile(f.Src, filepath.Join(dir, f.Name)); err != nil {
			return nil, err
		}
	}
	return &fakeVM{v: v, dir: dir}, nil
}

func (m *fakeVM) VsockPath() string { return filepath.Join(m.dir, "v.sock") }

func (m *fakeVM) Snapshot(context.Context) (string, string, error) {
	vs, mem := filepath.Join(m.dir, template.VMStateFile), filepath.Join(m.dir, template.MemFile)
	if err := os.WriteFile(vs, []byte("vmstate"), 0o600); err != nil {
		return "", "", err
	}
	if err := os.WriteFile(mem, []byte(m.v.memData), 0o600); err != nil {
		return "", "", err
	}
	return vs, mem, nil
}

func (m *fakeVM) Kill(context.Context) error {
	m.v.mu.Lock()
	m.v.killed++
	m.v.mu.Unlock()
	return os.RemoveAll(m.dir)
}

type fakeSlots struct {
	mu    sync.Mutex
	inUse map[string]bool
	held  map[string]bool
	freed int
}

func (s *fakeSlots) BuildSlot(id string, _ uint32) (uint32, func(bool), error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.held == nil {
		s.held = map[string]bool{}
	}
	s.held[id] = true
	return 1000, func(left bool) {
		s.mu.Lock()
		defer s.mu.Unlock()
		delete(s.held, id)
		if !left {
			s.freed++
		}
	}, nil
}

func (s *fakeSlots) TemplatesInUse() map[string]bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := map[string]bool{}
	for k, v := range s.inUse {
		out[k] = v
	}
	return out
}

var node = template.NodeKey{
	FirecrackerVersion: "v1.17.0", CPUModel: "Intel Xeon 6975P-C", HostKernel: "6.18.56",
	GuestKernelSHA256: strings.Repeat("1", 64), CAFingerprint: strings.Repeat("ab", 32),
}

type rig struct {
	b     *Builder
	vmm   *fakeVMM
	slots *fakeSlots
	data  string
}

func newRig(t *testing.T) *rig {
	t.Helper()
	data := t.TempDir()
	kernel := filepath.Join(data, "vmlinux")
	if err := os.WriteFile(kernel, []byte("kernel"), 0o644); err != nil {
		t.Fatal(err)
	}
	vmm := &fakeVMM{root: filepath.Join(data, "jail"), memData: "mem"}
	slots := &fakeSlots{}
	b := &Builder{
		Store: &template.Store{Dir: filepath.Join(data, "templates")}, VMM: vmm, Slots: slots, Node: node,
		GuestKernel: "6.18.25", KernelPath: kernel, VCPUs: 2, MemMiB: 4096, ScratchGiB: 1, Keep: 2,
		Ready: func(context.Context, string) error { return nil },
		Mkfs: func(_ context.Context, path string, size int64, label string) error {
			return os.WriteFile(path, []byte(label), 0o644)
		},
		Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	return &rig{b: b, vmm: vmm, slots: slots, data: data}
}

// writeRootfs writes a build-rootfs.sh style output with drive content data.
func writeRootfs(t *testing.T, dir, data, ca string) *Rootfs {
	t.Helper()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, RootfsImageFile), []byte(data), 0o644); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256([]byte(data))
	m := map[string]any{
		"schema": 1, "kind": "craft-fc-rootfs",
		"source_image": map[string]any{"ref": "onyxdotapp/sandbox:v5.1.0", "digest": "sha256:40928cdd"},
		"build_inputs": map[string]any{"egress_ca": map[string]any{"sha256_fingerprint": ca}},
		"guest": map[string]any{
			"boot_args": "console=ttyS0 reboot=k panic=1 pci=off init=/sbin/craft-init", "template_boot_args_extra": "craft.scratch=defer",
			"drives": []map[string]any{
				{"drive_id": "rootfs", "is_read_only": true}, {"drive_id": "scratch", "is_read_only": false},
				{"drive_id": "managed", "is_read_only": true},
			},
			"managed_slots": map[string]any{"a": "/dev/vdc", "b": "/dev/vdf"},
			"daemon":        map[string]any{"vsock_port": 52},
		},
		"output": map[string]any{"file": RootfsImageFile, "sha256": hex.EncodeToString(sum[:]), "size_bytes": len(data)},
	}
	raw, _ := json.Marshal(m)
	if err := os.WriteFile(filepath.Join(dir, RootfsManifestFile), raw, 0o644); err != nil {
		t.Fatal(err)
	}
	r, err := LoadRootfs(dir)
	if err != nil {
		t.Fatal(err)
	}
	return r
}

// The CA as openssl prints it (upper case, colons).
var opensslCA = strings.ToUpper(strings.TrimSuffix(strings.Repeat("ab:", 32), ":"))

func nlink(t *testing.T, path string) uint64 {
	t.Helper()
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	return uint64(st.Sys().(*syscall.Stat_t).Nlink)
}

func TestBuildWritesAVerifiedTemplate(t *testing.T) {
	r := newRig(t)
	in := writeRootfs(t, filepath.Join(r.data, "in"), "root drive", opensslCA)
	res, err := r.b.Build(context.Background(), in)
	if err != nil {
		t.Fatal(err)
	}
	tpl := res.Template
	if !res.Built || !strings.HasPrefix(tpl.Version, "v5.1.0-") || len(tpl.Version) != len("v5.1.0-")+12 {
		t.Fatalf("result %+v", res)
	}
	k := tpl.Key
	if k.ImageRef != "onyxdotapp/sandbox:v5.1.0" || k.CPUModel != node.CPUModel || k.FirecrackerVersion != "v1.17.0" ||
		k.GuestKernel != "6.18.25" || k.GuestKernelSHA256 != node.GuestKernelSHA256 || k.CAFingerprint != node.CAFingerprint ||
		k.RootfsManifestSHA256 != in.ManifestSHA256 || k.RootfsSHA256 != in.Manifest.Output.SHA256 || k.LayoutVersion != template.LayoutVersion {
		t.Fatalf("key %+v", k)
	}
	if err := tpl.CheckNode(node); err != nil {
		t.Fatal(err)
	}
	// The template is usable at once (Build primed the hash cache) and the
	// files hash to the manifest.
	if err := r.b.Store.Verify(tpl); err != nil {
		t.Fatal(err)
	}
	sums, _ := template.HashFiles(tpl.Dir, template.Files)
	for f, s := range sums {
		if tpl.Files[f] != s {
			t.Errorf("%s: manifest %s, file %s", f, tpl.Files[f], s)
		}
	}
	// Boot: kernel + all drive slots in order; scratch deferred.
	cfg := r.vmm.cfgs[0]
	if !strings.Contains(cfg.BootArgs, DeferArg) || !strings.Contains(cfg.BootArgs, "init=/sbin/craft-init") {
		t.Fatalf("boot args %q", cfg.BootArgs)
	}
	var ids []string
	for _, d := range cfg.Drives {
		ids = append(ids, d.ID)
	}
	if strings.Join(ids, ",") != "rootfs,scratch,managed,upload_a,upload_b,managed_b" || !cfg.Drives[2].ReadOnly || !cfg.Drives[3].ReadOnly ||
		!cfg.Drives[4].ReadOnly || !cfg.Drives[5].ReadOnly || cfg.Drives[1].ReadOnly || !cfg.Drives[0].ReadOnly {
		t.Fatalf("drives %+v", cfg.Drives)
	}
	// The balloon is set at boot (Firecracker accepts it only then), so
	// every restore of the template has it.
	if b := cfg.Balloon; b == nil || !b.FreePageReporting || b.FreePageHinting || b.AmountMiB != 0 || b.StatsIntervalS <= 0 {
		t.Fatalf("balloon %+v", cfg.Balloon)
	}
	if !tpl.HasBalloon() || tpl.LayoutVersion != template.BalloonLayout {
		t.Fatalf("template layout %d, balloon %v", tpl.LayoutVersion, tpl.HasBalloon())
	}
	if r.vmm.killed != 1 || r.slots.freed != 1 || len(r.slots.held) != 0 {
		t.Fatalf("killed %d freed %d held %v", r.vmm.killed, r.slots.freed, r.slots.held)
	}
	// No hard links: not between the input and the template, not in the
	// template, and the stage is gone.
	for _, f := range template.Files {
		if n := nlink(t, tpl.Path(f)); n != 1 {
			t.Errorf("%s has %d links", f, n)
		}
		if st, _ := os.Stat(tpl.Path(f)); st.Mode().Perm() != 0o644 {
			t.Errorf("%s mode %v", f, st.Mode())
		}
	}
	if nlink(t, in.Path) != 1 {
		t.Error("the input root drive got a link")
	}
	if ents, _ := filepath.Glob(filepath.Join(r.b.Store.Dir, ".build-*")); len(ents) != 0 {
		t.Errorf("staging left: %v", ents)
	}

	// Same input again: no build.
	res2, err := r.b.Build(context.Background(), in)
	if err != nil || res2.Built || res2.Template.Version != tpl.Version || r.vmm.boots != 1 {
		t.Fatalf("second build: %+v %v (boots %d)", res2, err, r.vmm.boots)
	}
}

func TestBuildRefusesBadInput(t *testing.T) {
	r := newRig(t)
	ctx := context.Background()
	// The drive does not match its manifest hash.
	in := writeRootfs(t, filepath.Join(r.data, "in"), "root drive", opensslCA)
	if err := os.WriteFile(in.Path, []byte("other drive"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err := r.b.Build(ctx, in)
	if apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE || r.vmm.boots != 0 {
		t.Fatalf("bad drive hash: %v (boots %d)", err, r.vmm.boots)
	}
	// The drive trusts another egress CA.
	other := writeRootfs(t, filepath.Join(r.data, "in2"), "root drive", strings.Repeat("cd", 32))
	_, err = r.b.Build(ctx, other)
	if apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE || !strings.Contains(err.Error(), "egress CA") {
		t.Fatalf("other CA: %v", err)
	}
	if list, _ := r.b.Store.List(); len(list) != 0 {
		t.Fatalf("templates %v", list)
	}
	if ents, _ := filepath.Glob(filepath.Join(r.b.Store.Dir, ".build-*")); len(ents) != 0 {
		t.Errorf("staging left: %v", ents)
	}
}

func TestBuildCleansUpWhenTheGuestIsNotReady(t *testing.T) {
	r := newRig(t)
	r.b.Ready = func(context.Context, string) error { return errors.New("no Health answer") }
	in := writeRootfs(t, filepath.Join(r.data, "in"), "root drive", opensslCA)
	_, err := r.b.Build(context.Background(), in)
	if apierr.ReasonOf(err) != pb.ErrorReason_VMM_FAILED {
		t.Fatalf("got %v", err)
	}
	if r.vmm.killed != 1 || r.slots.freed != 1 {
		t.Fatalf("killed %d freed %d", r.vmm.killed, r.slots.freed)
	}
	if ents, _ := os.ReadDir(r.b.Store.Dir); len(ents) != 0 {
		t.Fatalf("template dir not empty: %v", ents)
	}
}

func TestTamperedTemplateIsBuiltAgain(t *testing.T) {
	r := newRig(t)
	ctx := context.Background()
	in := writeRootfs(t, filepath.Join(r.data, "in"), "root drive", opensslCA)
	res, err := r.b.Build(ctx, in)
	if err != nil {
		t.Fatal(err)
	}
	mem := res.Template.Path(template.MemFile)
	if err := os.WriteFile(mem, []byte("MEM"), 0o644); err != nil {
		t.Fatal(err)
	}
	// While a VM uses it, the agent does not replace it.
	r.slots.inUse = map[string]bool{res.Template.Version: true}
	if _, err := r.b.Build(ctx, in); err == nil {
		t.Fatal("rebuilt a template that a VM uses")
	}
	r.slots.inUse = nil
	res2, err := r.b.Build(ctx, in)
	if err != nil || !res2.Built || res2.Template.Version != res.Template.Version {
		t.Fatalf("rebuild: %+v %v", res2, err)
	}
	if got, _ := os.ReadFile(mem); string(got) != "mem" {
		t.Fatalf("mem after the rebuild: %q", got)
	}
}

func TestIncompleteTemplateIsBuiltAgain(t *testing.T) {
	r := newRig(t)
	ctx := context.Background()
	in := writeRootfs(t, filepath.Join(r.data, "in"), "root drive", opensslCA)
	res, err := r.b.Build(ctx, in)
	if err != nil {
		t.Fatal(err)
	}
	// A data file is gone: Get reports TEMPLATE_MISSING, but the directory
	// is still there and must go before the new build is renamed in.
	if err := os.Remove(res.Template.Path(template.MemFile)); err != nil {
		t.Fatal(err)
	}
	r.slots.inUse = map[string]bool{res.Template.Version: true}
	if _, err := r.b.Build(ctx, in); err == nil {
		t.Fatal("removed an incomplete template that a VM uses")
	}
	r.slots.inUse = nil
	res2, err := r.b.Build(ctx, in)
	if err != nil || !res2.Built || res2.Template.Version != res.Template.Version {
		t.Fatalf("rebuild: %+v %v", res2, err)
	}
	if got, _ := os.ReadFile(res.Template.Path(template.MemFile)); string(got) != "mem" {
		t.Fatalf("mem after the rebuild: %q", got)
	}
}

func TestGCKeepsTwoAndTheOnesInUse(t *testing.T) {
	r := newRig(t)
	ctx := context.Background()
	now := time.Now()
	r.b.Now = func() time.Time { now = now.Add(time.Second); return now }
	var names []string
	for i, data := range []string{"drive one", "drive two", "drive three", "drive four"} {
		in := writeRootfs(t, filepath.Join(r.data, "in", data), data, opensslCA)
		if i == 2 {
			// A VM runs from the first template when the third is built.
			r.slots.inUse = map[string]bool{names[0]: true}
		}
		if i == 3 {
			r.slots.inUse = nil
		}
		res, err := r.b.Build(ctx, in)
		if err != nil {
			t.Fatal(err)
		}
		names = append(names, res.Template.Version)
		list, _ := r.b.Store.List()
		t.Logf("after build %d: %d templates, removed %v", i+1, len(list), res.Removed)
		switch i {
		case 1:
			if len(list) != 2 || len(res.Removed) != 0 {
				t.Fatalf("build 2: kept %d, removed %v", len(list), res.Removed)
			}
		case 2:
			// The 2 newest, plus the oldest because a VM uses it.
			if len(list) != 3 || len(res.Removed) != 0 {
				t.Fatalf("build 3: kept %d, removed %v (want %s kept in use)", len(list), res.Removed, names[0])
			}
		case 3:
			if len(list) != 2 || strings.Join(res.Removed, ",") != names[1]+","+names[0] {
				t.Fatalf("build 4: kept %d, removed %v, want %s,%s", len(list), res.Removed, names[1], names[0])
			}
		}
	}
	for _, n := range names[2:] {
		if _, err := r.b.Store.Get(n); err != nil {
			t.Errorf("%s: %v", n, err)
		}
	}
}

func TestCleanStaging(t *testing.T) {
	r := newRig(t)
	stale := filepath.Join(r.b.Store.Dir, ".build-v5.1.0-0123456789ab")
	if err := os.MkdirAll(stale, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := r.b.CleanStaging(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Fatalf("stale stage: %v", err)
	}
}

func TestLoadRootfsChecksTheDriveOrder(t *testing.T) {
	dir := t.TempDir()
	writeRootfs(t, dir, "x", opensslCA)
	raw, _ := os.ReadFile(filepath.Join(dir, RootfsManifestFile))
	bad := strings.Replace(string(raw), `"drive_id":"managed","is_read_only":true`, `"drive_id":"managed","is_read_only":false`, 1)
	if err := os.WriteFile(filepath.Join(dir, RootfsManifestFile), []byte(bad), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadRootfs(dir); apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE {
		t.Fatalf("writable managed drive: %v", err)
	}
	if _, err := LoadRootfs(t.TempDir()); apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_MISSING {
		t.Fatalf("empty dir: %v", err)
	}
	// Managed slots: the root drive's devices must be the template's
	// managed (vdc) and managed_b (vdf) drives. No managed_slots: an older
	// root drive, accepted.
	for name, c := range map[string]struct {
		from, to string
		ok       bool
	}{
		"slot b moved": {`"b":"/dev/vdf"`, `"b":"/dev/vde"`, false},
		"slot a moved": {`"a":"/dev/vdc"`, `"a":"/dev/vdd"`, false},
		"no slot b":    {`,"b":"/dev/vdf"`, ``, false},
		"no slots":     {`"managed_slots":{"a":"/dev/vdc","b":"/dev/vdf"},`, ``, true},
	} {
		d := t.TempDir()
		writeRootfs(t, d, "x", opensslCA)
		raw, _ := os.ReadFile(filepath.Join(d, RootfsManifestFile))
		edited := strings.Replace(string(raw), c.from, c.to, 1)
		if edited == string(raw) {
			t.Fatalf("%s: edit did not apply to %s", name, raw)
		}
		if err := os.WriteFile(filepath.Join(d, RootfsManifestFile), []byte(edited), 0o644); err != nil {
			t.Fatal(err)
		}
		_, err := LoadRootfs(d)
		if c.ok && err != nil || !c.ok && apierr.ReasonOf(err) != pb.ErrorReason_TEMPLATE_INCOMPATIBLE {
			t.Errorf("%s: %v", name, err)
		}
	}
}

func TestNameAndBootArgs(t *testing.T) {
	key := strings.Repeat("f", 64)
	for ref, want := range map[string]string{
		"onyxdotapp/sandbox:v5.1.0":               "v5.1.0-ffffffffffff",
		"onyxdotapp/sandbox@sha256:40928cdd":      "img-ffffffffffff",
		"registry:5000/sandbox":                   "img-ffffffffffff",
		"registry:5000/sandbox:v5.1.0@sha256:abc": "v5.1.0-ffffffffffff",
		"sandbox:odd+tag":                         "odd-tag-ffffffffffff",
	} {
		if got := Name(ref, key); got != want || !template.ValidVersion(got) {
			t.Errorf("Name(%q) = %q, want %q", ref, got, want)
		}
	}
	r := &Rootfs{}
	r.Manifest.Guest.BootArgs = "console=ttyS0 init=/sbin/craft-init"
	if got := r.BootArgs(); got != "console=ttyS0 init=/sbin/craft-init craft.scratch=defer" {
		t.Errorf("boot args %q", got)
	}
	if NormalizeFingerprint("AB:CD") != "abcd" {
		t.Error("fingerprint")
	}
}
