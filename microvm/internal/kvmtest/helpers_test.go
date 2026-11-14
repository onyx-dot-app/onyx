//go:build kvm && linux

package kvmtest

import (
	"bufio"
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/binaries"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/hostinfo"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/tplbuild"
)

// env holds the test host paths. Override them with environment variables.
type env struct {
	DataDir      string // KVM_DATA_DIR: XFS reflink data dir
	ImgDir       string // KVM_IMG_DIR: vmlinux, rootfs.ext4, scratch-empty.ext4
	ArtifactsDir string // KVM_ARTIFACTS_DIR: firecracker, jailer
	Template     string // set by buildTemplate
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

		VMs: n,
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

// buildTemplate builds the template from the kit rootfs (prototype guest
// agent) with the agent's template pipeline (internal/tplbuild) and sets
// e.Template to its version.
func buildTemplate(t *testing.T, e *env, cmd jailer.Command) {
	t.Helper()
	buildTemplateWith(t, e, cmd, bootArgs, waitPing)
}

// buildTemplateWith is buildTemplate with other boot args and another check
// that the guest is ready for the snapshot. If KVM_IMG_DIR has a
// build-rootfs.sh manifest.json, the build uses it (and its boot args).
func buildTemplateWith(t *testing.T, e *env, cmd jailer.Command, args string, ready func(ctx context.Context, vsockPath string) error) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	v := kvmVersions(t, *e)
	// Only a missing manifest falls back to the kit rootfs. A manifest that
	// LoadRootfs rejects fails the test, as it would fail the agent.
	var rf *tplbuild.Rootfs
	if _, err := os.Stat(filepath.Join(e.ImgDir, tplbuild.RootfsManifestFile)); errors.Is(err, os.ErrNotExist) {
		rf = kitRootfs(t, e.ImgDir, args)
	} else if rf, err = tplbuild.LoadRootfs(e.ImgDir); err != nil {
		t.Fatalf("rootfs manifest in %s: %v", e.ImgDir, err)
	}
	b := &tplbuild.Builder{
		Store: &template.Store{Dir: filepath.Join(e.DataDir, "templates")},
		VMM:   tplbuild.FirecrackerVMM{Launcher: &fcvm.Launcher{Cmd: cmd, Log: slog.Default()}},
		Slots: kvmSlots{}, Node: v.NodeKey(), GuestKernel: v.GuestKernel, KernelPath: kernelPath(t, *e),
		VCPUs: tplVCPUs, MemMiB: tplMemMiB, ScratchGiB: tplScratchGiB, Keep: 4, Ready: ready, Log: slog.Default(),
	}
	res, err := b.Build(ctx, rf)
	if err != nil {
		t.Fatalf("template build: %v", err)
	}
	e.Template = res.Template.Version
	t.Logf("template %s (built %v, %d ms)", e.Template, res.Built, res.BuildMS)
}

// kitRootfs describes a root drive that has no build-rootfs.sh manifest.
func kitRootfs(t *testing.T, imgDir, args string) *tplbuild.Rootfs {
	t.Helper()
	path := filepath.Join(imgDir, "rootfs.ext4")
	sum, err := template.FileSHA256(path)
	if err != nil {
		t.Fatal(err)
	}
	r := &tplbuild.Rootfs{Path: path, ManifestSHA256: sum}
	r.Manifest.SourceImage.Ref = "kit-rootfs"
	r.Manifest.Guest.BootArgs = args
	r.Manifest.Output.File, r.Manifest.Output.SHA256 = "rootfs.ext4", sum
	return r
}

type kvmSlots struct{}

func (kvmSlots) BuildSlot(string, uint32) (uint32, func(bool), error) {
	return 999999, func(bool) {}, nil
}
func (kvmSlots) TemplatesInUse() map[string]bool { return nil }

// kernelPath installs the guest kernel of the artifacts dir like the agent.
func kernelPath(t *testing.T, e env) string {
	t.Helper()
	k, err := binaries.InstallKernel(filepath.Join(e.ArtifactsDir, "vmlinux"), filepath.Join(e.DataDir, "kernel"))
	if err != nil {
		t.Fatal(err)
	}
	return k.Path
}

// kvmVersions are the node versions the agent would use on this host.
func kvmVersions(t *testing.T, e env) agent.Versions {
	t.Helper()
	k, err := binaries.InstallKernel(filepath.Join(e.ArtifactsDir, "vmlinux"), filepath.Join(e.DataDir, "kernel"))
	if err != nil {
		t.Fatal(err)
	}
	return agent.Versions{
		Firecracker: binaries.FirecrackerVersion, HostKernel: hostinfo.KernelRelease(), CPUModel: hostinfo.CPUModel(),
		Agent: "kvmtest", GuestKernel: k.Release, GuestKernelSHA256: k.SHA256,
	}
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

// vsockProbePorts are the guest → host vsock ports that the deny-list checks
// try: common service ports, the daemon port, the Dial default, the ports
// next to the relay port, and the relay port itself.
var vsockProbePorts = []int{1, 22, 52, 80, 443, 1024, 3010, 3127, 3128, 3129, 8080, 10250, 65535}

// vsockProbe connects from the guest (as root) to each port on the host
// (CID 2) and returns the ports that accepted the connection. A port counts
// as refused only on ECONNREFUSED or ECONNRESET (Firecracker resets a connect
// to a port with no host socket); any other error fails the probe.
func vsockProbe(ctx context.Context, vsockPath string, ports []int) (map[int]bool, string, error) {
	list := make([]string, len(ports))
	for i, p := range ports {
		list[i] = strconv.Itoa(p)
	}
	out, err := guestRun(ctx, vsockPath, "root", `python3 - `+strings.Join(list, " ")+` <<'EOF'
import errno, socket, sys
for port in map(int, sys.argv[1:]):
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect((2, port))
        print("VSOCK", port, "OPEN")
    except OSError as e:
        if e.errno in (errno.ECONNREFUSED, errno.ECONNRESET):
            print("VSOCK", port, "REFUSED", errno.errorcode[e.errno])
        else:
            print("VSOCK", port, "ERROR", type(e).__name__, e)
    finally:
        s.close()
EOF`)
	if err == nil && !strings.Contains(out, "EXIT 0") {
		err = fmt.Errorf("probe script failed")
	}
	accepted := map[int]bool{}
	seen := 0
	for _, l := range strings.Split(out, "\n") {
		f := strings.Fields(l)
		if len(f) < 3 || f[0] != "VSOCK" {
			continue
		}
		p, perr := strconv.Atoi(f[1])
		if perr != nil {
			continue
		}
		seen++
		switch f[2] {
		case "OPEN":
			accepted[p] = true
		case "REFUSED":
		default:
			if err == nil {
				err = fmt.Errorf("port %d: %s", p, strings.Join(f[2:], " "))
			}
		}
	}
	if err == nil && seen != len(ports) {
		err = fmt.Errorf("probe reported %d of %d ports", seen, len(ports))
	}
	return accepted, out, err
}

// hostVsockListeners returns the guest-reachable vsock ports of a VM: the
// <v.sock>_<port> sockets in its chroot.
func hostVsockListeners(t *testing.T, vsockPath string) []string {
	t.Helper()
	m, err := filepath.Glob(vsockPath + "_*")
	if err != nil {
		t.Fatal(err)
	}
	for i := range m {
		m[i] = strings.TrimPrefix(m[i], vsockPath+"_")
	}
	return m
}

// netnsOf returns the network namespace of pid and its interface names.
func netnsOf(t *testing.T, pid int) (string, []string) {
	t.Helper()
	ns, err := os.Readlink(fmt.Sprintf("/proc/%d/ns/net", pid))
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(fmt.Sprintf("/proc/%d/net/dev", pid))
	if err != nil {
		t.Fatal(err)
	}
	var ifs []string
	for _, l := range strings.Split(string(raw), "\n") {
		if name, _, ok := strings.Cut(l, ":"); ok {
			ifs = append(ifs, strings.TrimSpace(name))
		}
	}
	return ns, ifs
}
