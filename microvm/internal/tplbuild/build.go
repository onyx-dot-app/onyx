package tplbuild

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// KernelFile is the guest kernel file name in the build VM chroot.
const KernelFile = "vmlinux"

// Placeholder sizes. The managed slot A placeholder is an empty ext4 (attach
// mounts it); the upload slots and managed slot B are never mounted in the
// template. A managed swap puts an image in slot B (PATCH /drives).
const (
	managedBytes = 8 << 20
	uploadBytes  = 1 << 20
)

// File is one file to put in the build VM chroot.
type File struct {
	Name string
	Src  string
}

// BootConfig is the template VM.
type BootConfig struct {
	KernelFile string
	BootArgs   string
	Drives     []template.Drive
	VCPUs      uint32
	MemMiB     uint32
	// Balloon is the balloon device of the template VM; nil: none.
	Balloon *template.BalloonConfig
}

// VM is a running template build VM.
type VM interface {
	// VsockPath is the host path of the VM's vsock UDS.
	VsockPath() string
	// Snapshot pauses the VM and writes a full snapshot. It returns the host
	// paths of the vmstate and memory files.
	Snapshot(ctx context.Context) (vmstate, mem string, err error)
	// Kill stops the VM and removes its chroot.
	Kill(ctx context.Context) error
}

// VMM boots template VMs. The real one is FirecrackerVMM.
type VMM interface {
	// Boot starts VM id with jailer UID uid. Every file is a reflink copy
	// in the chroot.
	Boot(ctx context.Context, id string, uid uint32, files []File, cfg BootConfig) (VM, error)
}

// Slots hands out jailer UIDs and tells which templates VMs use. The real
// one is agent.Manager.
type Slots interface {
	BuildSlot(id string, memMiB uint32) (uint32, func(left bool), error)
	TemplatesInUse() map[string]bool
}

// Ready waits until the guest in the VM is ready for the snapshot.
type Ready func(ctx context.Context, vsockPath string) error

// Mkfs makes an empty ext4 file system of size bytes in a new file.
type Mkfs func(ctx context.Context, path string, size int64, label string) error

// Builder builds and garbage-collects the templates of one node.
type Builder struct {
	Store *template.Store
	VMM   VMM
	Slots Slots
	Node  template.NodeKey
	// GuestKernel is the release of KernelPath, for the key.
	GuestKernel string
	// KernelPath is the guest kernel on the data dir file system.
	KernelPath string
	VCPUs      uint32
	MemMiB     uint32
	ScratchGiB uint32
	// Keep is how many templates GC keeps (plus the ones in use).
	Keep    int
	Ready   Ready
	Mkfs    Mkfs
	Timeout time.Duration
	Log     *slog.Logger
	Now     func() time.Time

	mu sync.Mutex
}

// Result is the output of Build.
type Result struct {
	Template *template.Template
	// Built is false when a valid template for the key was already there.
	Built   bool
	BuildMS int64
	// Removed are the templates that GC removed.
	Removed []string
}

// Key returns the template key for a root drive on this node.
func (b *Builder) Key(r *Rootfs) template.Key {
	return template.Key{
		ImageRef: r.Manifest.SourceImage.Ref, ImageDigest: r.Manifest.SourceImage.Digest,
		RootfsSHA256: r.Manifest.Output.SHA256, RootfsManifestSHA256: r.ManifestSHA256,
		GuestKernel: b.GuestKernel, GuestKernelSHA256: b.Node.GuestKernelSHA256,
		FirecrackerVersion: b.Node.FirecrackerVersion, CPUModel: b.Node.CPUModel, HostKernel: b.Node.HostKernel,
		CAFingerprint: r.CAFingerprint(), LayoutVersion: template.LayoutVersion, BootArgs: r.BootArgs(),
		VCPUs: b.VCPUs, MemMiB: b.MemMiB, ScratchGiB: b.ScratchGiB,
	}
}

func (b *Builder) now() time.Time {
	if b.Now != nil {
		return b.Now()
	}
	return time.Now()
}

// Build makes the template for root drive r, unless a valid one is there,
// and then runs GC. One build runs at a time; other calls wait for it.
func (b *Builder) Build(ctx context.Context, r *Rootfs) (Result, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	// A root drive with no CA fits every deployment: the daemon installs the
	// CA at Init. A root drive with a CA must have this deployment's CA.
	if b.Node.CAFingerprint != "" && r.CAFingerprint() != "" && r.CAFingerprint() != b.Node.CAFingerprint {
		return Result{}, apierr.New(pb.ErrorReason_TEMPLATE_INCOMPATIBLE,
			"the root drive trusts egress CA %s, this deployment uses %s; build the root drive again", r.CAFingerprint(), b.Node.CAFingerprint)
	}
	if b.Node.RootfsCARequired && r.CAFingerprint() == "" {
		return Result{}, apierr.New(pb.ErrorReason_TEMPLATE_INCOMPATIBLE, "%s", template.NoCAError)
	}
	key := b.Key(r)
	name := Name(key.ImageRef, key.Hash())
	res := Result{}
	t, err := b.Store.Get(name)
	if err == nil {
		if err = t.CheckNode(b.Node); err == nil {
			err = b.Store.Verify(t)
		}
		if err == nil {
			res.Template = t
			res.Removed, err = b.gc()
			return res, err
		}
	}
	// An absent template is built. A directory that is there but not a
	// valid template (a missing file too) is removed first, so the new
	// build can take its name.
	exists, existsErr := b.Store.Exists(name)
	if existsErr != nil {
		return Result{}, existsErr
	}
	if exists {
		b.Log.Error("template is not valid; building it again", "template", name, "err", err)
		removed, rmErr := b.Store.RemoveUnused(name, b.Slots.TemplatesInUse)
		if rmErr != nil {
			return Result{}, rmErr
		}
		if !removed {
			return Result{}, fmt.Errorf("template %s is not valid (%w) and a VM uses it", name, err)
		}
	}
	t, ms, err := b.build(ctx, r, key, name)
	if err != nil {
		return Result{}, err
	}
	res.Template, res.Built, res.BuildMS = t, true, ms
	res.Removed, err = b.gc()
	return res, err
}

func (b *Builder) gc() ([]string, error) {
	removed, err := b.Store.GC(b.Keep, b.Slots.TemplatesInUse)
	if len(removed) > 0 {
		b.Log.Info("template GC", "removed", removed, "keep", b.Keep)
	}
	return removed, err
}

// CleanStaging removes the staging directories of builds that did not end
// (an agent that stopped during a build). Call it before the first Build.
func (b *Builder) CleanStaging() error {
	ents, err := os.ReadDir(b.Store.Dir)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	for _, e := range ents {
		if e.IsDir() && strings.HasPrefix(e.Name(), ".build-") {
			if err := os.RemoveAll(filepath.Join(b.Store.Dir, e.Name())); err != nil {
				return err
			}
			b.Log.Warn("removed unfinished template build", "dir", e.Name())
		}
	}
	return nil
}

type phases struct {
	copyMS, bootMS, snapMS, sealMS int64
}

func (b *Builder) build(ctx context.Context, r *Rootfs, key template.Key, name string) (*template.Template, int64, error) {
	timeout := b.Timeout
	if timeout == 0 {
		timeout = 5 * time.Minute
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	t0 := b.now()
	var ph phases
	b.Log.Info("template build started", "template", name, "image", key.ImageRef, "rootfs_sha256", key.RootfsSHA256)

	if err := os.MkdirAll(b.Store.Dir, 0o700); err != nil {
		return nil, 0, err
	}
	stage := filepath.Join(b.Store.Dir, ".build-"+name)
	if err := os.RemoveAll(stage); err != nil {
		return nil, 0, err
	}
	if err := os.Mkdir(stage, 0o755); err != nil {
		return nil, 0, err
	}
	ok := false
	defer func() {
		if !ok {
			_ = os.RemoveAll(stage)
		}
	}()

	// The drive that boots is the copy, so the copy is what gets hashed.
	reflinked, err := scratch.CopyFile(r.Path, filepath.Join(stage, template.RootfsFile))
	if err != nil {
		return nil, 0, fmt.Errorf("copy root drive: %w", err)
	}
	rootSum, err := template.FileSHA256(filepath.Join(stage, template.RootfsFile))
	if err != nil {
		return nil, 0, err
	}
	if rootSum != r.Manifest.Output.SHA256 {
		return nil, 0, apierr.New(pb.ErrorReason_TEMPLATE_INCOMPATIBLE,
			"root drive %s has SHA256 %s, its manifest has %s", r.Path, rootSum, r.Manifest.Output.SHA256)
	}
	mkfs := b.Mkfs
	if mkfs == nil {
		mkfs = MkfsExt4
	}
	if err := mkfs(ctx, filepath.Join(stage, template.ScratchFile), int64(b.ScratchGiB)*scratch.GiB, "scratch"); err != nil {
		return nil, 0, fmt.Errorf("scratch drive: %w", err)
	}
	// Slot A of each managed mount is an empty ext4 that the guest mounts at
	// boot; slot B and the upload slots are sparse placeholders.
	slotA := map[string]bool{}
	for _, m := range template.ManagedMountDrives {
		slotA[m.A.File] = true
	}
	for _, d := range template.Drives[2:] {
		if slotA[d.File] {
			if err := mkfs(ctx, filepath.Join(stage, d.File), managedBytes, "managed"); err != nil {
				return nil, 0, fmt.Errorf("managed drive %s: %w", d.ID, err)
			}
			continue
		}
		if err := sparseFile(filepath.Join(stage, d.File), uploadBytes); err != nil {
			return nil, 0, err
		}
	}
	ph.copyMS = b.now().Sub(t0).Milliseconds()

	files := []File{{Name: KernelFile, Src: b.KernelPath}}
	for _, d := range template.Drives {
		files = append(files, File{Name: d.File, Src: filepath.Join(stage, d.File)})
	}
	id := "tpl-" + key.Hash()[:12]
	uid, done, err := b.Slots.BuildSlot(id, b.MemMiB)
	if err != nil {
		return nil, 0, err
	}
	left := false
	defer func() { done(left) }()
	t1 := b.now()
	vm, err := b.VMM.Boot(ctx, id, uid, files, BootConfig{
		KernelFile: KernelFile, BootArgs: key.BootArgs, Drives: template.Drives, VCPUs: b.VCPUs, MemMiB: b.MemMiB,
		Balloon: template.BalloonFor(template.LayoutVersion),
	})
	if err != nil {
		left = errors.Is(err, ErrVMLeft)
		return nil, 0, apierr.New(pb.ErrorReason_VMM_FAILED, "boot template VM: %v", err)
	}
	kill := func() {
		kctx, kcancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
		defer kcancel()
		if err := vm.Kill(kctx); err != nil {
			left = true
			b.Log.Error("kill template VM", "id", id, "err", err)
		}
	}
	killed := false
	defer func() {
		if !killed {
			kill()
		}
	}()
	if err := b.Ready(ctx, vm.VsockPath()); err != nil {
		return nil, 0, apierr.New(pb.ErrorReason_VMM_FAILED, "template VM: guest not ready: %v", err)
	}
	t2 := b.now()
	ph.bootMS = t2.Sub(t1).Milliseconds()
	vmstate, mem, err := vm.Snapshot(ctx)
	if err != nil {
		return nil, 0, apierr.New(pb.ErrorReason_VMM_FAILED, "template VM snapshot: %v", err)
	}
	// Move the snapshot out before Kill removes the chroot.
	for src, f := range map[string]string{vmstate: template.VMStateFile, mem: template.MemFile} {
		dst := filepath.Join(stage, f)
		if err := os.Rename(src, dst); err != nil {
			return nil, 0, err
		}
		// Owned by the agent (root), like every template file.
		if err := os.Chown(dst, os.Geteuid(), os.Getegid()); err != nil {
			return nil, 0, err
		}
		if err := os.Chmod(dst, 0o644); err != nil {
			return nil, 0, err
		}
	}
	killed = true
	kill()
	t3 := b.now()
	ph.snapMS = t3.Sub(t2).Milliseconds()
	// The guest never mounted scratch or managed (DeferArg), so the staged
	// files are the ones it saw at snapshot time.
	for _, f := range template.Files {
		if err := os.Chmod(filepath.Join(stage, f), 0o644); err != nil {
			return nil, 0, err
		}
	}
	m := template.Manifest{Version: name, Key: key, BuiltAt: b.now().UTC()}
	m.BuildMS = b.now().Sub(t0).Milliseconds()
	m, prints, err := template.Seal(stage, m, map[string]string{template.RootfsFile: rootSum})
	if err != nil {
		return nil, 0, err
	}
	if err := syncDir(stage); err != nil {
		return nil, 0, err
	}
	final := filepath.Join(b.Store.Dir, name)
	if err := os.Rename(stage, final); err != nil {
		return nil, 0, err
	}
	ok = true
	if err := syncDir(b.Store.Dir); err != nil {
		return nil, 0, err
	}
	t, err := b.Store.Get(name)
	if err != nil {
		return nil, 0, err
	}
	if err := b.Store.MarkVerified(t, prints); err != nil {
		return nil, 0, err
	}
	ph.sealMS = b.now().Sub(t3).Milliseconds()
	total := b.now().Sub(t0).Milliseconds()
	b.Log.Info("template built", "template", name, "ms", total, "prepare_ms", ph.copyMS, "boot_to_ready_ms", ph.bootMS,
		"snapshot_ms", ph.snapMS, "hash_ms", ph.sealMS, "rootfs_reflink", reflinked, "snapshot_sha256", m.SnapshotSHA256)
	return t, total, nil
}

// ErrVMLeft marks a failed boot whose Firecracker process may still run.
var ErrVMLeft = errors.New("the template VM may still run")

// MkfsExt4 runs mkfs.ext4 on a new sparse file.
func MkfsExt4(ctx context.Context, path string, size int64, label string) error {
	if err := sparseFile(path, size); err != nil {
		return err
	}
	out, err := exec.CommandContext(ctx, "mkfs.ext4", "-q", "-F", "-L", label, path).CombinedOutput()
	if err != nil {
		_ = os.Remove(path)
		return fmt.Errorf("mkfs.ext4 %s: %v: %s", path, err, strings.TrimSpace(string(out)))
	}
	return nil
}

func sparseFile(path string, size int64) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		return err
	}
	if err := f.Truncate(size); err != nil {
		_ = f.Close()
		return err
	}
	return f.Close()
}

func syncDir(dir string) error {
	d, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer func() { _ = d.Close() }()
	return d.Sync()
}
