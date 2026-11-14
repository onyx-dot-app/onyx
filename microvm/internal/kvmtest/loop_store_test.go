//go:build kvm && linux

package kvmtest

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/unix"

	"github.com/onyx-dot-app/onyx/microvm/internal/loopstore"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

const (
	xfsMagic  = 0x58465342
	ext4Magic = 0xef53
)

func fsMagic(t *testing.T, path string) int64 {
	t.Helper()
	var s unix.Statfs_t
	if err := unix.Statfs(path, &s); err != nil {
		t.Fatal(err)
	}
	return s.Type
}

func run(t *testing.T, argv ...string) {
	t.Helper()
	if out, err := exec.Command(argv[0], argv[1:]...).CombinedOutput(); err != nil {
		t.Fatalf("%s: %v: %s", strings.Join(argv, " "), err, out)
	}
}

// startLoopAgent runs the agent binary like the DaemonSet: privileged, host
// PID and cgroup namespaces, the data dir as a bind mount with the default
// (private) propagation. KVM_AGENT_IMAGE (any entrypoint) needs mkfs.xfs.
func startLoopAgent(t *testing.T, e env, name, certDir string, certs *testcerts.Set) {
	t.Helper()
	bin := getenv("KVM_AGENT_BIN", "/opt/agent/host-agent")
	image := getenv("KVM_AGENT_IMAGE", "debian:trixie-slim")
	run(t, "docker", "run", "-d", "--name", name, "--privileged", "--pid=host", "--cgroupns=host", "--network=host",
		"-v", e.DataDir+":"+e.DataDir,
		"-v", e.ArtifactsDir+":"+e.ArtifactsDir+":ro",
		"-v", filepath.Dir(bin)+":"+filepath.Dir(bin)+":ro",
		"-v", certDir+":"+certDir+":ro",
		"-v", "/sys/fs/cgroup:/sys/fs/cgroup",
		"--entrypoint", bin, image, "--data-dir", e.DataDir, "--artifacts-dir", e.ArtifactsDir, "--egress-ca", certs.ClientCA,
		"--rootfs-dir", filepath.Join(e.DataDir, "rootfs"), "--image-gc-interval=0")
}

func storeLog(t *testing.T, name string) string {
	t.Helper()
	for _, line := range strings.Split(containerLogs(name), "\n") {
		if strings.Contains(line, "data dir is a loop store") {
			return line
		}
	}
	t.Fatalf("%s did not log a loop store; logs:\n%s", name, containerLogs(name))
	return ""
}

// TestLoopStoreKVM runs the agent on an ext4 data dir (like the GKE COS and
// AKS Ubuntu node roots). The agent makes a sparse XFS loop store, mounts it
// at the data dir on the host and in its container, and copies in the root
// drive that the init container put on ext4. VMs clone the template there.
// After an agent restart it adopts the VMs on the same store. After a
// "reboot" (VMs killed, store unmounted) it mounts the same image again, with
// the journal and templates in place.
//
// KVM_LOOP_DATA_DIR (default /mnt/fcext4/craft-fc) must be a short path; its
// parent becomes an ext4 mount of a sparse image in KVM_LOOP_WORK (default
// /var/tmp).
func TestLoopStoreKVM(t *testing.T) {
	e := loadEnv()
	e.DataDir = getenv("KVM_LOOP_DATA_DIR", "/mnt/fcext4/craft-fc")
	ext4Dir := filepath.Dir(e.DataDir)
	ext4Img := filepath.Join(getenv("KVM_LOOP_WORK", "/var/tmp"), "craft-fc-loop-ext4.img")
	names := []string{"ls1", "ls2", "ls3"}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Minute)
	defer cancel()

	// killVMs kills every VM scope, as a node reboot does. The tests of this
	// package run one at a time, so all fcvm scopes are this test's.
	killVMs := func() {
		_ = exec.Command("systemctl", "kill", "--signal=KILL", "fcvm-*.scope").Run()
		for deadline := time.Now().Add(15 * time.Second); time.Now().Before(deadline); time.Sleep(100 * time.Millisecond) {
			if out, _ := exec.Command("pgrep", "-x", "firecracker").Output(); len(strings.TrimSpace(string(out))) == 0 {
				return
			}
		}
	}
	// unmountStore unmounts every mount at the data dir in the host mount
	// namespace (the loop store), like a node reboot.
	unmountStore := func() error {
		for range 4 {
			var st unix.Statfs_t
			if err := unix.Statfs(e.DataDir, &st); err != nil || st.Type != xfsMagic {
				return nil
			}
			if out, err := exec.Command("umount", e.DataDir).CombinedOutput(); err != nil {
				return fmt.Errorf("umount %s: %v: %s", e.DataDir, err, out)
			}
		}
		return fmt.Errorf("%s is still XFS", e.DataDir)
	}
	cleanup := func() {
		_ = exec.Command("docker", append([]string{"rm", "-f"}, names...)...).Run()
		killVMs()
		_ = unmountStore()
		_ = exec.Command("umount", ext4Dir).Run()
		_ = os.Remove(ext4Img)
	}
	cleanup()
	// The test mounts over ext4Dir: never over a directory in use.
	if ents, err := os.ReadDir(ext4Dir); err == nil && len(ents) > 0 {
		t.Fatalf("%s is not empty; set KVM_LOOP_DATA_DIR to <new dir>/<name>", ext4Dir)
	}
	t.Cleanup(cleanup)

	// 1. The node file system: ext4, no reflink.
	if err := os.MkdirAll(ext4Dir, 0o755); err != nil {
		t.Fatal(err)
	}
	run(t, "truncate", "-s", "64G", ext4Img)
	run(t, "mkfs.ext4", "-q", "-F", ext4Img)
	run(t, "mount", "-o", "loop", ext4Img, ext4Dir)
	if err := os.MkdirAll(e.DataDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := scratch.ProbeReflink(e.DataDir); err == nil {
		t.Fatal("the ext4 data dir has reflink")
	}
	// The init container's root drive, on ext4 before the store exists. The
	// agent cannot build from it (not a real manifest); it only copies it.
	lowerDrive := filepath.Join(e.DataDir, "rootfs")
	if err := os.MkdirAll(lowerDrive, 0o755); err != nil {
		t.Fatal(err)
	}
	const manifest = `{"kvmtest":"loop store"}`
	if err := os.WriteFile(filepath.Join(lowerDrive, "manifest.json"), []byte(manifest), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(lowerDrive, "rootfs.ext4"), []byte("drive"), 0o644); err != nil {
		t.Fatal(err)
	}
	certDir := filepath.Join(ext4Dir, "certs")
	if err := os.MkdirAll(certDir, 0o700); err != nil {
		t.Fatal(err)
	}
	certs, err := testcerts.Write(certDir)
	if err != nil {
		t.Fatal(err)
	}

	// 2. First start: the agent makes and mounts the store.
	t0 := time.Now()
	startLoopAgent(t, e, "ls1", certDir, certs)
	c := dialAgent(t, ctx, e, "ls1")
	line := storeLog(t, "ls1")
	t.Logf("first start: %d ms; %s", time.Since(t0).Milliseconds(), line)
	if !strings.Contains(line, `"created":true`) {
		t.Fatalf("first start did not make the image: %s", line)
	}
	// The free space check also sees the ext4 file system under the store.
	if strings.Contains(line, `"node_dir":""`) {
		t.Errorf("the agent does not see the node file system: %s", line)
	}
	// The host (the VMs' mount namespace) sees XFS with reflink.
	if fsMagic(t, e.DataDir) != xfsMagic {
		t.Fatalf("host view of %s is not XFS", e.DataDir)
	}
	if err := scratch.ProbeReflink(e.DataDir); err != nil {
		t.Fatalf("host view of the store: %v", err)
	}
	if got, err := os.ReadFile(filepath.Join(e.DataDir, "rootfs", "manifest.json")); err != nil || string(got) != manifest {
		t.Fatalf("root drive not copied into the store: %q %v", got, err)
	}
	out, _ := exec.Command("findmnt", "-n", "-o", "SOURCE,FSTYPE,OPTIONS", e.DataDir).CombinedOutput()
	t.Logf("host mount: %s", strings.TrimSpace(string(out)))

	// 3. Template build and VMs on the store: each VM is a reflink clone.
	cmd := newCommand(t, e)
	buildTemplate(t, &e, cmd)
	lay := cmd.Layout
	n := min(e.VMs, 4)
	ids := make([]string, n)
	vms := make([]*pb.VM, n)
	for i := range ids {
		ids[i] = newUUID()
		r, err := c.Create(ctx, &pb.CreateRequest{SandboxId: ids[i], Attempt: 1, Template: e.Template, Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public"})
		if err != nil {
			t.Fatalf("create %d: %v; logs:\n%s", i, err, containerLogs("ls1"))
		}
		vms[i] = r.GetVm()
		if out, err := guestRun(ctx, lay.HostPath(ids[i], template.VsockUDS), "run", "echo ok"); err != nil || !strings.HasPrefix(out, "ok") {
			t.Fatalf("run in vm %d: %q %v", i, out, err)
		}
	}
	t.Logf("%d VMs on the loop store", n)

	// 4. Agent restart: same store (not made again), VMs adopted.
	run(t, "docker", "stop", "-t", "10", "ls1")
	_ = exec.Command("docker", "rm", "ls1").Run()
	startLoopAgent(t, e, "ls2", certDir, certs)
	c = dialAgent(t, ctx, e, "ls2")
	if line := storeLog(t, "ls2"); !strings.Contains(line, `"created":false`) {
		t.Fatalf("restart made a new image: %s", line)
	}
	l, err := c.List(ctx, &pb.ListRequest{})
	if err != nil {
		t.Fatal(err)
	}
	byID := map[string]*pb.VM{}
	for _, vm := range l.GetVms() {
		byID[vm.GetSandboxId()] = vm
	}
	for i := range ids {
		got := byID[ids[i]]
		if got == nil || got.GetState() != pb.VMState_VM_STATE_RUNNING || got.GetPid() != vms[i].GetPid() {
			t.Fatalf("vm %d not adopted after the agent restart: %v", i, got)
		}
		if out, err := guestRun(ctx, lay.HostPath(ids[i], template.VsockUDS), "run", "echo ok"); err != nil || !strings.HasPrefix(out, "ok") {
			t.Fatalf("run in adopted vm %d: %q %v", i, out, err)
		}
	}
	t.Logf("agent restart: %d/%d VMs adopted", n, n)
	if _, err := c.Stop(ctx, &pb.StopRequest{SandboxId: ids[0], Attempt: 1, Generation: vms[0].GetGeneration()}); err != nil {
		t.Fatalf("stop: %v", err)
	}

	// 5. Node reboot: the VMs die, the mount and the loop device go away.
	_ = exec.Command("docker", "rm", "-f", "ls2").Run()
	killVMs()
	if err := unmountStore(); err != nil {
		t.Fatal(err)
	}
	if fsMagic(t, e.DataDir) != ext4Magic {
		t.Fatalf("%s is not ext4 after the unmount", e.DataDir)
	}
	if _, err := os.Stat(filepath.Join(e.DataDir, loopstore.ImageName)); err != nil {
		t.Fatalf("store image after the unmount: %v", err)
	}
	startLoopAgent(t, e, "ls3", certDir, certs)
	c = dialAgent(t, ctx, e, "ls3")
	if line := storeLog(t, "ls3"); !strings.Contains(line, `"created":false`) {
		t.Fatalf("reboot made a new image: %s", line)
	}
	for _, line := range strings.Split(containerLogs("ls3"), "\n") {
		if strings.Contains(line, "recovered VMs") {
			t.Logf("after reboot: %s", line)
		}
	}
	for i := 1; i < n; i++ {
		if _, err := os.Stat(filepath.Join(e.DataDir, "journal", ids[i]+".json")); err != nil {
			t.Logf("journal record of vm %d after reboot: %v", i, err)
		}
	}
	l, err = c.List(ctx, &pb.ListRequest{})
	if err != nil {
		t.Fatal(err)
	}
	for _, vm := range l.GetVms() {
		if vm.GetState() == pb.VMState_VM_STATE_RUNNING {
			t.Fatalf("a killed VM is listed as running after the reboot: %v", vm)
		}
	}
	// The template is still on the store, and a new VM clones it.
	id := newUUID()
	r, err := c.Create(ctx, &pb.CreateRequest{SandboxId: id, Attempt: 1, Template: e.Template, Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public"})
	if err != nil {
		t.Fatalf("create after reboot: %v; logs:\n%s", err, containerLogs("ls3"))
	}
	if out, err := guestRun(ctx, lay.HostPath(id, template.VsockUDS), "run", "echo ok"); err != nil || !strings.HasPrefix(out, "ok") {
		t.Fatalf("run after reboot: %q %v", out, err)
	}
	if _, err := c.Stop(ctx, &pb.StopRequest{SandboxId: id, Attempt: 1, Generation: r.GetVm().GetGeneration()}); err != nil {
		t.Fatalf("stop after reboot: %v", err)
	}
	if logs := containerLogs("ls3"); !strings.Contains(logs, "loop store trimmed") {
		t.Errorf("no trim at start; logs:\n%s", logs)
	}
	t.Logf("after reboot: same image mounted again, template %s kept, new VM ran", e.Template)
}
