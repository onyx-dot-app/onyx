//go:build kvm && linux

package kvmtest

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	"github.com/onyx-dot-app/onyx/microvm/internal/server"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

const (
	ptNodeID   = "kvm-node-1"
	ptSecret   = "kvm-registration-secret-1"
	ptListen   = "127.0.0.1:7443"
	ptRegURL   = "http://127.0.0.1:8095"
	ptProxy    = "127.0.0.1:8099"
	ptBootArgs = "console=ttyS0 reboot=k panic=1 pci=off init=/sbin/craft-init craft.scratch=defer"
)

// waitDaemon waits until the guest daemon answers Health on vsock 52.
func waitDaemon(ctx context.Context, vsockPath string) error {
	for {
		conn, err := grpc.NewClient("passthrough:///guestd",
			grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) {
				return fcvm.DialVsock(ctx, vsockPath, server.DefaultDaemonPort)
			}),
			grpc.WithTransportCredentials(insecure.NewCredentials()))
		if err != nil {
			return err
		}
		hctx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
		_, err = sdpb.NewSandboxdClient(conn).Health(hctx, &sdpb.HealthRequest{})
		cancel()
		_ = conn.Close()
		if err == nil {
			return nil
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("guest daemon did not answer: %v", err)
		case <-time.After(20 * time.Millisecond):
		}
	}
}

// startPTAgent runs the agent binary in a privileged container with the
// host PID namespace and the given cgroup namespace mode (the DaemonSet's
// pod gets a private one), with the mTLS listener, egress relay and node key
// registration.
func startPTAgent(t *testing.T, e env, name, cgroupns, certDir string, certs *testcerts.Set) {
	t.Helper()
	bin := getenv("KVM_AGENT_BIN", "/opt/agent/host-agent")
	image := getenv("KVM_AGENT_IMAGE", "debian:trixie-slim")
	args := []string{"run", "-d", "--name", name, "--privileged", "--pid=host", "--cgroupns=" + cgroupns, "--network=host",
		"-e", "SANDBOX_NODE_REGISTRATION_SECRET=" + ptSecret,
		"-v", e.DataDir + ":" + e.DataDir,
		"-v", certDir + ":" + certDir + ":ro"}
	// The proxy CA, which the daemon installs at Init.
	confdir := getenv("KVM_PROXY_CONFDIR", "/opt/proxy/confdir")
	args = append(args, "-v", confdir+":"+confdir+":ro")
	if !chartMode() {
		args = append(args, "-v", e.ArtifactsDir+":"+e.ArtifactsDir+":ro", "-v", filepath.Dir(bin)+":"+filepath.Dir(bin)+":ro")
	}
	if cgroupns == "host" {
		args = append(args, "-v", "/sys/fs/cgroup:/sys/fs/cgroup")
	}
	artifacts := e.ArtifactsDir
	if chartMode() {
		// As the Helm DaemonSet runs it: the published image (agent and
		// artifacts inside), its own cgroup namespace joined to the host's
		// with nsenter, and no host /sys/fs/cgroup mount.
		args = append(args, "-v", "/dev/kvm:/dev/kvm", "--entrypoint", "nsenter", image,
			"--target=1", "--cgroup", "--", "/usr/local/bin/host-agent")
		artifacts = "/opt/craft-fc"
	} else {
		args = append(args, image, bin)
	}
	args = append(args, "--data-dir", e.DataDir, "--artifacts-dir", artifacts,
		"--listen", ptListen, "--tls-cert", certs.ServerCert, "--tls-key", certs.ServerKey, "--client-ca", certs.ClientCA,
		"--node-id", ptNodeID, "--egress-proxy", ptProxy, "--api-server-url", ptRegURL,
		"--egress-ca", filepath.Join(confdir, "mitmproxy-ca-cert.pem"))
	if out, err := exec.Command("docker", args...).CombinedOutput(); err != nil {
		t.Fatalf("docker run: %v: %s", err, out)
	}
}

// ptConn opens an mTLS connection to the agent and waits until it answers.
func ptConn(t *testing.T, ctx context.Context, certs *testcerts.Set, name string) *grpc.ClientConn {
	t.Helper()
	raw, err := os.ReadFile(certs.ServerCA)
	if err != nil {
		t.Fatal(err)
	}
	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(raw)
	c, err := tls.LoadX509KeyPair(certs.GoodCert, certs.GoodKey)
	if err != nil {
		t.Fatal(err)
	}
	cfg := &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS13, Certificates: []tls.Certificate{c}}
	conn, err := grpc.NewClient(ptListen, grpc.WithTransportCredentials(credentials.NewTLS(cfg)))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	ha := pb.NewHostAgentClient(conn)
	for {
		lctx, cancel := context.WithTimeout(ctx, time.Second)
		_, err := ha.List(lctx, &pb.ListRequest{})
		cancel()
		if err == nil {
			return conn
		}
		select {
		case <-ctx.Done():
			t.Fatalf("agent %s not ready over mTLS: %v; logs:\n%s", name, err, containerLogs(name))
		case <-time.After(20 * time.Millisecond):
		}
	}
}

func vmCtx(ctx context.Context, id, key string) context.Context {
	return metadata.AppendToOutgoingContext(ctx, server.SandboxIDHeader, id, guestd.KeyHeader, key)
}

type ptResult struct {
	id             string
	stdout, stderr string
	res            *sdpb.ExecResult
}

func ptCollect(s interface {
	Recv() (*sdpb.ExecEvent, error)
}) (ptResult, error) {
	var r ptResult
	var out, errb strings.Builder
	for {
		ev, err := s.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return r, err
		}
		switch x := ev.GetEvent().(type) {
		case *sdpb.ExecEvent_Started:
			r.id = x.Started.GetExecutionId()
		case *sdpb.ExecEvent_Output:
			if x.Output.GetStream() == sdpb.OutputStream_STDOUT {
				out.Write(x.Output.GetData())
			} else {
				errb.Write(x.Output.GetData())
			}
		case *sdpb.ExecEvent_Result:
			r.res = x.Result
		}
	}
	r.stdout, r.stderr = out.String(), errb.String()
	if r.res == nil {
		return r, errors.New("no result event")
	}
	return r, nil
}

func ptRun(ctx context.Context, c sdpb.SandboxdClient, argv ...string) (ptResult, error) {
	s, err := c.Run(ctx, &sdpb.RunRequest{Command: &sdpb.Command{Argv: argv}})
	if err != nil {
		return ptResult{}, err
	}
	return ptCollect(s)
}

func pctl(v []float64, p float64) float64 {
	if len(v) == 0 {
		return 0
	}
	s := slices.Clone(v)
	slices.Sort(s)
	return s[int(p*float64(len(s)-1)+0.5)]
}

func msOf(d time.Duration) float64 { return float64(d.Microseconds()) / 1000 }

func randKey() string {
	b := make([]byte, 32)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func logLine(logs, substr string) (int, string) {
	for i, l := range strings.Split(logs, "\n") {
		if strings.Contains(l, substr) {
			return i, l
		}
	}
	return -1, ""
}

// TestPassthroughKVM runs the guest daemon API end to end through the node
// agent pass-through over mTLS, with the agent in a private cgroup namespace
// (ENG-4571, ENG-4606, ENG-4610).
func TestPassthroughKVM(t *testing.T) {
	e := loadEnv()
	if e.VMs < 2 {
		t.Fatalf("KVM_VMS must be at least 2 for the pass-through test, got %d", e.VMs)
	}
	// Its own template: buildTemplateWith reuses any template of the same name,
	// and the other KVM tests build theirs with the prototype agent.
	e.Template = getenv("KVM_PT_TEMPLATE", "kvmtest-pt-1")
	cmd := newCommand(t, e)
	buildTemplateWith(t, &e, cmd, getenv("KVM_PT_BOOT_ARGS", ptBootArgs), waitDaemon)
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Minute)
	defer cancel()
	cgroupns := getenv("KVM_CGROUPNS", "private")
	logDir := getenv("KVM_LOG_DIR", "/var/log/bench")
	py := getenv("KVM_PYTHON", "/opt/proxy/venv/bin/python")
	harness := getenv("KVM_HARNESS_DIR", "/opt/harness")
	confdir := getenv("KVM_PROXY_CONFDIR", "/opt/proxy/confdir")
	certDir := getenv("KVM_CERT_DIR", "/opt/pt/certs")

	// Egress proxy harness: the sandbox-proxy gate addon and the node key route.
	_ = exec.Command("docker", "rm", "-f", "kvm-redis", "pt-a1", "pt-a2").Run()
	if out, err := exec.Command("docker", "run", "-d", "--rm", "--name", "kvm-redis", "--network", "host", "redis:7-alpine").CombinedOutput(); err != nil {
		t.Fatalf("redis: %v %s", err, out)
	}
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", "kvm-redis").Run() })
	penv := []string{"SANDBOX_RUNTIME=firecracker", "CACHE_BACKEND=redis", "REDIS_HOST=127.0.0.1", "REDIS_PORT=6379",
		"MULTI_TENANT=false", "LOG_LEVEL=debug", "SANDBOX_NODE_REGISTRATION_SECRET=" + ptSecret,
		"PYTHONPATH=" + getenv("KVM_PR_BACKEND", "/opt/pr/backend"), "HARNESS_CONFDIR=" + confdir}
	reg := startService(t, "reg_server", filepath.Join(logDir, "pt-reg.log"), penv, py, filepath.Join(harness, "reg_server.py"))
	proxy := startService(t, "gate_proxy", filepath.Join(logDir, "pt-proxy.log"), penv, py, filepath.Join(harness, "gate_proxy.py"))
	waitTCP(t, ctx, "127.0.0.1:8095", reg)
	waitTCP(t, ctx, "127.0.0.1:8099", proxy)

	if err := os.MkdirAll(certDir, 0o700); err != nil {
		t.Fatal(err)
	}
	certs, err := testcerts.Write(certDir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", "pt-a1", "pt-a2").Run() })
	startPTAgent(t, e, "pt-a1", cgroupns, certDir, certs)
	conn := ptConn(t, ctx, certs, "pt-a1")
	ha, sd := pb.NewHostAgentClient(conn), sdpb.NewSandboxdClient(conn)
	if _, l := logLine(containerLogs("pt-a1"), "private cgroup namespace"); l != "" {
		t.Logf("agent: %s", l)
	} else if cgroupns == "private" && !chartMode() {
		t.Errorf("agent did not detect its private cgroup namespace")
	}

	// Create N VMs from the template (booted with craft.scratch=defer).
	n := e.VMs
	ids, keys := make([]string, n), make([]string, n)
	vms := make([]*pb.VM, n)
	createMS := make([]float64, n)
	errs := make([]error, n)
	var wg sync.WaitGroup
	for i := range ids {
		ids[i], keys[i] = newUUID(), randKey()
		wg.Go(func() {
			t0 := time.Now()
			r, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: ids[i], Attempt: 1, Template: e.Template,
				Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public", SandboxdKey: keys[i]})
			createMS[i], errs[i] = msOf(time.Since(t0)), err
			if err == nil {
				vms[i] = r.GetVm()
			}
		})
	}
	wg.Wait()
	// A failed run must not leave VMs behind for the next one. ha is the
	// current agent's client (the restart subtest replaces it).
	t.Cleanup(func() {
		cctx, ccancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer ccancel()
		for i, vm := range vms {
			if vm == nil || !alive(vm.GetPid()) {
				continue
			}
			_, _ = ha.Stop(cctx, &pb.StopRequest{SandboxId: ids[i], Attempt: 1, Generation: vm.GetGeneration()})
			killFirecracker(t, vm.GetPid())
		}
	})
	for i, err := range errs {
		if err != nil {
			t.Fatalf("create %d: %v\nagent logs:\n%s", i, err, containerLogs("pt-a1"))
		}
	}
	t.Logf("BENCH create_ms n=%d (all at once) p50=%.1f p95=%.1f max=%.1f", n, pctl(createMS, 0.5), pctl(createMS, 0.95), pctl(createMS, 1))

	// Per VM: CloseConnections, then Init and Run(echo) through the pass-through.
	var closeMS, initMS, runMS, totalMS []float64
	for i := range ids {
		t0 := time.Now()
		if _, err := ha.CloseConnections(ctx, &pb.CloseConnectionsRequest{SandboxId: ids[i], Attempt: 1, Generation: vms[i].GetGeneration()}); err != nil {
			t.Fatalf("vm %d close connections: %v", i, err)
		}
		t1 := time.Now()
		ent := make([]byte, 64)
		_, _ = rand.Read(ent)
		ir, err := sd.Init(vmCtx(ctx, ids[i], keys[i]), &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: ent,
			SandboxId: ids[i], Generation: vms[i].GetGeneration(), SessionIds: []string{"s1"}, ScratchBytes: scratchGiB << 30})
		if err != nil {
			t.Fatalf("vm %d init through the pass-through: %v", i, err)
		}
		t2 := time.Now()
		r, err := ptRun(vmCtx(ctx, ids[i], keys[i]), sd, "echo", "hello")
		t3 := time.Now()
		if err != nil || r.stdout != "hello\n" || r.res.GetExitCode() != 0 {
			t.Fatalf("vm %d run: %v %q %v", i, err, r.stdout, r.res)
		}
		closeMS, initMS, runMS, totalMS = append(closeMS, msOf(t1.Sub(t0))), append(initMS, msOf(t2.Sub(t1))),
			append(runMS, msOf(t3.Sub(t2))), append(totalMS, msOf(t3.Sub(t1)))
		if i == 0 {
			t.Logf("vm 0 init: clock_step=%v entropy_credited=%v attached=%v relay_reset=%v grown=%v", ir.GetClockStep().AsDuration(),
				ir.GetEntropyCredited(), ir.GetAttached(), ir.GetRelayReset(), ir.GetGrown())
			if !ir.GetAttached() || !ir.GetRelayReset() || !ir.GetEntropyCredited() {
				t.Errorf("init steps missing: %+v", ir)
			}
		}
		h, err := sd.Health(vmCtx(ctx, ids[i], keys[i]), &sdpb.HealthRequest{})
		if err != nil || h.GetGeneration() != vms[i].GetGeneration() || h.GetSandboxId() != ids[i] || !h.GetKeySet() {
			t.Fatalf("vm %d health: %v %v", i, h, err)
		}
		if _, err := sd.SetKey(vmCtx(ctx, ids[i], keys[i]), &sdpb.SetKeyRequest{Key: randKey()}); status.Code(err) != codes.PermissionDenied {
			t.Fatalf("vm %d SetKey through the pass-through: %v", i, err)
		}
	}
	t.Logf("BENCH close_connections_ms p50=%.2f p95=%.2f max=%.2f", pctl(closeMS, 0.5), pctl(closeMS, 0.95), pctl(closeMS, 1))
	t.Logf("BENCH pt_init_ms p50=%.2f p95=%.2f max=%.2f", pctl(initMS, 0.5), pctl(initMS, 0.95), pctl(initMS, 1))
	t.Logf("BENCH pt_run_echo_ms p50=%.2f p95=%.2f max=%.2f", pctl(runMS, 0.5), pctl(runMS, 0.95), pctl(runMS, 1))
	t.Logf("BENCH pt_init_plus_run_ms n=%d p50=%.2f p95=%.2f max=%.2f", len(totalMS), pctl(totalMS, 0.5), pctl(totalMS, 0.95), pctl(totalMS, 1))
	gens := map[uint64]bool{}
	for _, vm := range vms {
		gens[vm.GetGeneration()] = true
	}
	t.Logf("generation (host boot ID): %d distinct for %d VMs; each daemon reports its own after Init", len(gens), n)
	if len(gens) != n {
		t.Errorf("generations are not unique")
	}

	// Warm Run latency on the cached connection.
	var warm []float64
	for i := 0; i < 50; i++ {
		t0 := time.Now()
		if _, err := ptRun(vmCtx(ctx, ids[i%n], keys[i%n]), sd, "true"); err != nil {
			t.Fatal(err)
		}
		warm = append(warm, msOf(time.Since(t0)))
	}
	t.Logf("BENCH pt_run_true_warm_ms n=50 p50=%.2f p95=%.2f max=%.2f", pctl(warm, 0.5), pctl(warm, 0.95), pctl(warm, 1))

	v0, k0 := ids[0], keys[0]
	// Resources that outlive a subtest (the second agent's connection) belong to the parent.
	parent := t
	t.Run("start_stream_cancel", func(t *testing.T) {
		st, err := sd.Start(vmCtx(ctx, v0, k0), &sdpb.StartRequest{Command: &sdpb.Command{Argv: []string{"sh", "-c",
			"setsid sleep 4242 & sleep 4242 & echo started; wait"}}})
		if err != nil {
			t.Fatal(err)
		}
		id := st.GetStarted().GetExecutionId()
		s, err := sd.Stream(vmCtx(ctx, v0, k0), &sdpb.StreamRequest{ExecutionId: id})
		if err != nil {
			t.Fatal(err)
		}
		done := make(chan ptResult, 1)
		go func() {
			r, err := ptCollect(s)
			if err != nil {
				t.Errorf("stream: %v", err)
			}
			done <- r
		}()
		time.Sleep(500 * time.Millisecond)
		t0 := time.Now()
		cr, err := sd.Cancel(vmCtx(ctx, v0, k0), &sdpb.CancelRequest{ExecutionId: id})
		if err != nil {
			t.Fatal(err)
		}
		r := <-done
		t.Logf("cancel: %s (completion %s, %d ms); stream got %q and %s", id, cr.GetResult().GetCompletion(),
			time.Since(t0).Milliseconds(), r.stdout, r.res.GetCompletion())
		if r.res.GetCompletion() != sdpb.Completion_CANCELED || !strings.Contains(r.stdout, "started") {
			t.Errorf("stream result %v", r.res)
		}
		left, _ := ptRun(vmCtx(ctx, v0, k0), sd, "sh", "-c", `n=0; for f in /proc/[0-9]*/cmdline; do [ "$(tr '\0' ' ' <$f 2>/dev/null)" = "sleep 4242 " ] && n=$((n+1)); done; echo $n`)
		if strings.TrimSpace(left.stdout) != "0" {
			t.Errorf("%s sleep processes left after cancel", strings.TrimSpace(left.stdout))
		}
	})

	placed := func(id string, gen uint64) error {
		body, _ := json.Marshal(map[string]any{"sandbox_id": id, "tenant_id": "public", "node_id": ptNodeID, "generation": gen})
		req, _ := http.NewRequestWithContext(ctx, http.MethodPut, ptRegURL+"/test/placement", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return err
		}
		_ = resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("placement: HTTP %d", resp.StatusCode)
		}
		return nil
	}
	verified := func(id string, gen uint64) int {
		return countLines(proxy.log, "harness_placement sandbox="+id+" node="+ptNodeID+fmt.Sprintf(" gen=%d placed=True", gen))
	}

	t.Run("egress", func(t *testing.T) {
		if countLines(reg.log, "signing") < 1 {
			t.Logf("reg log has no signing key line yet")
		}
		if err := placed(v0, vms[0].GetGeneration()); err != nil {
			t.Fatal(err)
		}
		r, err := ptRun(vmCtx(ctx, v0, k0), sd, "bash", "-c", egressMatrix)
		if err != nil {
			t.Fatalf("matrix: %v", err)
		}
		pass, total := 0, 0
		for _, l := range strings.Split(r.stdout, "\n") {
			if strings.HasPrefix(l, "MATRIX ") && l != "MATRIX_DONE" {
				total++
				if strings.Contains(l, " OK") {
					pass++
				}
				t.Log(l)
			}
		}
		t.Logf("egress matrix through the Go relay: %d/%d; proxy verified %d signed connections for vm 0", pass, total, verified(v0, vms[0].GetGeneration()))
		if total != 9 || pass != total {
			t.Errorf("matrix %d/%d pass; stderr %s", pass, total, r.stderr)
		}
		// An unplaced VM is refused by the proxy.
		rb, _ := ptRun(vmCtx(ctx, ids[1], keys[1]), sd, "sh", "-c", "curl -sS -o /dev/null -w '%{http_code}' https://pypi.org/simple/ 2>&1; echo")
		t.Logf("unplaced vm 1: %s", strings.TrimSpace(rb.stdout))
		if !strings.Contains(rb.stdout, "403") {
			t.Errorf("unplaced VM was not refused: %q", rb.stdout)
		}
	})

	t.Run("close_connections", func(t *testing.T) {
		if _, err := ptRun(vmCtx(ctx, v0, k0), sd, "sh", "-c", "cat > /tmp/hold.py <<'EOF'\n"+holdPy+"EOF\necho ok"); err != nil {
			t.Fatal(err)
		}
		st, err := sd.Start(vmCtx(ctx, v0, k0), &sdpb.StartRequest{Command: &sdpb.Command{Argv: []string{"python3", "/tmp/hold.py"}}})
		if err != nil {
			t.Fatal(err)
		}
		time.Sleep(2 * time.Second)
		cc, err := ha.CloseConnections(ctx, &pb.CloseConnectionsRequest{SandboxId: v0, Attempt: 1, Generation: vms[0].GetGeneration()})
		if err != nil {
			t.Fatal(err)
		}
		s, err := sd.Stream(vmCtx(ctx, v0, k0), &sdpb.StreamRequest{ExecutionId: st.GetStarted().GetExecutionId()})
		if err != nil {
			t.Fatal(err)
		}
		r, err := ptCollect(s)
		t.Logf("CloseConnections closed %d; guest tunnel: %s", cc.GetClosed(), strings.ReplaceAll(strings.TrimSpace(r.stdout), "\n", " | "))
		ended := strings.Contains(r.stdout, "EOF") || strings.Contains(r.stdout, "ERR")
		if err != nil || cc.GetClosed() < 1 || !strings.Contains(r.stdout, "200") || !ended {
			t.Errorf("tunnel was not closed: %q %v", r.stdout, err)
		}
	})

	// Agent restart with the VMs running: a new agent (same cgroup namespace
	// mode) re-adopts them, and the pass-through works again.
	t.Run("restart", func(t *testing.T) {
		tStop := time.Now()
		if out, err := exec.Command("docker", "stop", "-t", "10", "pt-a1").CombinedOutput(); err != nil {
			t.Fatalf("docker stop: %v: %s", err, out)
		}
		a1 := containerLogs("pt-a1")
		_ = os.WriteFile(filepath.Join(logDir, "pt-a1.log"), []byte(a1), 0o644)
		_ = exec.Command("docker", "rm", "pt-a1").Run()
		aliveN := 0
		for _, vm := range vms {
			if alive(vm.GetPid()) {
				aliveN++
			}
		}
		t.Logf("agent stopped; %d/%d Firecracker processes alive", aliveN, n)
		startPTAgent(t, e, "pt-a2", cgroupns, certDir, certs)
		conn2 := ptConn(parent, ctx, certs, "pt-a2")
		t.Logf("API outage (stop → new agent answers over mTLS): %d ms", time.Since(tStop).Milliseconds())
		ha, sd = pb.NewHostAgentClient(conn2), sdpb.NewSandboxdClient(conn2)
		_, rec := logLine(containerLogs("pt-a2"), "recovered VMs")
		t.Logf("pt-a2: %s", rec)
		l, err := ha.List(ctx, &pb.ListRequest{})
		if err != nil {
			t.Fatal(err)
		}
		adopted := 0
		for _, vm := range l.GetVms() {
			if vm.GetState() == pb.VMState_VM_STATE_RUNNING {
				adopted++
			}
		}
		ok := 0
		var after []float64
		for i := range ids {
			t0 := time.Now()
			r, err := ptRun(vmCtx(ctx, ids[i], keys[i]), sd, "echo", "again")
			if err == nil && r.stdout == "again\n" {
				ok++
				after = append(after, msOf(time.Since(t0)))
			} else {
				t.Errorf("vm %d after restart: %v %q", i, err, r.stdout)
			}
		}
		t.Logf("after restart: adopted %d/%d running, pass-through Run %d/%d (first call p50=%.2f ms p95=%.2f ms)",
			adopted, n, ok, n, pctl(after, 0.5), pctl(after, 0.95))
		if adopted != n || aliveN != n {
			t.Errorf("not every VM was kept and adopted")
		}
		// Egress again, with the new agent's node key.
		before := verified(v0, vms[0].GetGeneration())
		r, _ := ptRun(vmCtx(ctx, v0, k0), sd, "sh", "-c", "curl -sS -o /dev/null -w '%{http_code}' https://pypi.org/simple/six/ 2>&1; echo")
		time.Sleep(500 * time.Millisecond)
		t.Logf("egress after restart: %s, new verified connections %d", strings.TrimSpace(r.stdout), verified(v0, vms[0].GetGeneration())-before)
		if !strings.Contains(r.stdout, "200") {
			t.Errorf("egress after restart failed: %q", r.stdout)
		}
	})

	// Stop during a pass-through call: the agent releases the relay identity
	// and the daemon connection before it kills the VM and frees its UID.
	t.Run("stop_order", func(t *testing.T) {
		s, err := sd.Run(vmCtx(ctx, v0, k0), &sdpb.RunRequest{Command: &sdpb.Command{Argv: []string{"sleep", "60"}}})
		if err != nil {
			t.Fatal(err)
		}
		if _, err := s.Recv(); err != nil {
			t.Fatal(err)
		}
		done := make(chan error, 1)
		go func() { _, err := ptCollect(s); done <- err }()
		t0 := time.Now()
		if _, err := ha.Stop(ctx, &pb.StopRequest{SandboxId: v0, Attempt: 1, Generation: vms[0].GetGeneration()}); err != nil {
			t.Fatal(err)
		}
		stopMS := time.Since(t0).Milliseconds()
		callErr := <-done
		t.Logf("stop %d ms; in-flight Run ended with %v (reason %s)", stopMS, callErr, apierr.FromStatus(callErr))
		if apierr.FromStatus(callErr) != pb.ErrorReason_VM_NOT_RUNNING {
			t.Errorf("in-flight call: %v", callErr)
		}
		logs := containerLogs("pt-a2")
		iRel, lRel := logLine(logs, `"msg":"released VM identity","sandbox_id":"`+v0)
		iStop, lStop := logLine(logs, `"msg":"stopped","sandbox_id":"`+v0)
		t.Logf("agent log: %s", lRel)
		t.Logf("agent log: %s", lStop)
		if iRel < 0 || iStop < 0 || iRel > iStop {
			t.Errorf("release (line %d) not before stopped (line %d)", iRel, iStop)
		}
		if alive(vms[0].GetPid()) {
			t.Errorf("VM process still alive after Stop")
		}
		_, err = sd.Health(vmCtx(ctx, v0, k0), &sdpb.HealthRequest{})
		t.Logf("pass-through after Stop: %s", apierr.FromStatus(err))
		if apierr.FromStatus(err) != pb.ErrorReason_SANDBOX_NOT_FOUND {
			t.Errorf("pass-through after Stop: %v", err)
		}
	})

	for i := 1; i < n; i++ {
		if _, err := ha.Stop(ctx, &pb.StopRequest{SandboxId: ids[i], Attempt: 1, Generation: vms[i].GetGeneration()}); err != nil {
			t.Errorf("stop %d: %v", i, err)
		}
	}
	left := 0
	for _, vm := range vms {
		if alive(vm.GetPid()) {
			left++
		}
	}
	t.Logf("stopped all VMs; %d Firecracker processes left", left)
	a2 := containerLogs("pt-a2")
	_ = os.WriteFile(filepath.Join(logDir, "pt-a2.log"), []byte(a2), 0o644)
}

// holdPy opens a CONNECT tunnel and waits for the relay to close it.
const holdPy = `import socket, time
s = socket.create_connection(("127.0.0.1", 3128))
s.sendall(b"CONNECT pypi.org:443 HTTP/1.1\r\nHost: pypi.org:443\r\n\r\n")
print(s.recv(200).split(b"\r\n")[0].decode(), flush=True)
s.settimeout(90)
t = time.time()
try:
    d = s.recv(1)
    print("EOF" if d == b"" else "DATA", round(time.time() - t, 2), flush=True)
except Exception as e:
    print("ERR", type(e).__name__, round(time.time() - t, 2), flush=True)
`

// killFirecracker kills pid if it is still a Firecracker process (test
// cleanup after a failed Stop).
func killFirecracker(t *testing.T, pid int32) {
	t.Helper()
	comm, err := os.ReadFile(fmt.Sprintf("/proc/%d/comm", pid))
	if err != nil || strings.TrimSpace(string(comm)) != "firecracker" {
		return
	}
	if err := syscall.Kill(int(pid), syscall.SIGKILL); err != nil {
		t.Logf("kill firecracker %d: %v", pid, err)
	}
}

// chartMode runs the agent from KVM_AGENT_IMAGE the way the Helm chart does
// (KVM_AGENT_CHART=1).
func chartMode() bool { return os.Getenv("KVM_AGENT_CHART") == "1" }
