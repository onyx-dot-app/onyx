//go:build kvm && linux

package kvmtest

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

const counterScript = `setsid nohup bash -c 'while true; do date +%s.%N >> /workspace/sessions/counter; sleep 1; done' >/dev/null 2>&1 </dev/null & echo COUNTER_STARTED`

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// startContainer runs the agent binary in a privileged container with the
// host PID and cgroup namespaces, as the DaemonSet will (ENG-4583).
func startContainer(t *testing.T, e env, name string) {
	t.Helper()
	bin := getenv("KVM_AGENT_BIN", "/opt/agent/host-agent")
	image := getenv("KVM_AGENT_IMAGE", "debian:trixie-slim")
	// The kit root drive has no egress CA, and an agent with no CA source
	// refuses CA-free templates. Any CA certificate will do.
	certDir := filepath.Join(e.DataDir, "restart-certs")
	if err := os.MkdirAll(certDir, 0o700); err != nil {
		t.Fatal(err)
	}
	certs, err := testcerts.Write(certDir)
	if err != nil {
		t.Fatal(err)
	}
	args := []string{"run", "-d", "--name", name, "--privileged", "--pid=host", "--cgroupns=host", "--network=host",
		"-v", e.DataDir + ":" + e.DataDir,
		"-v", e.ArtifactsDir + ":" + e.ArtifactsDir + ":ro",
		"-v", filepath.Dir(bin) + ":" + filepath.Dir(bin) + ":ro",
		"-v", "/sys/fs/cgroup:/sys/fs/cgroup",
		image, bin, "--data-dir", e.DataDir, "--artifacts-dir", e.ArtifactsDir, "--egress-ca", certs.ClientCA}
	if out, err := exec.Command("docker", args...).CombinedOutput(); err != nil {
		t.Fatalf("docker run: %v: %s", err, out)
	}
}

func containerLogs(name string) string {
	out, _ := exec.Command("docker", "logs", name).CombinedOutput()
	return string(out)
}

func dialAgent(t *testing.T, ctx context.Context, e env, name string) pb.HostAgentClient {
	t.Helper()
	sock := filepath.Join(e.DataDir, "run", "host-agent.sock")
	for {
		c, err := net.Dial("unix", sock)
		if err == nil {
			_ = c.Close()
			break
		}
		select {
		case <-ctx.Done():
			t.Fatalf("agent socket not ready: %v; logs:\n%s", err, containerLogs(name))
		case <-time.After(10 * time.Millisecond):
		}
	}
	conn, err := grpc.NewClient("unix://"+sock, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	c := pb.NewHostAgentClient(conn)
	if _, err := c.List(ctx, &pb.ListRequest{}); err != nil {
		t.Fatalf("list on new agent: %v; logs:\n%s", err, containerLogs(name))
	}
	return c
}

func alive(pid int32) bool {
	_, err := os.Stat(fmt.Sprintf("/proc/%d", pid))
	return err == nil
}

func TestRestartKVM(t *testing.T) {
	e := loadEnv()
	cmd := newCommand(t, e)
	buildTemplate(t, &e, cmd)
	for _, n := range []string{"ha1", "ha2"} {
		_ = exec.Command("docker", "rm", "-f", n).Run()
	}
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", "ha1", "ha2").Run() })
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
	defer cancel()
	lay := cmd.Layout

	startContainer(t, e, "ha1")
	c := dialAgent(t, ctx, e, "ha1")

	// 20 VMs, plus one whose journal record will be unreadable.
	n := e.VMs
	ids := make([]string, n+1)
	vms := make([]*pb.VM, n+1)
	var wg sync.WaitGroup
	errs := make([]error, n+1)
	for i := range ids {
		ids[i] = newUUID()
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			r, err := c.Create(ctx, &pb.CreateRequest{SandboxId: ids[i], Attempt: 1, Template: e.Template, Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public"})
			errs[i] = err
			if err == nil {
				vms[i] = r.GetVm()
			}
		}(i)
	}
	wg.Wait()
	for i, err := range errs {
		if err != nil {
			t.Fatalf("create %d: %v", i, err)
		}
	}
	doubt := vms[n]
	for i := 0; i < n; i++ {
		// The guest clock is behind by the template age until it is set (the
		// daemon's Init will do this).
		if _, err := guestCmd(ctx, lay.HostPath(ids[i], template.VsockUDS), fmt.Sprintf("settime %d", time.Now().UnixNano())); err != nil {
			t.Fatalf("settime %d: %v", i, err)
		}
		out, err := guestRun(ctx, lay.HostPath(ids[i], template.VsockUDS), "run", counterScript)
		if err != nil || !strings.Contains(out, "COUNTER_STARTED") {
			t.Fatalf("counter %d: %q %v", i, out, err)
		}
	}

	// An orphan: a VM in our layout that the agent never journaled.
	orphanID := newUUID()
	store := &template.Store{Dir: filepath.Join(e.DataDir, "templates")}
	tpl, err := store.Get(e.Template)
	if err != nil {
		t.Fatal(err)
	}
	l := &fcvm.Launcher{Cmd: cmd, Log: slog.Default()}
	orphan, err := l.Launch(ctx, agent.LaunchSpec{ID: orphanID, UID: 999990, Template: tpl, ScratchBytes: int64(tplScratchGiB) * scratch.GiB})
	if err != nil {
		t.Fatalf("orphan: %v", err)
	}
	orphanPID := int32(orphan.Info().PID)
	t.Logf("started %d VMs + 1 doubt VM via ha1, 1 orphan (pid %d) outside the agent", n, orphanPID)
	time.Sleep(3 * time.Second)

	// Stop the agent container. The VMs must keep running.
	tStop := time.Now()
	if out, err := exec.Command("docker", "stop", "-t", "10", "ha1").CombinedOutput(); err != nil {
		t.Fatalf("docker stop: %v: %s", err, out)
	}
	stopDur := time.Since(tStop)
	ha1Logs := containerLogs("ha1")
	_ = exec.Command("docker", "rm", "ha1").Run()
	aliveCount := 0
	for _, vm := range vms {
		if alive(vm.GetPid()) {
			aliveCount++
		}
	}
	t.Logf("docker stop took %d ms; %d/%d Firecracker processes alive while no agent runs", stopDur.Milliseconds(), aliveCount, n+1)
	if aliveCount != n+1 || !alive(orphanPID) {
		t.Fatalf("VMs died with the agent container")
	}
	// Make the doubt VM's record unreadable.
	if err := os.WriteFile(filepath.Join(e.DataDir, "journal", doubt.GetSandboxId()+".json"), []byte("{corrupt"), 0o600); err != nil {
		t.Fatal(err)
	}

	// Keep the agent down for a while, like a pod restart with an image pull.
	time.Sleep(5 * time.Second)
	startContainer(t, e, "ha2")
	c = dialAgent(t, ctx, e, "ha2")
	outage := time.Since(tStop)
	tUp := time.Now()
	logs := containerLogs("ha2")
	recovered := ""
	for _, line := range strings.Split(logs, "\n") {
		if strings.Contains(line, "recovered VMs") {
			recovered = line
		}
	}
	t.Logf("API outage (stop → new agent answers): %d ms", outage.Milliseconds())
	t.Logf("ha2: %s", recovered)

	l2, err := c.List(ctx, &pb.ListRequest{})
	if err != nil {
		t.Fatal(err)
	}
	byID := map[string]*pb.VM{}
	for _, vm := range l2.GetVms() {
		byID[vm.GetSandboxId()] = vm
	}
	adopted := 0
	for i := 0; i < n; i++ {
		got := byID[ids[i]]
		if got != nil && got.GetState() == pb.VMState_VM_STATE_RUNNING && got.GetGeneration() == vms[i].GetGeneration() && got.GetPid() == vms[i].GetPid() {
			adopted++
		} else {
			t.Errorf("vm %d not adopted: %v", i, got)
		}
	}
	t.Logf("adopted %d/%d (same generation and PID)", adopted, n)
	if _, listed := byID[doubt.GetSandboxId()]; listed {
		t.Errorf("VM with an unreadable record was adopted")
	}
	if !alive(doubt.GetPid()) {
		t.Errorf("VM with an unreadable record was killed")
	} else {
		t.Logf("unreadable record: VM left alone (pid %d alive, not listed)", doubt.GetPid())
	}
	orphanGone := false
	for deadline := time.Now().Add(10 * time.Second); time.Now().Before(deadline); time.Sleep(20 * time.Millisecond) {
		if !alive(orphanPID) {
			orphanGone = true
			break
		}
	}
	if _, err := os.Stat(lay.ChrootDir(orphanID)); err == nil || !orphanGone {
		t.Errorf("orphan not removed: pid alive=%v", !orphanGone)
	} else {
		t.Logf("orphan pid %d killed, chroot removed", orphanPID)
	}

	// The VMs and their programs ran on: ping/run and counters without gaps.
	time.Sleep(3 * time.Second)
	okPing, okRun, okCounter := 0, 0, 0
	worst := 0.0
	for i := 0; i < n; i++ {
		v := lay.HostPath(ids[i], template.VsockUDS)
		pctx, pcancel := context.WithTimeout(ctx, 20*time.Second)
		if out, err := guestCmd(pctx, v, "ping"); err == nil && strings.TrimSpace(out) == "pong" {
			okPing++
		}
		if out, err := guestRun(pctx, v, "run", "echo ok"); err == nil && strings.HasPrefix(out, "ok\n") {
			okRun++
		}
		out, err := guestRun(pctx, v, "run", "cat /workspace/sessions/counter")
		pcancel()
		if err != nil {
			t.Errorf("counter %d: %v", i, err)
			continue
		}
		var ts []float64
		for _, ln := range strings.Split(out, "\n") {
			if f, perr := strconv.ParseFloat(strings.TrimSpace(ln), 64); perr == nil {
				ts = append(ts, f)
			}
		}
		maxGap := 0.0
		for k := 1; k < len(ts); k++ {
			maxGap = max(maxGap, ts[k]-ts[k-1])
		}
		worst = max(worst, maxGap)
		// The counter must have ticked before the stop and after the new agent came up.
		before := len(ts) > 0 && ts[0] < float64(tStop.UnixNano())/1e9
		spans := before && ts[len(ts)-1] > float64(tUp.UnixNano())/1e9
		if maxGap < 1.5 && spans {
			okCounter++
		} else {
			t.Errorf("vm %d counter: %d ticks, max gap %.2f s, spans restart %v", i, len(ts), maxGap, spans)
		}
	}
	t.Logf("after restart: ping %d/%d, run %d/%d, counters without gaps %d/%d (worst gap %.2f s)", okPing, n, okRun, n, okCounter, n, worst)

	// Idempotency and Stop through the new agent.
	r, err := c.Create(ctx, &pb.CreateRequest{SandboxId: ids[0], Attempt: 1, Template: e.Template, Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public"})
	if err != nil || r.GetCreated() || r.GetVm().GetGeneration() != vms[0].GetGeneration() {
		t.Errorf("repeat create after restart: %v %v", r, err)
	}
	for i := 0; i < n; i++ {
		if _, err := c.Stop(ctx, &pb.StopRequest{SandboxId: ids[i], Attempt: 1, Generation: vms[i].GetGeneration()}); err != nil {
			t.Errorf("stop %d after restart: %v", i, err)
		}
	}
	left := 0
	for i := 0; i < n; i++ {
		if alive(vms[i].GetPid()) {
			left++
		}
	}
	t.Logf("stopped %d adopted VMs through ha2; %d processes left", n, left)

	// The doubt VM's sandbox is blocked while its VM runs.
	doubtReq := &pb.CreateRequest{SandboxId: doubt.GetSandboxId(), Attempt: 2, Template: e.Template, Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public"}
	_, err = c.Create(ctx, doubtReq)
	wantReason(t, "create of a sandbox in doubt", err, pb.ErrorReason_SANDBOX_IN_DOUBT)
	if raw, _ := os.ReadFile(filepath.Join(e.DataDir, "journal", doubt.GetSandboxId()+".json")); string(raw) != "{corrupt" {
		t.Errorf("record of a sandbox in doubt changed: %q", raw)
	}
	// Clean up the doubt VM by hand (the agent leaves it alone on purpose).
	if err := l.Remove(ctx, agent.Candidate{ID: doubt.GetSandboxId(), PID: int(doubt.GetPid())}); err != nil {
		t.Errorf("remove doubt VM: %v", err)
	}
	// Its process is gone, so the doubt clears and a new attempt starts.
	if r, err := c.Create(ctx, doubtReq); err != nil {
		t.Errorf("create after the doubt VM exited: %v", err)
	} else {
		t.Logf("doubt cleared after the VM exited; new attempt pid %d", r.GetVm().GetPid())
		if _, err := c.Stop(ctx, &pb.StopRequest{SandboxId: doubt.GetSandboxId(), Attempt: 2, Generation: r.GetVm().GetGeneration()}); err != nil {
			t.Errorf("stop of the new attempt: %v", err)
		}
	}
	_ = os.Remove(filepath.Join(e.DataDir, "journal", doubt.GetSandboxId()+".json"))
	if t.Failed() {
		t.Logf("ha1 logs:\n%s\nha2 logs:\n%s", ha1Logs, logs)
	}
}
