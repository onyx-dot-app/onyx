//go:build kvm && linux

package kvmtest

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/hostinfo"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
	"github.com/onyx-dot-app/onyx/microvm/internal/relay"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
)

// The matrix runs as the sandbox user with the proxy env of the prototype
// guest agent (HTTP(S)_PROXY=http://127.0.0.1:3128, NODE_USE_ENV_PROXY=1, CA vars).
const egressMatrix = `W=/tmp/m; rm -rf $W; mkdir -p $W
run() { n=$1; shift; if out=$(timeout 180 "$@" 2>&1); then echo "MATRIX $n OK $(echo "$out" | tail -1)"; else echo "MATRIX $n FAIL $(echo "$out" | tail -3 | tr '\n' ' ')"; fi; }
run curl_https curl -sSf -o /dev/null -w '%{http_code}' https://www.google.com/
run curl_http_x2 curl -sSf -o /dev/null -o /dev/null -w '%{http_code} connects=%{num_connects} ' http://example.com/ http://example.com/
run curl_forged_auth curl -sSf -o /dev/null -w '%{http_code}' --proxy-header 'Proxy-Authorization: Bearer forged-by-vm' https://www.google.com/
run curl_session_hint curl -sSf -o /dev/null -w '%{http_code}' -x http://sess-kvm-1:x@127.0.0.1:3128 https://www.google.com/
run setup_venv bash -c "python3 -m venv $W/v && $W/v/bin/pip install -q --no-cache-dir requests six==1.16.0 && echo ok"
run python_requests $W/v/bin/python -c "import requests;s=requests.Session();print([s.get('https://pypi.org/simple/six/').status_code for _ in range(2)])"
run node_fetch node -e "(async()=>{for(let i=0;i<2;i++){const r=await fetch('https://pypi.org/simple/six/');await r.text();console.log(r.status)}})().catch(e=>{console.error(e.cause||e);process.exit(1)})"
run pip_install $W/v/bin/pip install -q --no-cache-dir --force-reinstall six==1.16.0
run git_clone git clone -q --depth 1 https://github.com/octocat/Hello-World.git $W/g
echo MATRIX_DONE`

// holdTunnel opens a CONNECT tunnel and waits for the relay to close it.
const holdTunnel = `cat > /tmp/hold.py <<'EOF'
import socket, time
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
EOF
setsid nohup python3 /tmp/hold.py > /tmp/hold.out 2>&1 < /dev/null & echo HOLD_STARTED`

type service struct {
	name string
	cmd  *exec.Cmd
	log  string
}

func startService(t *testing.T, name, logPath string, env []string, argv ...string) *service {
	t.Helper()
	f, err := os.Create(logPath)
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Env = append(os.Environ(), env...)
	cmd.Stdout, cmd.Stderr = f, f
	cmd.Dir = getenv("KVM_PR_BACKEND", "/opt/pr/backend")
	if err := cmd.Start(); err != nil {
		t.Fatalf("start %s: %v", name, err)
	}
	s := &service{name: name, cmd: cmd, log: logPath}
	t.Cleanup(func() { _ = cmd.Process.Kill(); _, _ = cmd.Process.Wait(); _ = f.Close() })
	return s
}

func waitTCP(t *testing.T, ctx context.Context, addr string, s *service) {
	t.Helper()
	for {
		c, err := net.Dial("tcp", addr)
		if err == nil {
			_ = c.Close()
			return
		}
		select {
		case <-ctx.Done():
			raw, _ := os.ReadFile(s.log)
			t.Fatalf("%s did not listen on %s: %v\n%s", s.name, addr, err, raw)
		case <-time.After(50 * time.Millisecond):
		}
	}
}

func countLines(path, substr string) int {
	raw, _ := os.ReadFile(path)
	n := 0
	for _, l := range strings.Split(string(raw), "\n") {
		if strings.Contains(l, substr) {
			n++
		}
	}
	return n
}

func TestEgressKVM(t *testing.T) {
	e := loadEnv()
	cmd := newCommand(t, e)
	buildTemplate(t, &e, cmd)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Minute)
	defer cancel()
	logDir := getenv("KVM_LOG_DIR", "/var/log/bench")
	py := getenv("KVM_PYTHON", "/opt/proxy/venv/bin/python")
	harness := getenv("KVM_HARNESS_DIR", "/opt/harness")
	const secret = "kvm-registration-secret-1"
	const nodeID = "kvm-node-1"

	_ = exec.Command("docker", "rm", "-f", "kvm-redis").Run()
	if out, err := exec.Command("docker", "run", "-d", "--rm", "--name", "kvm-redis", "--network", "host", "redis:7-alpine").CombinedOutput(); err != nil {
		t.Fatalf("redis: %v %s", err, out)
	}
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", "kvm-redis").Run() })
	env := []string{"SANDBOX_RUNTIME=firecracker", "CACHE_BACKEND=redis", "REDIS_HOST=127.0.0.1", "REDIS_PORT=6379",
		"MULTI_TENANT=false", "LOG_LEVEL=debug", "SANDBOX_NODE_REGISTRATION_SECRET=" + secret, "PYTHONPATH=" + getenv("KVM_PR_BACKEND", "/opt/pr/backend")}
	confdir := filepath.Join(t.TempDir(), "confdir")
	reg := startService(t, "reg_server", filepath.Join(logDir, "egress-reg.log"), env, py, filepath.Join(harness, "reg_server.py"))
	proxy := startService(t, "gate_proxy", filepath.Join(logDir, "egress-proxy.log"), append(env, "HARNESS_CONFDIR="+confdir), py, filepath.Join(harness, "gate_proxy.py"))
	waitTCP(t, ctx, "127.0.0.1:8095", reg)
	waitTCP(t, ctx, "127.0.0.1:8099", proxy)
	// mitmproxy can listen before it has written its CA files.
	var ca []byte
	for {
		var err error
		if ca, err = os.ReadFile(filepath.Join(confdir, "mitmproxy-ca-cert.pem")); err == nil && len(ca) > 0 {
			break
		}
		select {
		case <-ctx.Done():
			t.Fatalf("no proxy CA: %v", err)
		case <-time.After(50 * time.Millisecond):
		}
	}

	// The agent with the relay and a fresh node key, registered through the PR route.
	_, key, _ := ed25519.GenerateKey(nil)
	signer := relay.NewSigner(nodeID, fmt.Sprintf("%s-%d", nodeID, time.Now().Unix()), key)
	log := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelWarn}))
	rl := &relay.Relay{Signer: signer, Upstream: "127.0.0.1:8099", Log: log}
	g := &relay.Registrar{BaseURL: "http://127.0.0.1:8095", Secret: secret, Signer: signer, Log: log}
	if err := g.Register(ctx); err != nil {
		t.Fatalf("register node key: %v", err)
	}
	bad := &relay.Registrar{BaseURL: "http://127.0.0.1:8095", Secret: "wrong", Signer: signer, Log: log}
	if err := bad.Register(ctx); err == nil {
		t.Fatal("registration with a wrong secret succeeded")
	}
	t.Logf("node key %s registered (wrong secret rejected)", signer.KeyID)

	uids, _ := jailer.NewUIDPool(uidBase, 65536)
	m := agent.NewManager(agent.Config{MinFreeMemMiB: 2048, MinFreeDiskBytes: 10 * uint64(scratch.GiB), MaxScratchGiB: 100,
		StartTimeout: time.Minute, StopTimeout: 30 * time.Second, TombstoneTTL: time.Hour},
		&template.Store{Dir: filepath.Join(e.DataDir, "templates")}, &fcvm.Launcher{Cmd: cmd, Log: log},
		hostinfo.Stats{DataDir: e.DataDir}, uids, kvmVersions(t, e), log)
	m.UseEgress(&relay.AgentEgress{Relay: rl})
	jdir := t.TempDir()
	m.UseJournal(&journal.Journal{Dir: jdir})
	mk := func() agent.VM {
		vm, _, err := m.Create(ctx, agent.CreateRequest{SandboxID: newUUID(), Attempt: 1, Template: e.Template,
			VCPUs: tplVCPUs, MemMiB: tplMemMiB, ScratchGiB: tplScratchGiB, TenantID: "public"})
		if err != nil {
			t.Fatal(err)
		}
		return vm
	}
	a, b := mk(), mk()
	defer func() {
		for _, vm := range []agent.VM{a, b} {
			_, _ = m.Stop(context.Background(), vm.SandboxID, vm.Attempt, vm.Generation)
		}
	}()
	// Placement for A only (the api_server writes it in production).
	body, _ := json.Marshal(map[string]any{"sandbox_id": a.SandboxID, "tenant_id": "public", "node_id": nodeID, "generation": a.Generation})
	req, _ := http.NewRequestWithContext(ctx, http.MethodPut, "http://127.0.0.1:8095/test/placement", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil || resp.StatusCode != 200 {
		t.Fatalf("placement: %v %v", resp, err)
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	_ = resp.Body.Close()

	lay := cmd.Layout
	va, vb := lay.HostPath(a.SandboxID, template.VsockUDS), lay.HostPath(b.SandboxID, template.VsockUDS)
	for _, v := range []string{va, vb} {
		if _, err := guestCmd(ctx, v, fmt.Sprintf("settime %d", time.Now().UnixNano())); err != nil {
			t.Fatal(err)
		}
		out, err := guestCmd(ctx, v, "netsetup "+base64.StdEncoding.EncodeToString(ca))
		if err != nil || !strings.Contains(out, "NETSETUP_OK") {
			t.Fatalf("netsetup: %q %v", out, err)
		}
	}

	out, err := guestRun(ctx, va, "run", egressMatrix)
	if err != nil {
		t.Fatalf("matrix: %v", err)
	}
	pass, total := 0, 0
	for _, l := range strings.Split(out, "\n") {
		if strings.HasPrefix(l, "MATRIX ") && l != "MATRIX_DONE" {
			total++
			if strings.Contains(l, " OK") {
				pass++
			}
			t.Log(l)
		}
	}
	if total != 9 || pass != total {
		t.Errorf("matrix %d/%d pass", pass, total)
	}

	// B has no placement record: the proxy must refuse it.
	outB, _ := guestRun(ctx, vb, "run", "curl -sS -o /dev/null -w '%{http_code}' https://www.google.com/ 2>&1; echo")
	t.Logf("unplaced VM: %s", strings.TrimSpace(outB))
	if !strings.Contains(outB, "403") {
		t.Errorf("unplaced VM was not refused: %q", outB)
	}

	// CloseConnections closes a live tunnel; the guest sees it at once.
	if out, err := guestRun(ctx, va, "run", holdTunnel); err != nil || !strings.Contains(out, "HOLD_STARTED") {
		t.Fatalf("hold: %q %v", out, err)
	}
	time.Sleep(2 * time.Second)
	closed, err := m.CloseConnections(a.SandboxID, a.Attempt, a.Generation)
	if err != nil || closed < 1 {
		t.Errorf("close connections: %d %v", closed, err)
	}
	time.Sleep(time.Second)
	hold, _ := guestRun(ctx, va, "run", "cat /tmp/hold.out")
	t.Logf("CloseConnections closed %d; guest tunnel: %s", closed, strings.ReplaceAll(strings.TrimSpace(hold), "\n", " | "))
	if !strings.Contains(hold, "200") || !(strings.Contains(hold, "EOF") || strings.Contains(hold, "ERR")) {
		t.Errorf("tunnel was not closed: %q", hold)
	}

	// The proxy resolved the signed identity.
	time.Sleep(500 * time.Millisecond)
	verifiedA := countLines(proxy.log, "harness_placement sandbox="+a.SandboxID+" node="+nodeID+fmt.Sprintf(" gen=%d placed=True", a.Generation))
	refusedB := countLines(proxy.log, "harness_placement sandbox="+b.SandboxID) - countLines(proxy.log, "harness_placement sandbox="+b.SandboxID+" node="+nodeID+fmt.Sprintf(" gen=%d placed=True", b.Generation))
	verifiedLog := countLines(proxy.log, "identity_signed_verified tenant=public sandbox="+a.SandboxID)
	rejectedA := 0
	raw, _ := os.ReadFile(proxy.log)
	for _, l := range strings.Split(string(raw), "\n") {
		if strings.Contains(l, "identity_signed_rejected") && !strings.Contains(l, "not_placed") {
			rejectedA++
		}
	}
	notPlaced := countLines(proxy.log, "identity_signed_rejected reason=not_placed")
	t.Logf("proxy: %d signed connections verified and placed for A (%d identity_signed_verified lines), %d not placed for B (%d not_placed rejections), %d other rejections",
		verifiedA, verifiedLog, refusedB, notPlaced, rejectedA)
	if verifiedA < 9 || refusedB < 1 || rejectedA != 0 {
		t.Errorf("proxy identity checks failed; see %s", proxy.log)
	}
	if countLines(reg.log, "sandbox_node_signing_key_registered node="+nodeID) < 1 {
		t.Errorf("registration not logged by the api route; see %s", reg.log)
	}

	// Agent restart: a new process (new Manager, new relay, new key) adopts
	// the VMs from the journal and re-attaches their egress.
	rl.Detach(a.SandboxID)
	rl.Detach(b.SandboxID)
	_, key2, _ := ed25519.GenerateKey(nil)
	signer2 := relay.NewSigner(nodeID, fmt.Sprintf("%s-%d-2", nodeID, time.Now().Unix()), key2)
	if err := (&relay.Registrar{BaseURL: "http://127.0.0.1:8095", Secret: secret, Signer: signer2, Log: log}).Register(ctx); err != nil {
		t.Fatalf("register second key: %v", err)
	}
	uids2, _ := jailer.NewUIDPool(uidBase, 65536)
	m2 := agent.NewManager(agent.Config{MinFreeMemMiB: 2048, MinFreeDiskBytes: 10 * uint64(scratch.GiB), MaxScratchGiB: 100,
		StartTimeout: time.Minute, StopTimeout: 30 * time.Second, TombstoneTTL: time.Hour},
		&template.Store{Dir: filepath.Join(e.DataDir, "templates")}, &fcvm.Launcher{Cmd: cmd, Log: log},
		hostinfo.Stats{DataDir: e.DataDir}, uids2, kvmVersions(t, e), log)
	m2.UseJournal(&journal.Journal{Dir: jdir})
	m2.UseEgress(&relay.AgentEgress{Relay: &relay.Relay{Signer: signer2, Upstream: "127.0.0.1:8099", Log: log}})
	rep, err := m2.Recover(ctx, &fcvm.Launcher{Cmd: cmd, Log: log})
	if err != nil || rep.Adopted != 2 {
		t.Fatalf("recover: %+v %v", rep, err)
	}
	m = m2
	before := countLines(proxy.log, "harness_placement sandbox="+a.SandboxID+" node="+nodeID+fmt.Sprintf(" gen=%d placed=True", a.Generation))
	out2, _ := guestRun(ctx, va, "run", "curl -sS -o /dev/null -w '%{http_code}' https://www.google.com/ 2>&1; echo")
	time.Sleep(500 * time.Millisecond)
	after := countLines(proxy.log, "harness_placement sandbox="+a.SandboxID+" node="+nodeID+fmt.Sprintf(" gen=%d placed=True", a.Generation))
	t.Logf("after agent restart (key %s): curl %s, new verified connections %d", signer2.KeyID, strings.TrimSpace(out2), after-before)
	if !strings.Contains(out2, "200") || after <= before {
		t.Errorf("egress after adopt failed: %q", out2)
	}
}
