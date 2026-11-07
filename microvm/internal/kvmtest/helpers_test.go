//go:build kvm && linux

package kvmtest

import (
	"bufio"
	"context"
	"encoding/base64"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/binaries"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcapi/client/operations"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcapi/models"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
)

// env holds the test host paths. Override them with environment variables.
type env struct {
	DataDir      string // KVM_DATA_DIR: XFS reflink data dir
	ImgDir       string // KVM_IMG_DIR: vmlinux, rootfs.ext4, scratch-empty.ext4
	ArtifactsDir string // KVM_ARTIFACTS_DIR: firecracker, jailer
	Template     string // KVM_TEMPLATE: template version to build or use
	VMs          int    // KVM_VMS: number of VMs
}

func loadEnv() env {
	get := func(k, def string) string {
		if v := os.Getenv(k); v != "" {
			return v
		}
		return def
	}
	n := 20
	if v := os.Getenv("KVM_VMS"); v != "" {
		_, _ = fmt.Sscanf(v, "%d", &n)
	}
	return env{
		DataDir:      get("KVM_DATA_DIR", "/var/lib/craft-fc"),
		ImgDir:       get("KVM_IMG_DIR", "/opt/craft-fc-test/img"),
		ArtifactsDir: get("KVM_ARTIFACTS_DIR", "/opt/craft-fc"),
		Template:     get("KVM_TEMPLATE", "kvmtest-1"),
		VMs:          n,
	}
}

const (
	tplVCPUs      = 2
	tplMemMiB     = 4096
	tplScratchGiB = 1
	bootArgs      = "console=ttyS0 reboot=k panic=1 pci=off init=/sbin/fc-init fcroot=rw"
	agentPort     = 52
)

func newCommand(t *testing.T, e env) jailer.Command {
	t.Helper()
	for _, d := range []string{"templates", "jail", "bin", "run"} {
		if err := os.MkdirAll(filepath.Join(e.DataDir, d), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Chmod(filepath.Join(e.DataDir, "jail"), 0o711); err != nil {
		t.Fatal(err)
	}
	bins, err := binaries.Install(e.ArtifactsDir, filepath.Join(e.DataDir, "bin"),
		binaries.FirecrackerVersion, binaries.FirecrackerSHA256, binaries.JailerSHA256)
	if err != nil {
		t.Fatal(err)
	}
	return jailer.Command{
		JailerBin: bins.Jailer, FirecrackerBin: bins.Firecracker,
		Layout: jailer.Layout{ChrootBase: filepath.Join(e.DataDir, "jail")},
		Slice:  "fcvms.slice", HostMountNS: true, LogLevel: "Warning",
	}
}

// buildTemplate boots the kit rootfs with the prototype guest agent under the
// jailer, then snapshots it into <data>/templates/<version>. It is the test
// stand-in for the template pipeline (ENG-4566).
func buildTemplate(t *testing.T, e env, cmd jailer.Command) {
	t.Helper()
	buildTemplateWith(t, e, cmd, bootArgs, waitPing)
}

// buildTemplateWith is buildTemplate with other boot args and another check
// that the guest is ready for the snapshot.
func buildTemplateWith(t *testing.T, e env, cmd jailer.Command, args string, ready func(ctx context.Context, vsockPath string) error) {
	t.Helper()
	store := &template.Store{Dir: filepath.Join(e.DataDir, "templates")}
	if _, err := store.Get(e.Template); err == nil {
		t.Logf("template %s already built", e.Template)
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	defer cancel()
	l := &fcvm.Launcher{Cmd: cmd, Log: slog.Default()}
	id := "tpl-" + strings.ReplaceAll(e.Template, ".", "-")
	const uid = 999999
	p, err := l.Spawn(ctx, id, uid, []fcvm.FileSource{
		{Name: "vmlinux", Src: filepath.Join(e.ImgDir, "vmlinux"), Link: true},
		{Name: template.RootfsFile, Src: filepath.Join(e.ImgDir, "rootfs.ext4"), Link: true},
		{Name: template.ScratchFile, Src: filepath.Join(e.ImgDir, "scratch-empty.ext4")},
	})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = p.Kill(context.Background()) }()
	api := p.API()
	must := func(what string, err error) {
		if err != nil {
			t.Fatalf("%s: %v (console: %s)", what, err, readTail(cmd.Layout.ConsoleLog(id)))
		}
	}
	kernel := "/vmlinux"
	_, err = api.PutGuestBootSourceContext(ctx, &operations.PutGuestBootSourceParams{Body: &models.BootSource{KernelImagePath: &kernel, BootArgs: args}})
	must("boot source", err)
	for _, d := range []struct {
		id   string
		root bool
		ro   bool
	}{{template.RootfsDriveID, true, true}, {template.ScratchDriveID, false, false}} {
		driveID, root, path := d.id, d.root, "/"+map[string]string{template.RootfsDriveID: template.RootfsFile, template.ScratchDriveID: template.ScratchFile}[d.id]
		_, err = api.PutGuestDriveByIDContext(ctx, &operations.PutGuestDriveByIDParams{
			DriveID: driveID, Body: &models.Drive{DriveID: &driveID, IsRootDevice: &root, IsReadOnly: d.ro, PathOnHost: path},
		})
		must("drive "+driveID, err)
	}
	vcpus, mem := int64(tplVCPUs), int64(tplMemMiB)
	_, err = api.PutMachineConfigurationContext(ctx, &operations.PutMachineConfigurationParams{Body: &models.MachineConfiguration{VcpuCount: &vcpus, MemSizeMib: &mem}})
	must("machine config", err)
	cid, uds := int64(template.GuestCID), template.VsockUDS
	_, err = api.PutGuestVsockContext(ctx, &operations.PutGuestVsockParams{Body: &models.Vsock{GuestCid: &cid, UdsPath: &uds}})
	must("vsock", err)
	start := models.InstanceActionInfoActionTypeInstanceStart
	_, err = api.CreateSyncActionContext(ctx, &operations.CreateSyncActionParams{Info: &models.InstanceActionInfo{ActionType: &start}})
	must("start", err)
	vsockPath := cmd.Layout.HostPath(id, template.VsockUDS)
	must("guest ready", ready(ctx, vsockPath))
	paused := models.VMStatePaused
	_, err = api.PatchVMContext(ctx, &operations.PatchVMParams{Body: &models.VM{State: &paused}})
	must("pause", err)
	snapPath, memPath := "/"+template.VMStateFile, "/"+template.MemFile
	_, err = api.CreateSnapshotContext(ctx, &operations.CreateSnapshotParams{Body: &models.SnapshotCreateParams{
		SnapshotType: models.SnapshotCreateParamsSnapshotTypeFull, SnapshotPath: &snapPath, MemFilePath: &memPath,
	}})
	must("snapshot", err)

	tmp := filepath.Join(store.Dir, "."+e.Template+".tmp")
	_ = os.RemoveAll(tmp)
	if err := os.MkdirAll(tmp, 0o755); err != nil {
		t.Fatal(err)
	}
	root := cmd.Layout.RootDir(id)
	for _, f := range []string{template.VMStateFile, template.MemFile} {
		if err := os.Rename(filepath.Join(root, f), filepath.Join(tmp, f)); err != nil {
			t.Fatal(err)
		}
	}
	if err := scratch.Prepare(filepath.Join(root, template.ScratchFile), filepath.Join(tmp, template.ScratchFile), int64(tplScratchGiB)*scratch.GiB, 0, 0); err != nil {
		t.Fatal(err)
	}
	if err := os.Link(filepath.Join(e.ImgDir, "rootfs.ext4"), filepath.Join(tmp, template.RootfsFile)); err != nil {
		t.Fatal(err)
	}
	// Template files are shared read-only by every VM (each with its own UID).
	for _, f := range []string{template.VMStateFile, template.MemFile, template.ScratchFile} {
		if err := os.Chown(filepath.Join(tmp, f), 0, 0); err != nil {
			t.Fatal(err)
		}
		if err := os.Chmod(filepath.Join(tmp, f), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := template.WriteManifest(tmp, template.Manifest{
		Version: e.Template, VCPUs: tplVCPUs, MemMiB: tplMemMiB, ScratchGiB: tplScratchGiB,
		GuestKernel: "6.18.25", FirecrackerVersion: binaries.FirecrackerVersion,
	}); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(tmp, filepath.Join(store.Dir, e.Template)); err != nil {
		t.Fatal(err)
	}
	t.Logf("template %s built", e.Template)
}

// guestCmd sends one prototype guest agent command and returns the reply.
func guestCmd(ctx context.Context, vsockPath, line string) (string, error) {
	c, err := fcvm.DialVsock(ctx, vsockPath, agentPort)
	if err != nil {
		return "", err
	}
	defer func() { _ = c.Close() }()
	if dl, ok := ctx.Deadline(); ok {
		_ = c.SetDeadline(dl)
	}
	if _, err := io.WriteString(c, line+"\n"); err != nil {
		return "", err
	}
	out, err := io.ReadAll(bufio.NewReader(c))
	return string(out), err
}

func guestRun(ctx context.Context, vsockPath, verb, script string) (string, error) {
	return guestCmd(ctx, vsockPath, verb+" "+base64.StdEncoding.EncodeToString([]byte(script)))
}

func waitPing(ctx context.Context, vsockPath string) error {
	for {
		pctx, cancel := context.WithTimeout(ctx, 2*time.Second)
		out, err := guestCmd(pctx, vsockPath, "ping")
		cancel()
		if err == nil && strings.TrimSpace(out) == "pong" {
			return nil
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("guest agent did not answer ping: %v (%q)", err, out)
		case <-time.After(5 * time.Millisecond):
		}
	}
}

func readTail(path string) string {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err.Error()
	}
	if len(raw) > 3000 {
		raw = raw[len(raw)-3000:]
	}
	return string(raw)
}

func scopeActive(cmd jailer.Command, id string) string {
	argv := cmd.SystemctlArgv("is-active", jailer.ScopeUnit(id))
	out, _ := exec.Command(argv[0], argv[1:]...).Output()
	return strings.TrimSpace(string(out))
}
