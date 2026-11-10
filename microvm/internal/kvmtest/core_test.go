//go:build kvm && linux

package kvmtest

import (
	"context"
	"crypto/rand"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/binaries"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/hostinfo"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/server"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

const (
	uidBase    = 1000000
	scratchGiB = 2
)

func newUUID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// startAgent runs the agent in this process on a Unix socket and returns a client.
func startAgent(t *testing.T, e env, cmd jailer.Command) pb.HostAgentClient {
	t.Helper()
	uids, err := jailer.NewUIDPool(uidBase, 65536)
	if err != nil {
		t.Fatal(err)
	}
	log := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelWarn}))
	m := agent.NewManager(agent.Config{
		MinFreeMemMiB: 2048, MinFreeDiskBytes: 10 * uint64(scratch.GiB), MaxScratchGiB: 100,
		StartTimeout: 60 * time.Second, StopTimeout: 30 * time.Second, TombstoneTTL: time.Hour,
	},
		&template.Store{Dir: filepath.Join(e.DataDir, "templates")},
		&fcvm.Launcher{Cmd: cmd, Log: log},
		hostinfo.Stats{DataDir: e.DataDir},
		uids,
		agent.Versions{Firecracker: binaries.FirecrackerVersion, HostKernel: hostinfo.KernelRelease(), CPUModel: hostinfo.CPUModel(), Agent: "kvmtest"},
		log,
	)
	sock := filepath.Join(e.DataDir, "run", "kvmtest.sock")
	ln, err := server.ListenUnix(sock)
	if err != nil {
		t.Fatal(err)
	}
	srv := server.New(m)
	go func() { _ = srv.Serve(ln) }()
	t.Cleanup(srv.Stop)
	conn, err := grpc.NewClient("unix://"+sock, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	return pb.NewHostAgentClient(conn)
}

func wantReason(t *testing.T, what string, err error, want pb.ErrorReason) {
	t.Helper()
	if got := apierr.FromStatus(err); got != want {
		t.Errorf("%s: reason %s, want %s (err %v)", what, got, want, err)
	} else {
		t.Logf("%s: %s OK (%v)", what, want, err)
	}
}

func pct(ms []float64, p float64) float64 {
	s := append([]float64(nil), ms...)
	sort.Float64s(s)
	return s[min(len(s)-1, int(float64(len(s))*p))]
}

func TestCoreKVM(t *testing.T) {
	e := loadEnv()
	cmd := newCommand(t, e)
	buildTemplate(t, e, cmd)
	c := startAgent(t, e, cmd)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	lay := cmd.Layout

	ni, err := c.NodeInfo(ctx, &pb.NodeInfoRequest{})
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("NodeInfo: %v", ni)
	if len(ni.GetTemplates()) == 0 || ni.GetFirecrackerVersion() != binaries.FirecrackerVersion {
		t.Fatalf("NodeInfo has no template or a wrong Firecracker version")
	}

	// 1. Start N VMs at once.
	req := func(id string, attempt uint64) *pb.CreateRequest {
		return &pb.CreateRequest{SandboxId: id, Attempt: attempt, Template: e.Template, Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public"}
	}
	ids := make([]string, e.VMs)
	vms := make([]*pb.VM, e.VMs)
	lat := make([]float64, e.VMs)
	var wg sync.WaitGroup
	errs := make([]error, e.VMs)
	t0 := time.Now()
	for i := range ids {
		ids[i] = newUUID()
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			s := time.Now()
			r, err := c.Create(ctx, req(ids[i], 1))
			lat[i] = float64(time.Since(s).Milliseconds())
			errs[i] = err
			if err == nil {
				vms[i] = r.GetVm()
			}
		}(i)
	}
	wg.Wait()
	wall := time.Since(t0)
	for i, err := range errs {
		if err != nil {
			t.Fatalf("create %d: %v", i, err)
		}
	}
	t.Logf("BENCH create_n=%d wall_ms=%d p50_ms=%.0f p95_ms=%.0f max_ms=%.0f", e.VMs, wall.Milliseconds(), pct(lat, 0.5), pct(lat, 0.95), pct(lat, 1))

	// 2. Same attempt again returns the same VM.
	for i, id := range ids {
		r, err := c.Create(ctx, req(id, 1))
		if err != nil {
			t.Fatalf("repeat create %d: %v", i, err)
		}
		if r.GetCreated() || r.GetVm().GetGeneration() != vms[i].GetGeneration() || r.GetVm().GetPid() != vms[i].GetPid() {
			t.Fatalf("repeat create %d returned a different VM: %v vs %v", i, r.GetVm(), vms[i])
		}
	}
	t.Logf("repeat Create: %d/%d returned the same generation and PID", e.VMs, e.VMs)

	// 3. Typed errors.
	_, err = c.Create(ctx, req(ids[0], 2))
	wantReason(t, "new attempt while running", err, pb.ErrorReason_ATTEMPT_CONFLICT)
	bad := req(newUUID(), 1)
	bad.MemMib = 2048
	_, err = c.Create(ctx, bad)
	wantReason(t, "shape mismatch", err, pb.ErrorReason_TEMPLATE_SHAPE_MISMATCH)
	bad = req(newUUID(), 1)
	bad.Template = "no-such-template"
	_, err = c.Create(ctx, bad)
	wantReason(t, "missing template", err, pb.ErrorReason_TEMPLATE_MISSING)
	bad = req(newUUID(), 1)
	bad.ScratchGib = 0
	_, err = c.Create(ctx, bad)
	wantReason(t, "scratch below template", err, pb.ErrorReason_SCRATCH_TOO_SMALL)
	_, err = c.Stop(ctx, &pb.StopRequest{SandboxId: ids[0], Attempt: 1, Generation: vms[0].GetGeneration() + 1})
	wantReason(t, "stop with wrong generation", err, pb.ErrorReason_INSTANCE_MISMATCH)
	_, err = c.Stop(ctx, &pb.StopRequest{SandboxId: ids[0], Attempt: 2, Generation: vms[0].GetGeneration()})
	wantReason(t, "stop with wrong attempt", err, pb.ErrorReason_INSTANCE_MISMATCH)

	// 4. Process checks: our Firecracker, own scope in fcvms.slice, own UID.
	seenUID := map[string]bool{}
	for i, vm := range vms {
		pid := vm.GetPid()
		comm, _ := os.ReadFile(fmt.Sprintf("/proc/%d/comm", pid))
		cg, _ := os.ReadFile(fmt.Sprintf("/proc/%d/cgroup", pid))
		status, _ := os.ReadFile(fmt.Sprintf("/proc/%d/status", pid))
		uidLine := ""
		for _, l := range strings.Split(string(status), "\n") {
			if strings.HasPrefix(l, "Uid:") {
				uidLine = strings.Join(strings.Fields(l)[1:], " ")
			}
		}
		wantCG := "0::/fcvms.slice/" + jailer.ScopeUnit(ids[i])
		if strings.TrimSpace(string(comm)) != "firecracker" || strings.TrimSpace(string(cg)) != wantCG {
			t.Errorf("vm %d: comm %q cgroup %q, want firecracker %q", i, strings.TrimSpace(string(comm)), strings.TrimSpace(string(cg)), wantCG)
		}
		wantUID := fmt.Sprintf("%d %d %d %d", vm.GetUid(), vm.GetUid(), vm.GetUid(), vm.GetUid())
		if uidLine != wantUID || seenUID[uidLine] {
			t.Errorf("vm %d: Uid %q, want unique %q", i, uidLine, wantUID)
		}
		seenUID[uidLine] = true
		if i == 0 {
			t.Logf("vm 0: pid %d comm %s cgroup %s uid %s", pid, strings.TrimSpace(string(comm)), strings.TrimSpace(string(cg)), uidLine)
		}
	}
	t.Logf("cgroup/UID: %d VMs, %d unique UIDs", len(vms), len(seenUID))

	// 5. ping and run in every VM.
	okPing, okRun := 0, 0
	for i, id := range ids {
		v := lay.HostPath(id, template.VsockUDS)
		pctx, pcancel := context.WithTimeout(ctx, 10*time.Second)
		out, err := guestCmd(pctx, v, "ping")
		if err == nil && strings.TrimSpace(out) == "pong" {
			okPing++
		} else {
			t.Errorf("vm %d ping: %q %v", i, out, err)
		}
		out, err = guestRun(pctx, v, "run", "echo ok-$(id -un)")
		pcancel()
		if err == nil && strings.Contains(out, "ok-sandbox") && strings.Contains(out, "EXIT 0") {
			okRun++
		} else {
			t.Errorf("vm %d run: %q %v", i, out, err)
		}
	}
	t.Logf("ping %d/%d, run %d/%d", okPing, e.VMs, okRun, e.VMs)

	// 6. Scratch cap on VM 0: the guest sees the grown disk, grows ext4, then
	// a write past the cap fails.
	v0 := lay.HostPath(ids[0], template.VsockUDS)
	sctx, scancel := context.WithTimeout(ctx, 3*time.Minute)
	// The daemon (ENG-4571) will do this in Init. EXT4_IOC_RESIZE_FS is the
	// online grow that resize2fs uses; it needs no e2fsprogs in the image.
	out, err := guestRun(sctx, v0, "root", `echo dev_bytes=$(( $(cat /sys/block/vdb/size) * 512 ));
python3 - <<'EOF'
import fcntl, os, struct
dev = int(open("/sys/block/vdb/size").read()) * 512
fd = os.open("/mnt/scratch", os.O_RDONLY)
blocks = dev // os.statvfs("/mnt/scratch").f_frsize
fcntl.ioctl(fd, 0x40086610, struct.pack("Q", blocks))  # EXT4_IOC_RESIZE_FS
print("resized_blocks", blocks)
EOF
df -B1M --output=size /mnt/scratch | tail -1 | sed 's/^ */fs_mib=/'`)
	t.Logf("resize: %s %v", strings.TrimSpace(out), err)
	if !strings.Contains(out, fmt.Sprintf("dev_bytes=%d", int64(scratchGiB)*scratch.GiB)) || !strings.Contains(out, "resized_blocks") {
		t.Errorf("guest did not grow to a %d GiB scratch disk: %q", scratchGiB, out)
	}
	var fsMiB int
	if i := strings.Index(out, "fs_mib="); i >= 0 {
		_, _ = fmt.Sscanf(out[i:], "fs_mib=%d", &fsMiB)
	}
	if fsMiB < scratchGiB*1024*9/10 {
		t.Errorf("guest file system is %d MiB after the grow, want about %d", fsMiB, scratchGiB*1024)
	}
	out, err = guestRun(sctx, v0, "run", `dd if=/dev/zero of=/workspace/sessions/fill bs=1M count=3072 2>&1 | grep -v records; echo dd_rc=${PIPESTATUS[0]}; sync; df -B1M --output=used,avail /workspace/sessions | tail -1`)
	scancel()
	t.Logf("fill 3 GiB: %s %v", strings.TrimSpace(out), err)
	if !strings.Contains(out, "No space left on device") || strings.Contains(out, "dd_rc=0") {
		t.Errorf("write past the scratch cap did not fail: %q", out)
	}
	st, err := os.Stat(lay.HostPath(ids[0], template.ScratchFile))
	if err != nil {
		t.Errorf("stat host scratch file: %v", err)
	} else if st.Size() != int64(scratchGiB)*scratch.GiB {
		t.Errorf("host scratch file size %d, want %d", st.Size(), int64(scratchGiB)*scratch.GiB)
	}

	// 7. A VM that dies on its own shows as EXITED; a new attempt then works.
	crash := vms[e.VMs-1]
	if err := syscall.Kill(int(crash.GetPid()), syscall.SIGKILL); err != nil {
		t.Fatal(err)
	}
	var exited *pb.VM
	deadline := time.Now().Add(20 * time.Second)
	for exited == nil && time.Now().Before(deadline) {
		l, err := c.List(ctx, &pb.ListRequest{})
		if err != nil {
			t.Fatal(err)
		}
		for _, vm := range l.GetVms() {
			if vm.GetSandboxId() == crash.GetSandboxId() && vm.GetState() == pb.VMState_VM_STATE_EXITED {
				exited = vm
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	if exited == nil {
		t.Fatalf("killed VM did not show as EXITED")
	}
	r, err := c.Create(ctx, req(crash.GetSandboxId(), 2))
	if err != nil {
		t.Fatalf("new attempt after crash: %v", err)
	}
	t.Logf("crash: EXITED seen, attempt 2 created with generation %d", r.GetVm().GetGeneration())
	vms[e.VMs-1] = r.GetVm()

	// 8. List and NodeInfo.
	l, err := c.List(ctx, &pb.ListRequest{})
	if err != nil {
		t.Fatal(err)
	}
	running := 0
	for _, vm := range l.GetVms() {
		if vm.GetState() == pb.VMState_VM_STATE_RUNNING {
			running++
		}
	}
	ni, _ = c.NodeInfo(ctx, &pb.NodeInfoRequest{})
	t.Logf("List: %d VMs, %d running; NodeInfo vm_count %d mem_available_mib %d", len(l.GetVms()), running, ni.GetVmCount(), ni.GetMemAvailableMib())
	if running != e.VMs || int(ni.GetVmCount()) != e.VMs {
		t.Errorf("want %d running VMs", e.VMs)
	}

	// 9. Stop all; then the VMs, scopes and chroots are gone.
	stopLat := make([]float64, 0, e.VMs)
	for i, vm := range vms {
		s := time.Now()
		if _, err := c.Stop(ctx, &pb.StopRequest{SandboxId: vm.GetSandboxId(), Attempt: vm.GetAttempt(), Generation: vm.GetGeneration()}); err != nil {
			t.Errorf("stop %d: %v", i, err)
		}
		stopLat = append(stopLat, float64(time.Since(s).Milliseconds()))
	}
	t.Logf("BENCH stop_n=%d p50_ms=%.0f max_ms=%.0f", e.VMs, pct(stopLat, 0.5), pct(stopLat, 1))
	left := 0
	for _, vm := range vms {
		if _, err := os.Stat(fmt.Sprintf("/proc/%d", vm.GetPid())); err == nil {
			left++
		}
		if _, err := os.Stat(lay.ChrootDir(vm.GetSandboxId())); err == nil {
			t.Errorf("chroot of %s still exists", vm.GetSandboxId())
		}
		if a := scopeActive(cmd, vm.GetSandboxId()); a == "active" {
			t.Errorf("scope of %s still active", vm.GetSandboxId())
		}
	}
	if left != 0 {
		t.Errorf("%d Firecracker processes still exist", left)
	}
	r2, err := c.Stop(ctx, &pb.StopRequest{SandboxId: vms[0].GetSandboxId(), Attempt: 1, Generation: vms[0].GetGeneration()})
	if err != nil || !r2.GetAlreadyStopped() {
		t.Errorf("repeat stop: %v %v", r2, err)
	}
	_, err = c.Create(ctx, req(vms[0].GetSandboxId(), 1))
	wantReason(t, "create a stopped attempt again", err, pb.ErrorReason_STALE_ATTEMPT)
	t.Logf("stop: all %d stopped, 0 processes, 0 chroots, 0 active scopes", e.VMs)
}
