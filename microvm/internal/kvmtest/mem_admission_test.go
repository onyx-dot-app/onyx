//go:build kvm && linux

package kvmtest

import (
	"bufio"
	"context"
	"crypto/rand"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcapi/client/operations"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// Guest workloads. touch writes one byte per page, so the pages are real.
const (
	burstPy = `b = bytearray(2560 << 20)
for i in range(0, len(b), 4096):
    b[i] = 1
print('burst done', flush=True)
`
	holdPyMem = `import time
b = bytearray(%d << 20)
for i in range(0, len(b), 4096):
    b[i] = 1
print('held', flush=True)
time.sleep(86400)
`
	hogPy = `a = []
while True:
    x = bytearray(64 << 20)
    for i in range(0, len(x), 4096):
        x[i] = 1
    a.append(x)
`
)

// memVM is one VM of the test.
type memVM struct {
	id, key string
	vm      *pb.VM
}

func scopeDir(id string) string {
	return filepath.Join("/sys/fs/cgroup/fcvms.slice", jailer.ScopeUnit(id))
}

func readFileTrim(path string) string {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "ERR " + err.Error()
	}
	return strings.TrimSpace(string(raw))
}

// smapsMiB returns Rss and Anonymous of a process in MiB.
func smapsMiB(pid int32) (rss, anon uint64) {
	f, err := os.Open(fmt.Sprintf("/proc/%d/smaps_rollup", pid))
	if err != nil {
		return 0, 0
	}
	defer func() { _ = f.Close() }()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		fs := strings.Fields(sc.Text())
		if len(fs) < 2 {
			continue
		}
		kb, _ := strconv.ParseUint(fs[1], 10, 64)
		switch fs[0] {
		case "Rss:":
			rss = kb >> 10
		case "Anonymous:":
			anon = kb >> 10
		}
	}
	return rss, anon
}

// cgroupStat returns one memory.stat field of a VM scope in MiB.
func cgroupStat(id, field string) uint64 {
	raw, err := os.ReadFile(filepath.Join(scopeDir(id), "memory.stat"))
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(raw), "\n") {
		if k, v, ok := strings.Cut(line, " "); ok && k == field {
			n, _ := strconv.ParseUint(v, 10, 64)
			return n >> 20
		}
	}
	return 0
}

func cgroupEvent(id, field string) string {
	raw, err := os.ReadFile(filepath.Join(scopeDir(id), "memory.events"))
	if err != nil {
		return "gone"
	}
	for _, line := range strings.Split(string(raw), "\n") {
		if k, v, ok := strings.Cut(line, " "); ok && k == field {
			return v
		}
	}
	return "?"
}

func reasonMetadata(err error) map[string]string {
	st, _ := status.FromError(err)
	for _, d := range st.Details() {
		if info, ok := d.(*errdetails.ErrorInfo); ok {
			return info.GetMetadata()
		}
	}
	return nil
}

// TestMemAdmissionKVM checks memory admission and drain through the agent binary: a layout 4
// template with the balloon (free page reporting) and its restores, the
// guest daemon's page reporting order and idle reclaim, the per-VM cgroup
// limits, memory admission up to the refusal, and the manual drain.
func TestMemAdmissionKVM(t *testing.T) {
	e := loadEnv()
	_ = newCommand(t, e)
	ctx, cancel := context.WithTimeout(context.Background(), 75*time.Minute)
	defer cancel()
	src := getenv("KVM_TB_ROOTFS", "/opt/tb/rootfs-out")
	ca := getenv("KVM_TB_CA", "/opt/tb/ca/ca.crt")
	certDir := getenv("KVM_CERT_DIR", "/opt/tb/certs")
	rootfsDir := filepath.Join(e.DataDir, "rootfs")
	nIdle := e.VMs
	const agentName = "mem-a1"
	reclaimIdle := time.Minute // the root drive's --daemon-cmd sets --reclaim-idle=1m

	_ = exec.Command("docker", "rm", "-f", agentName).Run()
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", agentName).Run() })
	if err := os.MkdirAll(certDir, 0o700); err != nil {
		t.Fatal(err)
	}
	certs, err := testcerts.Write(certDir)
	if err != nil {
		t.Fatal(err)
	}
	putRootfs(t, src, rootfsDir, "")
	_ = os.Remove(filepath.Join(e.DataDir, "drain.json"))
	startTBAgent(t, e, agentName, rootfsDir, ca, certDir, certs)
	conn := ptConn(t, ctx, certs, agentName)
	ha, sd := pb.NewHostAgentClient(conn), sdpb.NewSandboxdClient(conn)
	br, err := ha.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
	if err != nil {
		t.Fatalf("build: %v\n%s", err, containerLogs(agentName))
	}
	tpl := br.GetTemplate()
	t.Logf("template %s balloon=%v managed_slots=%d built=%v build_ms=%d", tpl.GetVersion(), tpl.GetBalloon(),
		tpl.GetManagedSlots(), br.GetBuilt(), br.GetBuildMs())
	if !tpl.GetBalloon() {
		t.Fatal("the template has no balloon")
	}

	var all []*memVM
	create := func() (*memVM, error) {
		v := &memVM{id: newUUID(), key: randKey()}
		r, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: v.id, Attempt: 1, Template: tpl.GetVersion(),
			Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public", SandboxdKey: v.key})
		if err != nil {
			return nil, err
		}
		v.vm = r.GetVm()
		ent := make([]byte, 64)
		_, _ = rand.Read(ent)
		if _, err := sd.Init(vmCtx(ctx, v.id, v.key), &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: ent,
			SandboxId: v.id, Generation: v.vm.GetGeneration(), ScratchBytes: scratchGiB << 30}); err != nil {
			return nil, fmt.Errorf("init: %w", err)
		}
		all = append(all, v)
		return v, nil
	}
	mustCreate := func() *memVM {
		v, err := create()
		if err != nil {
			t.Fatalf("create: %v\n%s", err, containerLogs(agentName))
		}
		return v
	}
	run := func(v *memVM, script string) ptResult {
		r, err := ptRun(vmCtx(ctx, v.id, v.key), sd, "sh", "-c", script)
		if err != nil {
			t.Fatalf("run in %s: %v", v.id, err)
		}
		return r
	}
	stopAll := func() {
		for _, v := range all {
			if _, err := ha.Stop(ctx, &pb.StopRequest{SandboxId: v.id, Attempt: 1, Generation: v.vm.GetGeneration()}); err != nil {
				t.Errorf("stop %s: %v", v.id, err)
			}
		}
		all = nil
	}
	t.Cleanup(func() {
		for _, v := range all {
			_, _ = ha.Stop(context.Background(), &pb.StopRequest{SandboxId: v.id, Attempt: 1, Generation: v.vm.GetGeneration()})
		}
	})

	// 1. A restore from the layout 4 template has the balloon, the guest
	// reports at order 0, and the scope has the limits.
	v0 := mustCreate()
	api := fcvm.APIClient(filepath.Join(e.DataDir, "jail", "firecracker", v0.id, "root", jailer.APISock))
	bc, err := api.DescribeBalloonConfigContext(ctx, &operations.DescribeBalloonConfigParams{})
	if err != nil {
		t.Fatalf("GET /balloon on a restored VM: %v", err)
	}
	b := bc.Payload
	t.Logf("restored VM balloon: amount_mib=%d deflate_on_oom=%v free_page_reporting=%v free_page_hinting=%v stats_s=%d",
		*b.AmountMib, *b.DeflateOnOom, b.FreePageReporting, b.FreePageHinting, b.StatsPollingIntervals)
	if !b.FreePageReporting || b.FreePageHinting || *b.AmountMib != 0 {
		t.Errorf("balloon %+v", b)
	}
	r := run(v0, "cat /sys/module/page_reporting/parameters/page_reporting_order; zcat /proc/config.gz | grep -E '^CONFIG_(VIRTIO_BALLOON|PAGE_REPORTING|BALLOON_COMPACTION|COMPACTION)='; uname -r")
	t.Logf("guest: %s", strings.ReplaceAll(strings.TrimSpace(r.stdout), "\n", " | "))
	if !strings.HasPrefix(r.stdout, "0\n") || !strings.Contains(r.stdout, "CONFIG_PAGE_REPORTING=y") {
		t.Errorf("guest page reporting: %q %q", r.stdout, r.stderr)
	}
	memMax, cpuMax := readFileTrim(filepath.Join(scopeDir(v0.id), "memory.max")), readFileTrim(filepath.Join(scopeDir(v0.id), "cpu.max"))
	t.Logf("scope %s: memory.max=%s cpu.max=%s", jailer.ScopeUnit(v0.id), memMax, cpuMax)
	if memMax != fmt.Sprint((tplMemMiB+jailer.DefaultMemOverheadMiB)<<20) || cpuMax != fmt.Sprintf("%d 100000", tplVCPUs*100000) {
		t.Errorf("scope limits memory.max=%s cpu.max=%s", memMax, cpuMax)
	}
	// A CPU hog on every vCPU stays at the cpu.max quota.
	if r := run(v0, "for i in $(seq "+fmt.Sprint(tplVCPUs*2)+"); do timeout 10 sh -c 'while :; do :; done' & done; wait; echo ok"); r.res.GetExitCode() != 0 {
		t.Errorf("cpu hog: %q", r.stderr)
	}
	t.Logf("cpu.stat after a 10 s hog on %d threads: %s", tplVCPUs*2,
		strings.ReplaceAll(readFileTrim(filepath.Join(scopeDir(v0.id), "cpu.stat")), "\n", " "))

	// 2. Balloon reclaim on idle VMs: a burst (2.5 GiB anon + 1.5 GiB page
	// cache), then idle. Host memory per VM from the Firecracker process.
	vms := []*memVM{v0}
	for len(vms) < nIdle {
		vms = append(vms, mustCreate())
	}
	sample := func(what string) (anonSum uint64) {
		var cur, peak uint64
		for _, v := range vms {
			_, anon := smapsMiB(v.vm.GetPid())
			anonSum += anon
			cur += readUintFile(filepath.Join(scopeDir(v.id), "memory.current")) >> 20
			peak += readUintFile(filepath.Join(scopeDir(v.id), "memory.peak")) >> 20
		}
		n := uint64(len(vms))
		t.Logf("BENCH mem %-40s n=%d anon_avg_mib=%d cgroup_current_avg_mib=%d cgroup_peak_avg_mib=%d host_avail_mib=%d", what, n,
			anonSum/n, cur/n, peak/n, memAvailMiB(t))
		return anonSum / uint64(len(vms))
	}
	fresh := sample("fresh restore + Init")
	// All bursts at once, so every VM starts its idle period at the same
	// time and the samples below see one phase.
	errs := make(chan error, len(vms))
	for _, v := range vms {
		go func(v *memVM) {
			_, err := ptRun(vmCtx(ctx, v.id, v.key), sd, "sh", "-c",
				"cat > /tmp/burst.py <<'EOF'\n"+burstPy+"EOF\npython3 /tmp/burst.py && dd if=/dev/vda of=/dev/null bs=1M count=1536 2>/dev/null; echo ok")
			errs <- err
		}(v)
	}
	for range vms {
		if err := <-errs; err != nil {
			t.Fatalf("burst: %v", err)
		}
	}
	lastCall := time.Now()
	peak := sample("right after the burst")
	time.Sleep(30 * time.Second)
	reported := sample("burst + 30 s (free page reporting)")
	// The guest daemon drops caches after reclaimIdle without calls; it
	// checks every 15 s. Then reporting returns the pages (~20 s).
	time.Sleep(time.Until(lastCall.Add(reclaimIdle + 60*time.Second)))
	reclaimed := sample("idle reclaim (drop_caches) + reporting")
	t.Logf("BENCH reclaim per VM MiB: fresh=%d burst=%d after_reporting=%d after_idle_reclaim=%d", fresh, peak, reported, reclaimed)
	// Reporting returns the burst's freed anon memory within seconds, so it
	// is already gone in the first sample (the scope's memory.peak shows
	// the burst). The idle reclaim must return most of the page cache.
	if reclaimed*2 > reported {
		t.Errorf("no idle reclaim: burst %d, reporting %d, idle %d MiB", peak, reported, reclaimed)
	}
	lines := 0
	for _, v := range vms {
		if strings.Contains(run(v, "cat /run/craft-fc/log/guest-daemon.log 2>/dev/null").stdout, "idle memory reclaim") {
			lines++
		}
	}
	t.Logf("guest daemons that logged an idle reclaim: %d/%d", lines, len(vms))
	stopAll()

	// 3. Fill the node to the memory refusal: each VM holds holdMiB.
	const holdMiB = 3072
	var holds []string
	var refusal error
	t0 := time.Now()
	for i := 0; i < 60; i++ {
		v, err := create()
		if err != nil {
			refusal = err
			break
		}
		run(v, fmt.Sprintf("cat > /tmp/hold.py <<'EOF'\n"+holdPyMem+"EOF", holdMiB))
		st, err := sd.Start(vmCtx(ctx, v.id, v.key), &sdpb.StartRequest{Command: &sdpb.Command{Argv: []string{"python3", "/tmp/hold.py"}}})
		if err != nil {
			t.Fatal(err)
		}
		holds = append(holds, st.GetStarted().GetExecutionId())
		for {
			in, err := sd.Inspect(vmCtx(ctx, v.id, v.key), &sdpb.InspectRequest{ExecutionId: st.GetStarted().GetExecutionId()})
			if err != nil || in.GetExecution().GetState() != sdpb.ExecState_RUNNING {
				t.Fatalf("hold %d: %v %v", i, in, err)
			}
			if in.GetExecution().GetStdoutBytes() > 0 {
				break
			}
			time.Sleep(100 * time.Millisecond)
		}
	}
	availAfter := memAvailMiB(t)
	if apierr.FromStatus(refusal) != pb.ErrorReason_CAPACITY_MEMORY {
		t.Fatalf("fill: %d VMs, then %v", len(all), refusal)
	}
	md := reasonMetadata(refusal)
	t.Logf("BENCH fill: %d VMs holding %d MiB each admitted in %v; refusal: %s", len(all), holdMiB, time.Since(t0).Round(time.Second), status.Convert(refusal).Message())
	t.Logf("refusal metadata %v; host MemAvailable right after: %d MiB", md, availAfter)
	ni, err := ha.NodeInfo(ctx, &pb.NodeInfoRequest{})
	if err == nil {
		t.Logf("node info: total=%d available=%d reserve=%d starting=%d vms=%d", ni.GetMemTotalMib(), ni.GetMemAvailableMib(),
			ni.GetMemReserveMib(), ni.GetMemStartingMib(), ni.GetVmCount())
	}
	// Free one VM's hold: reporting returns its memory and Create works again.
	last := all[len(all)-1]
	if _, err := sd.Cancel(vmCtx(ctx, last.id, last.key), &sdpb.CancelRequest{ExecutionId: holds[len(holds)-1]}); err != nil {
		t.Fatal(err)
	}
	t1 := time.Now()
	admitted := false
	for time.Since(t1) < 90*time.Second {
		if _, err := create(); err == nil {
			admitted = true
			break
		} else if apierr.FromStatus(err) != pb.ErrorReason_CAPACITY_MEMORY {
			t.Fatalf("create after free: %v", err)
		}
		time.Sleep(2 * time.Second)
	}
	t.Logf("BENCH admitted again %v after one guest freed %d MiB: %v (MemAvailable %d MiB)", time.Since(t1).Round(time.Second), holdMiB, admitted, memAvailMiB(t))
	if !admitted {
		t.Error("the node did not admit a VM after a guest freed its memory")
	}

	// 4. Manual drain.
	d, err := ha.SetDrain(ctx, &pb.SetDrainRequest{Drain: true})
	if err != nil || d.GetDrain().GetState() != pb.DrainState_DRAIN_STATE_DRAINING {
		t.Fatalf("set drain: %v %v", d, err)
	}
	if _, err := create(); apierr.FromStatus(err) != pb.ErrorReason_NODE_DRAINING {
		t.Fatalf("create while draining: %v", err)
	}
	if _, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: v0.id, Attempt: 2, Template: tpl.GetVersion(),
		Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public"}); err == nil {
		t.Error("a new attempt started while draining")
	}
	stopAll()
	ni, err = ha.NodeInfo(ctx, &pb.NodeInfoRequest{})
	if err != nil || ni.GetDrain().GetState() != pb.DrainState_DRAIN_STATE_DRAINED {
		t.Fatalf("after stopping all: %v %v", ni.GetDrain(), err)
	}
	t.Logf("drain: %v", ni.GetDrain())
	if d, err := ha.SetDrain(ctx, &pb.SetDrainRequest{Drain: false}); err != nil || d.GetDrain().GetState() != pb.DrainState_DRAIN_STATE_ACTIVE {
		t.Fatalf("clear drain: %v %v", d, err)
	}

	// 5. A guest memory hog with the default overhead: the guest OOM
	// killer stops the hog, the VM lives. The overhead is anon + kernel
	// memory of the scope above the guest size.
	type hogResult struct {
		r   ptResult
		err error
	}
	hogOnce := func(v *memVM, what string) {
		done := make(chan hogResult, 1)
		go func() {
			r, err := ptRun(vmCtx(ctx, v.id, v.key), sd, "sh", "-c",
				"cat > /tmp/hog.py <<'EOF'\n"+hogPy+"EOF\n(dd if=/dev/vda of=/dev/null bs=1M 2>/dev/null &) ; python3 /tmp/hog.py; echo hog_rc=$?; dmesg | grep -i -m2 'out of memory'")
			done <- hogResult{r: r, err: err}
		}()
		var maxAnon, maxKernel, maxFile uint64
		var res ptResult
		var runErr error
		tick := time.NewTicker(200 * time.Millisecond)
		defer tick.Stop()
		limit := time.NewTimer(5 * time.Minute)
		defer limit.Stop()
	loop:
		for {
			select {
			case h := <-done:
				res, runErr = h.r, h.err
				break loop
			case <-tick.C:
				maxAnon = max(maxAnon, cgroupStat(v.id, "anon"))
				maxKernel = max(maxKernel, cgroupStat(v.id, "kernel"))
				maxFile = max(maxFile, cgroupStat(v.id, "file"))
			case <-limit.C:
				t.Errorf("%s: hog did not end", what)
				break loop
			}
		}
		l, _ := ha.List(ctx, &pb.ListRequest{})
		state := "missing"
		for _, x := range l.GetVms() {
			if x.GetSandboxId() == v.id {
				state = x.GetState().String()
			}
		}
		alive := pidAlive(v.vm.GetPid())
		t.Logf("BENCH hog %s: memory.max=%s peak=%s MiB, max anon=%d kernel=%d file=%d MiB (anon+kernel-guest=%d MiB), oom=%s oom_kill=%s, vm=%s fc_alive=%v, guest: %q",
			what, readFileTrim(filepath.Join(scopeDir(v.id), "memory.max")), mibOf(readFileTrim(filepath.Join(scopeDir(v.id), "memory.peak"))),
			maxAnon, maxKernel, maxFile, int64(maxAnon+maxKernel)-tplMemMiB, cgroupEvent(v.id, "oom"), cgroupEvent(v.id, "oom_kill"),
			state, alive, strings.TrimSpace(res.stdout))
		// The guest OOM killer must stop the hog; the VM must not die.
		if runErr != nil {
			t.Errorf("%s: hog call: %v", what, runErr)
		}
		if !strings.Contains(res.stdout, "hog_rc=137") {
			t.Errorf("%s: the guest OOM killer did not stop the hog: %q", what, res.stdout)
		}
		if state != pb.VMState_VM_STATE_RUNNING.String() || !alive {
			t.Errorf("%s: VM state %s, Firecracker alive %v; want a running VM", what, state, alive)
		}
		if k := cgroupEvent(v.id, "oom_kill"); k != "0" {
			t.Errorf("%s: scope oom_kill %s, want 0", what, k)
		}
	}
	bystander := mustCreate()
	hv := mustCreate()
	hogOnce(hv, "overhead default")

	// 6. The same hog with a 16 MiB overhead: the guest OOM killer still
	// stops the hog before Firecracker reaches memory.max, so the VM lives.
	_ = exec.Command("docker", "rm", "-f", agentName).Run()
	startTBAgent(t, e, agentName, rootfsDir, ca, certDir, certs, "--vm-mem-overhead-mib", "16")
	conn = ptConn(t, ctx, certs, agentName)
	ha, sd = pb.NewHostAgentClient(conn), sdpb.NewSandboxdClient(conn)
	tight := mustCreate()
	t.Logf("tight scope memory.max=%s", readFileTrim(filepath.Join(scopeDir(tight.id), "memory.max")))
	hogOnce(tight, "overhead 16 MiB")
	time.Sleep(3 * time.Second)
	l, _ := ha.List(ctx, &pb.ListRequest{})
	for _, x := range l.GetVms() {
		t.Logf("after the tight hog: %s %s pid=%d", x.GetSandboxId(), x.GetState(), x.GetPid())
	}
	if _, err := os.Stat(filepath.Join(e.DataDir, "jail", "firecracker", tight.id)); err == nil {
		t.Logf("tight VM chroot still present")
	} else {
		t.Logf("tight VM chroot removed")
	}
	t.Logf("tight scope after: %s", readFileTrim(filepath.Join(scopeDir(tight.id), "memory.events")))
	if r, err := ptRun(vmCtx(ctx, bystander.id, bystander.key), sd, "echo", "alive"); err != nil || r.stdout != "alive\n" {
		t.Errorf("bystander VM: %q %v", r.stdout, err)
	}
	stopAll()
	for _, line := range strings.Split(containerLogs(agentName), "\n") {
		if strings.Contains(line, `"level":"ERROR"`) || strings.Contains(line, "exited without Stop") {
			t.Logf("agent: %s", line)
		}
	}
}

func readUintFile(path string) uint64 {
	n, _ := strconv.ParseUint(readFileTrim(path), 10, 64)
	return n
}

func mibOf(s string) string {
	n, err := strconv.ParseUint(s, 10, 64)
	if err != nil {
		return s
	}
	return fmt.Sprint(n >> 20)
}

func pidAlive(pid int32) bool {
	raw, err := os.ReadFile(fmt.Sprintf("/proc/%d/comm", pid))
	return err == nil && strings.TrimSpace(string(raw)) == "firecracker"
}

// TestMemOOMKVM checks what happens when a Firecracker process goes over
// its scope's memory.max. A guest cannot do that with the default limit
// (TestMemAdmissionKVM: guest size + 16 MiB holds), so the test lowers
// memory.max of one running VM to 2 GiB, as a stand-in for a Firecracker
// that leaks. The kernel must kill only that VM; the agent must show it as
// EXITED and clean it up; the other VM keeps running.
func TestMemOOMKVM(t *testing.T) {
	e := loadEnv()
	_ = newCommand(t, e)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	src := getenv("KVM_TB_ROOTFS", "/opt/tb/rootfs-out")
	ca := getenv("KVM_TB_CA", "/opt/tb/ca/ca.crt")
	certDir := getenv("KVM_CERT_DIR", "/opt/tb/certs")
	rootfsDir := filepath.Join(e.DataDir, "rootfs")
	const agentName = "mem-oom-a1"
	_ = exec.Command("docker", "rm", "-f", agentName).Run()
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", agentName).Run() })
	if err := os.MkdirAll(certDir, 0o700); err != nil {
		t.Fatal(err)
	}
	certs, err := testcerts.Write(certDir)
	if err != nil {
		t.Fatal(err)
	}
	putRootfs(t, src, rootfsDir, "")
	startTBAgent(t, e, agentName, rootfsDir, ca, certDir, certs)
	conn := ptConn(t, ctx, certs, agentName)
	ha, sd := pb.NewHostAgentClient(conn), sdpb.NewSandboxdClient(conn)
	br, err := ha.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
	if err != nil {
		t.Fatal(err)
	}
	tpl := br.GetTemplate().GetVersion()
	newVM := func(attempt uint64, id string) *memVM {
		v := &memVM{id: id, key: randKey()}
		r, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: v.id, Attempt: attempt, Template: tpl,
			Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public", SandboxdKey: v.key})
		if err != nil {
			t.Fatalf("create: %v", err)
		}
		v.vm = r.GetVm()
		ent := make([]byte, 64)
		_, _ = rand.Read(ent)
		if _, err := sd.Init(vmCtx(ctx, v.id, v.key), &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: ent,
			SandboxId: v.id, Generation: v.vm.GetGeneration(), ScratchBytes: scratchGiB << 30}); err != nil {
			t.Fatalf("init: %v", err)
		}
		return v
	}
	bystander := newVM(1, newUUID())
	victim := newVM(1, newUUID())
	t.Cleanup(func() {
		for _, v := range []*memVM{bystander, victim} {
			_, _ = ha.Stop(context.Background(), &pb.StopRequest{SandboxId: v.id, Attempt: v.vm.GetAttempt(), Generation: v.vm.GetGeneration()})
		}
	})
	scope := scopeDir(victim.id)
	if err := os.WriteFile(filepath.Join(scope, "memory.max"), []byte(fmt.Sprint(2048<<20)), 0o644); err != nil {
		t.Fatal(err)
	}
	t0 := time.Now()
	r, runErr := ptRun(vmCtx(ctx, victim.id, victim.key), sd, "sh", "-c", "cat > /tmp/hog.py <<'EOF'\n"+hogPy+"EOF\npython3 /tmp/hog.py; echo hog_rc=$?")
	t.Logf("hog in the victim ended after %v: err=%v stdout=%q", time.Since(t0).Round(time.Millisecond), runErr, r.stdout)
	if runErr == nil {
		t.Fatal("the hog ended without killing the VM")
	}
	t.Logf("victim scope memory.events: %s", strings.ReplaceAll(readFileTrim(filepath.Join(scope, "memory.events")), "\n", " "))
	state := ""
	for time.Since(t0) < time.Minute {
		l, err := ha.List(ctx, &pb.ListRequest{})
		if err != nil {
			t.Fatal(err)
		}
		for _, x := range l.GetVms() {
			if x.GetSandboxId() == victim.id {
				state = x.GetState().String()
			}
		}
		if state == pb.VMState_VM_STATE_EXITED.String() {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Logf("victim state %s after %v; fc alive %v; scope dir exists %v; chroot exists %v", state, time.Since(t0).Round(time.Millisecond),
		pidAlive(victim.vm.GetPid()), exists(scope), exists(filepath.Join(e.DataDir, "jail", "firecracker", victim.id)))
	if state != pb.VMState_VM_STATE_EXITED.String() || pidAlive(victim.vm.GetPid()) {
		t.Errorf("victim: %s", state)
	}
	if r, err := ptRun(vmCtx(ctx, bystander.id, bystander.key), sd, "echo", "alive"); err != nil || r.stdout != "alive\n" {
		t.Errorf("bystander: %q %v", r.stdout, err)
	} else {
		t.Logf("bystander VM still runs")
	}
	sr, err := ha.Stop(ctx, &pb.StopRequest{SandboxId: victim.id, Attempt: 1, Generation: victim.vm.GetGeneration()})
	t.Logf("Stop of the killed VM: %v %v", sr, err)
	if err != nil || !sr.GetAlreadyStopped() {
		t.Errorf("stop: %v %v", sr, err)
	}
	next := newVM(2, victim.id)
	t.Logf("new attempt for the sandbox: generation %d, scope memory.max %s", next.vm.GetGeneration(),
		readFileTrim(filepath.Join(scopeDir(next.id), "memory.max")))
	victim = next
	for _, line := range strings.Split(containerLogs(agentName), "\n") {
		if strings.Contains(line, "exited without Stop") || strings.Contains(line, `"level":"ERROR"`) {
			t.Logf("agent: %s", line)
		}
	}
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
