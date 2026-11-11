//go:build kvm && linux

package kvmtest

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// skillsBundle is a managed bundle: SKILL.md says "skills <ver>", run.sh is
// executable, big.bin is random (its SHA256 proves which drive a reader
// read), plus small files.
func skillsBundle(t *testing.T, ver string, bigMiB, small int) (zipBytes []byte, bigSHA string) {
	t.Helper()
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	add := func(name string, mode os.FileMode, data []byte) {
		h := &zip.FileHeader{Name: name, Method: zip.Deflate}
		h.SetMode(mode)
		w, err := zw.CreateHeader(h)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := w.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	big := make([]byte, bigMiB<<20)
	_, _ = rand.Read(big)
	sum := sha256.Sum256(big)
	add("skills/hello/SKILL.md", 0o644, []byte("skills "+ver+"\n"))
	add("skills/hello/run.sh", 0o755, []byte("#!/bin/sh\necho ran "+ver+"\n"))
	add("skills/hello/big.bin", 0o644, big)
	for i := range small {
		add(fmt.Sprintf("skills/lib/f%04d.txt", i), 0o644, []byte(fmt.Sprintf("%s file %d\n", ver, i)))
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes(), hex.EncodeToString(sum[:])
}

func putImage(ctx context.Context, ha pb.HostAgentClient, z []byte) (*pb.PutManagedImageResponse, error) {
	sum := sha256.Sum256(z)
	s, err := ha.PutManagedImage(ctx)
	if err != nil {
		return nil, err
	}
	hdr := &pb.ManagedBundleHeader{Sha256: hex.EncodeToString(sum[:]), SizeBytes: uint64(len(z))}
	if err := s.Send(&pb.PutManagedImageRequest{Part: &pb.PutManagedImageRequest_Header{Header: hdr}}); err != nil {
		return nil, err
	}
	for off := 0; off < len(z); off += 1 << 20 {
		end := min(off+1<<20, len(z))
		if err := s.Send(&pb.PutManagedImageRequest{Part: &pb.PutManagedImageRequest_Data{Data: z[off:end]}}); err != nil {
			break // the agent already has the image
		}
	}
	return s.CloseAndRecv()
}

const managedHoldPy = `import hashlib, os, sys, time
d = '/workspace/managed/skills/hello'
f = open(d + '/SKILL.md', 'rb')
big = open(d + '/big.bin', 'rb')
os.chdir(d)
print('first', f.read().decode().strip(), flush=True)
while not os.path.exists('/tmp/go'):
    time.sleep(0.02)
f.seek(0)
try:
    cwd = os.getcwd()
except FileNotFoundError:
    cwd = 'ENOENT'
rel = open('run.sh').read().split()[-1]
print('again', f.read().decode().strip(), hashlib.sha256(big.read()).hexdigest(), 'cwd-relative', rel, 'getcwd', cwd, flush=True)
`

// TestManagedSwapKVM checks the managed drive swap through the
// agent binary: n running VMs from a layout 3 template, a reader in each VM
// that holds files open on the managed drive, a swap of every VM one at a
// time, and the guest checks (new content, old reader intact, noexec, no
// rw remount, no restart).
func TestManagedSwapKVM(t *testing.T) {
	e := loadEnv()
	_ = newCommand(t, e)
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Minute)
	defer cancel()
	src := getenv("KVM_TB_ROOTFS", "/opt/tb/rootfs-out")
	ca := getenv("KVM_TB_CA", "/opt/tb/ca/ca.crt")
	certDir := getenv("KVM_CERT_DIR", "/opt/tb/certs")
	rootfsDir := filepath.Join(e.DataDir, "rootfs")
	n := e.VMs
	const agentName = "ms-a1"

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
		t.Fatalf("build: %v\n%s", err, containerLogs(agentName))
	}
	tpl := br.GetTemplate()
	t.Logf("template %s managed_slots=%d built=%v build_ms=%d", tpl.GetVersion(), tpl.GetManagedSlots(), br.GetBuilt(), br.GetBuildMs())
	if tpl.GetManagedSlots() != 2 {
		t.Fatalf("template has %d managed slots", tpl.GetManagedSlots())
	}

	// n running VMs, each with Init.
	ids, keys := make([]string, n), make([]string, n)
	vms := make([]*pb.VM, n)
	for i := range ids {
		ids[i], keys[i] = newUUID(), randKey()
		r, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: ids[i], Attempt: 1, Template: tpl.GetVersion(),
			Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public", SandboxdKey: keys[i]})
		if err != nil {
			t.Fatalf("create %d: %v\n%s", i, err, containerLogs(agentName))
		}
		vms[i] = r.GetVm()
		ent := make([]byte, 64)
		_, _ = rand.Read(ent)
		if _, err := sd.Init(vmCtx(ctx, ids[i], keys[i]), &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: ent,
			SandboxId: ids[i], Generation: vms[i].GetGeneration(), ScratchBytes: scratchGiB << 30}); err != nil {
			t.Fatalf("init %d: %v", i, err)
		}
	}
	run := func(i int, script string) (ptResult, error) {
		return ptRun(vmCtx(ctx, ids[i], keys[i]), sd, "sh", "-c", script)
	}
	targets := func(idx ...int) []*pb.SwapTarget {
		var out []*pb.SwapTarget
		for _, i := range idx {
			out = append(out, &pb.SwapTarget{SandboxId: ids[i], Attempt: 1, Generation: vms[i].GetGeneration(), SandboxdKey: keys[i]})
		}
		return out
	}
	all := make([]int, n)
	for i := range all {
		all[i] = i
	}
	swap := func(what, image string, idx []int) []*pb.SwapResult {
		t0 := time.Now()
		r, err := ha.SwapManaged(ctx, &pb.SwapManagedRequest{ImageId: image, Targets: targets(idx...)})
		if err != nil {
			t.Fatalf("%s: %v", what, err)
		}
		wall := time.Since(t0)
		var ms []float64
		for _, res := range r.GetResults() {
			ms = append(ms, float64(res.GetMs()))
		}
		t.Logf("BENCH swap %s n=%d total_ms=%d per_vm_ms p50=%.0f p95=%.0f max=%.0f", what, len(idx), wall.Milliseconds(),
			pctl(ms, 0.5), pctl(ms, 0.95), pctl(ms, 1))
		return r.GetResults()
	}
	mustOK := func(what string, rs []*pb.SwapResult, slot pb.ManagedSlot) {
		for i, res := range rs {
			if !res.GetOk() || res.GetActive() != slot {
				t.Fatalf("%s vm %d: %v", what, i, res)
			}
		}
	}

	// Before any swap: slot A has the empty template placeholder.
	if r, err := run(0, "grep ' /workspace/managed ' /proc/self/mountinfo; ls -A /workspace/managed | wc -l"); err == nil {
		t.Logf("before: %s", strings.TrimSpace(r.stdout))
	}

	// Images: v1, v2, v3.
	type img struct {
		id, bigSHA string
	}
	imgs := map[string]img{}
	for _, v := range []string{"v1", "v2", "v3"} {
		z, bigSHA := skillsBundle(t, v, 8, 300)
		t0 := time.Now()
		pr, err := putImage(ctx, ha, z)
		if err != nil {
			t.Fatalf("put %s: %v\n%s", v, err, containerLogs(agentName))
		}
		t.Logf("BENCH put_image %s zip_bytes=%d image_bytes=%d files=%d build_ms=%d call_ms=%d", v, len(z),
			pr.GetImage().GetSizeBytes(), pr.GetImage().GetFiles(), pr.GetBuildMs(), time.Since(t0).Milliseconds())
		imgs[v] = img{id: pr.GetImage().GetImageId(), bigSHA: bigSHA}
	}

	// 1. First load: v1 into every VM (slot B).
	mustOK("v1", swap("v1 (first load)", imgs["v1"].id, all), pb.ManagedSlot_MANAGED_SLOT_B)

	// 2. A reader in each VM holds SKILL.md and big.bin open (and its cwd) on
	// the v1 drive.
	pidsBefore := map[string]int32{}
	l, err := ha.List(ctx, &pb.ListRequest{})
	if err != nil {
		t.Fatal(err)
	}
	for _, vm := range l.GetVms() {
		pidsBefore[vm.GetSandboxId()] = vm.GetPid()
	}
	readers := make([]string, n)
	uptime := make([]time.Duration, n)
	for i := range ids {
		if _, err := run(i, "cat > /tmp/hold.py <<'EOF'\n"+managedHoldPy+"EOF\nrm -f /tmp/go"); err != nil {
			t.Fatal(err)
		}
		st, err := sd.Start(vmCtx(ctx, ids[i], keys[i]), &sdpb.StartRequest{Command: &sdpb.Command{Argv: []string{"python3", "/tmp/hold.py"}}})
		if err != nil {
			t.Fatal(err)
		}
		readers[i] = st.GetStarted().GetExecutionId()
	}
	for i := range ids {
		for {
			in, err := sd.Inspect(vmCtx(ctx, ids[i], keys[i]), &sdpb.InspectRequest{ExecutionId: readers[i]})
			if err != nil {
				t.Fatal(err)
			}
			if in.GetExecution().GetState() != sdpb.ExecState_RUNNING {
				t.Fatalf("reader %d ended: %v", i, in.GetExecution())
			}
			if in.GetExecution().GetStdoutBytes() > 0 {
				break
			}
			time.Sleep(20 * time.Millisecond)
		}
		h, err := sd.Health(vmCtx(ctx, ids[i], keys[i]), &sdpb.HealthRequest{})
		if err != nil {
			t.Fatal(err)
		}
		uptime[i] = h.GetUptime().AsDuration()
	}

	// 3. The swap under test: v2 into every VM while the readers hold v1.
	res := swap("v2 (readers hold v1)", imgs["v2"].id, all)
	mustOK("v2", res, pb.ManagedSlot_MANAGED_SLOT_A)
	inUse := 0
	for _, r := range res {
		if r.GetPreviousInUse() {
			inUse++
		}
	}
	t.Logf("v2: %d/%d VMs report the old drive in use (readers)", inUse, n)
	if inUse != n {
		t.Errorf("previous_in_use on %d VMs, want %d", inUse, n)
	}

	// 4. Guest checks.
	const checks = `set -u
cat /workspace/managed/skills/hello/SKILL.md
echo mounts=$(grep -c ' /workspace/managed ' /proc/self/mountinfo)
grep ' /workspace/managed ' /proc/self/mountinfo | awk '{print "opts=" $6, "src=" $(NF-1)}'
/workspace/managed/skills/hello/run.sh >/dev/null 2>&1; echo exec_rc=$?
sh /workspace/managed/skills/hello/run.sh
mount -o remount,rw /workspace/managed 2>/dev/null; echo remount_rc=$?
touch /workspace/managed/x 2>/dev/null; echo touch_rc=$?
dev=$(grep ' /workspace/managed ' /proc/self/mountinfo | awk '{print $(NF-1)}')
blockdev --setrw "$dev" 2>/dev/null; echo setrw_rc=$?
mount -o remount,rw /workspace/managed 2>/dev/null; echo remount2_rc=$?
touch /workspace/managed/y 2>/dev/null; echo touch2_rc=$?
echo files=$(ls /workspace/managed/skills/lib | wc -l)
`
	failures := 0
	for i := range ids {
		r, err := run(i, checks)
		if err != nil {
			t.Fatalf("checks %d: %v", i, err)
		}
		out := r.stdout
		ok := strings.HasPrefix(out, "skills v2\n") && strings.Contains(out, "mounts=1\n") &&
			strings.Contains(out, "src=/dev/vdc") && strings.Contains(out, "exec_rc=126") &&
			strings.Contains(out, "ran v2") && !strings.Contains(out, "remount_rc=0") && !strings.Contains(out, "touch_rc=0") &&
			!strings.Contains(out, "remount2_rc=0") && !strings.Contains(out, "touch2_rc=0") && strings.Contains(out, "files=300")
		for _, o := range []string{"ro", "nosuid", "nodev", "noexec"} {
			if !strings.Contains(strings.SplitN(strings.SplitN(out, "opts=", 2)[1], " ", 2)[0], o) {
				ok = false
			}
		}
		if i == 0 || !ok {
			t.Logf("vm %d guest checks:\n%s%s", i, out, r.stderr)
		}
		if !ok {
			failures++
		}
	}
	if failures > 0 {
		t.Errorf("%d VMs failed the guest checks", failures)
	}

	// 5. A third swap goes to slot B, which the readers still hold: refused.
	busy := swap("v3 while readers hold slot B", imgs["v3"].id, []int{0})
	if busy[0].GetOk() || busy[0].GetReason() != pb.ErrorReason_MANAGED_SLOT_BUSY {
		t.Fatalf("busy slot: %v", busy[0])
	}
	t.Logf("busy slot: %s: %s", busy[0].GetReason(), busy[0].GetMessage())

	// 6. Readers: drop the guest page cache, then read the old files again
	// (from the old drive, which is lazily detached).
	readerOK := 0
	for i := range ids {
		if _, err := run(i, "sync; echo 3 > /proc/sys/vm/drop_caches; touch /tmp/go"); err != nil {
			t.Fatal(err)
		}
		s, err := sd.Stream(vmCtx(ctx, ids[i], keys[i]), &sdpb.StreamRequest{ExecutionId: readers[i]})
		if err != nil {
			t.Fatal(err)
		}
		r, err := ptCollect(s)
		if err != nil {
			t.Fatal(err)
		}
		// A cwd on a detached mount still works for relative paths, but
		// getcwd() fails with ENOENT (the path is gone).
		want := "first skills v1\nagain skills v1 " + imgs["v1"].bigSHA + " cwd-relative v1 getcwd ENOENT\n"
		if i == 0 {
			t.Logf("reader 0: %q", r.stdout)
		}
		if r.stdout == want && r.res.GetExitCode() == 0 {
			readerOK++
		} else {
			t.Errorf("reader %d: %q %q %v", i, r.stdout, r.stderr, r.res)
		}
	}
	t.Logf("readers that read the old drive intact after the swap: %d/%d", readerOK, n)

	// 7. No VM restart: same Firecracker PID, daemon uptime kept growing.
	l, err = ha.List(ctx, &pb.ListRequest{})
	if err != nil {
		t.Fatal(err)
	}
	same := 0
	for _, vm := range l.GetVms() {
		if pidsBefore[vm.GetSandboxId()] == vm.GetPid() && vm.GetManaged().GetActive() == pb.ManagedSlot_MANAGED_SLOT_A &&
			vm.GetManaged().GetSlotAImage() == imgs["v2"].id && vm.GetManaged().GetSlotBImage() == imgs["v1"].id {
			same++
		}
	}
	for i := range ids {
		h, err := sd.Health(vmCtx(ctx, ids[i], keys[i]), &sdpb.HealthRequest{})
		if err != nil || h.GetUptime().AsDuration() <= uptime[i] {
			t.Errorf("vm %d daemon restarted: %v %v", i, h, err)
		}
	}
	t.Logf("same Firecracker PID and journal slots after the swaps: %d/%d", same, n)
	if same != n {
		t.Errorf("%d/%d VMs kept their PID and slots", same, n)
	}

	// 8. With the readers gone, v3 goes to slot B in every VM; a repeat does
	// nothing.
	mustOK("v3", swap("v3 (no readers)", imgs["v3"].id, all), pb.ManagedSlot_MANAGED_SLOT_B)
	again := swap("v3 again", imgs["v3"].id, []int{0})
	if !again[0].GetOk() || again[0].GetChanged() {
		t.Fatalf("repeat: %v", again[0])
	}
	if r, err := run(0, "cat /workspace/managed/skills/hello/SKILL.md; grep ' /workspace/managed ' /proc/self/mountinfo | awk '{print $(NF-1)}'"); err != nil ||
		r.stdout != "skills v3\n/dev/vdf\n" {
		t.Fatalf("after v3: %q %v", r.stdout, err)
	}

	// 9. Agent restart: the journal keeps the slots; a swap still works.
	if out, err := exec.Command("docker", "restart", agentName).CombinedOutput(); err != nil {
		t.Fatalf("restart: %v %s", err, out)
	}
	conn = ptConn(t, ctx, certs, agentName)
	ha, sd = pb.NewHostAgentClient(conn), sdpb.NewSandboxdClient(conn)
	l, err = ha.List(ctx, &pb.ListRequest{})
	if err != nil {
		t.Fatal(err)
	}
	for _, vm := range l.GetVms() {
		if vm.GetManaged().GetActive() != pb.ManagedSlot_MANAGED_SLOT_B || vm.GetManaged().GetSlotBImage() != imgs["v3"].id {
			t.Errorf("after restart %s: %v", vm.GetSandboxId(), vm.GetManaged())
		}
	}
	mustOK("v2 after restart", swap("v2 after an agent restart", imgs["v2"].id, []int{0}), pb.ManagedSlot_MANAGED_SLOT_A)
	if r, err := run(0, "cat /workspace/managed/skills/hello/SKILL.md"); err != nil || r.stdout != "skills v2\n" {
		t.Fatalf("after restart swap: %q %v", r.stdout, err)
	}
	ni, err := ha.NodeInfo(ctx, &pb.NodeInfoRequest{})
	if err == nil {
		for _, mi := range ni.GetManagedImages() {
			t.Logf("node image %s size=%d files=%d vms=%d", mi.GetImageId()[:12], mi.GetSizeBytes(), mi.GetFiles(), mi.GetVms())
		}
	}

	for i := range ids {
		if _, err := ha.Stop(ctx, &pb.StopRequest{SandboxId: ids[i], Attempt: 1, Generation: vms[i].GetGeneration()}); err != nil {
			t.Errorf("stop %d: %v", i, err)
		}
	}
	if logs := containerLogs(agentName); strings.Contains(logs, `"level":"ERROR"`) {
		for _, line := range strings.Split(logs, "\n") {
			if strings.Contains(line, `"level":"ERROR"`) {
				t.Logf("agent error: %s", line)
			}
		}
	}
}
