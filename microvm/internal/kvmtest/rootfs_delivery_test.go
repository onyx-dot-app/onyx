//go:build kvm && linux

package kvmtest

import (
	"context"
	"crypto/rand"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	"github.com/onyx-dot-app/onyx/microvm/internal/tplbuild"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// Guest checks through the egress relay (HTTPS_PROXY=127.0.0.1:3128 from guest.env).
const (
	rdCurl = `curl -sS --max-time 30 https://example.com/ 2>&1; echo "rc=$?"`
	rdPy   = `for p in /opt/onyx/python/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do [ -x $p ] && exec $p -c 'import urllib.request; print(urllib.request.urlopen("https://pypi.org/", timeout=30).read().decode().strip())' 2>&1; done; echo no python`
	rdNode = `node -e 'fetch("https://registry.npmjs.org/").then(r=>r.text()).then(t=>console.log(t.trim())).catch(e=>{console.log(String(e.cause||e));process.exit(1)})' 2>&1; echo "rc=$?"`
	rdNSS  = `certutil -L -d sql:/home/sandbox/.pki/nssdb 2>&1 | grep -c craft-egress-ca; stat -c 'owner=%U' /home/sandbox/.pki/nssdb/cert9.db`
	// The default root drive runs commands as the sandbox user, not root.
	rdUser = `echo "uid=$(id -u) gid=$(id -g) home=$HOME user=$USER"; touch ws-probe && echo ws-ok; touch /tmp/probe && echo tmp-ok; touch /usr/local/share/ca-certificates/probe 2>/dev/null || echo ca-store-denied; pwd`
)

// TestRootfsDeliveryKVM checks rootfs delivery through the agent binary: the root
// drive image installs into --rootfs-dir like the Helm init container, the
// agent builds a template from that CA-free drive, and each VM trusts the
// deployment CA that the agent sends with SetKey, and no other. A second
// deployment CA keeps the same template.
//
// Inputs: KVM_RD_IMAGE (the root drive image, Dockerfile.image), KVM_RD_DIR
// (a work dir the agent container can mount), and the template build inputs
// (KVM_AGENT_BIN, KVM_AGENT_IMAGE, KVM_DATA_DIR, KVM_ARTIFACTS_DIR).
func TestRootfsDeliveryKVM(t *testing.T) {
	e := loadEnv()
	_ = newCommand(t, e)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
	defer cancel()
	image := getenv("KVM_RD_IMAGE", "craft-fc-rootfs:dev")
	work := getenv("KVM_RD_DIR", "/opt/rd/work")
	rootfsDir := filepath.Join(e.DataDir, "rootfs")
	tplDir := filepath.Join(e.DataDir, "templates")
	_ = exec.Command("docker", "rm", "-f", "rd-a1", "rd-a2").Run()
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", "rd-a1", "rd-a2").Run() })
	for _, d := range []string{tplDir, rootfsDir, work} {
		if err := os.RemoveAll(d); err != nil {
			t.Fatal(err)
		}
	}
	certDir := filepath.Join(work, "certs")
	caDir := filepath.Join(work, "ca")
	for _, d := range []string{certDir, caDir} {
		if err := os.MkdirAll(d, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	certs, err := testcerts.Write(certDir)
	if err != nil {
		t.Fatal(err)
	}

	// 1. The init container step: copy, then nothing on a second run.
	install := func() string {
		out, err := exec.Command("docker", "run", "--rm", "-v", e.DataDir+":"+e.DataDir, image, rootfsDir).CombinedOutput()
		if err != nil {
			t.Fatalf("install: %v: %s", err, out)
		}
		return strings.TrimSpace(string(out))
	}
	t0 := time.Now()
	first := install()
	t.Logf("BENCH rootfs_install_ms=%d: %s", time.Since(t0).Milliseconds(), first)
	t0 = time.Now()
	second := install()
	t.Logf("BENCH rootfs_install_again_ms=%d: %s", time.Since(t0).Milliseconds(), second)
	if !strings.Contains(first, "installed in "+rootfsDir) || !strings.Contains(second, "is current") {
		t.Fatalf("install output: %q / %q", first, second)
	}
	rf, err := tplbuild.LoadRootfs(rootfsDir)
	if err != nil {
		t.Fatal(err)
	}
	if rf.CAFingerprint() != "" {
		t.Fatalf("the published root drive has a CA: %s", rf.CAFingerprint())
	}
	t.Logf("root drive: source %s, sha256 %s", rf.Manifest.SourceImage.Pinned, rf.Manifest.Output.SHA256[:16])

	// 2. A TLS-intercepting proxy, like sandbox-proxy, as the agent's --egress-proxy.
	ca1, err := testcerts.NewCA("deployment-one")
	if err != nil {
		t.Fatal(err)
	}
	ca2, err := testcerts.NewCA("deployment-two")
	if err != nil {
		t.Fatal(err)
	}
	ca1File, ca2File := filepath.Join(caDir, "one.crt"), filepath.Join(caDir, "two.crt")
	for f, ca := range map[string]*testcerts.CA{ca1File: ca1, ca2File: ca2} {
		if err := os.WriteFile(f, ca.PEM, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close() }()
	mitm := testcerts.NewMITM(ca1)
	go mitm.Serve(ln)
	egress := []string{"--egress-proxy", ln.Addr().String(), "--node-id", "kvm-rd-node"}

	type vmRef struct {
		id, key string
		gen     uint64
	}
	var sd sdpb.SandboxdClient
	var ha pb.HostAgentClient
	agentName := "rd-a1"
	createInit := func(tpl string) vmRef {
		t.Helper()
		v := vmRef{id: newUUID(), key: randKey()}
		r, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: v.id, Attempt: 1, Template: tpl, Vcpus: tplVCPUs,
			MemMib: tplMemMiB, ScratchGib: tplScratchGiB, TenantId: "public", SandboxdKey: v.key})
		if err != nil {
			t.Fatalf("create: %v", err)
		}
		v.gen = r.GetVm().GetGeneration()
		ent := make([]byte, 64)
		_, _ = rand.Read(ent)
		ir, err := sd.Init(vmCtx(ctx, v.id, v.key), &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: ent,
			SandboxId: v.id, Generation: v.gen, ScratchBytes: tplScratchGiB << 30})
		if err != nil || !ir.GetAttached() || !ir.GetEgressCaInstalled() {
			t.Fatalf("init: %v %v", ir, err)
		}
		return v
	}
	expect := func(v vmRef, what, script, want string, ok bool) {
		t.Helper()
		r, err := ptRun(vmCtx(ctx, v.id, v.key), sd, "bash", "-lc", script)
		if err != nil {
			t.Fatalf("%s: %v", what, err)
		}
		t.Logf("%s: %s", what, strings.ReplaceAll(strings.TrimSpace(r.stdout), "\n", " | "))
		if strings.Contains(r.stdout, want) != ok {
			logs := containerLogs(agentName)
			t.Errorf("%s: want %q present=%v, got %q\nagent log tail:\n%s", what, want, ok, r.stdout, logs[max(0, len(logs)-4000):])
		}
	}
	stop := func(v vmRef) {
		if _, err := ha.Stop(ctx, &pb.StopRequest{SandboxId: v.id, Attempt: 1, Generation: v.gen}); err != nil {
			t.Errorf("stop: %v", err)
		}
	}

	// 3. Deployment one: build the template, then a VM that trusts CA 1.
	startTBAgent(t, e, "rd-a1", rootfsDir, ca1File, certDir, certs, egress...)
	conn := ptConn(t, ctx, certs, "rd-a1")
	ha, sd = pb.NewHostAgentClient(conn), sdpb.NewSandboxdClient(conn)
	br, err := ha.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
	if err != nil {
		t.Fatalf("build: %v\n%s", err, containerLogs("rd-a1"))
	}
	tpl := br.GetTemplate()
	t.Logf("BENCH template_build_ms=%d built=%v template=%s ca=%q", br.GetBuildMs(), br.GetBuilt(), tpl.GetVersion(), tpl.GetCaFingerprint())
	if tpl.GetCaFingerprint() != "" || !tpl.GetCompatible() {
		t.Fatalf("template %v", tpl)
	}
	v1 := createInit(tpl.GetVersion())
	expect(v1, "curl, CA 1", rdCurl, "mitm-ok deployment-one example.com", true)
	expect(v1, "python, CA 1", rdPy, "mitm-ok deployment-one pypi.org", true)
	expect(v1, "node, CA 1", rdNode, "mitm-ok deployment-one registry.npmjs.org", true)
	expect(v1, "NSS database", rdNSS, "1\nowner=sandbox", true)
	expect(v1, "curl again", rdCurl, "mitm-ok deployment-one", true)
	sessionID := newUUID()
	r, err := sd.Run(vmCtx(ctx, v1.id, v1.key), &sdpb.RunRequest{Command: &sdpb.Command{Argv: []string{"bash", "-c", rdUser}, SessionId: sessionID}})
	if err != nil {
		t.Fatalf("command user: %v", err)
	}
	ur, err := ptCollect(r)
	want := fmt.Sprintf("uid=1000 gid=1000 home=/home/sandbox user=sandbox\nws-ok\ntmp-ok\nca-store-denied\n/home/onyx/workspaces/%s\n", sessionID)
	if err != nil || ur.stdout != want {
		t.Errorf("command user: got %q %v, want %q (stderr %q)", ur.stdout, err, want, ur.stderr)
	}
	mitm.SetCA(ca2)
	expect(v1, "VM 1 refuses CA 2", rdCurl, "mitm-ok", false)
	mitm.SetCA(ca1)
	stop(v1)
	_ = conn.Close()
	if out, err := exec.Command("docker", "rm", "-f", "rd-a1").CombinedOutput(); err != nil {
		t.Fatalf("stop agent 1: %v %s", err, out)
	}

	// 4. Deployment two, same root drive: the same template, and a VM that
	// trusts CA 2 and not CA 1.
	agentName = "rd-a2"
	startTBAgent(t, e, "rd-a2", rootfsDir, ca2File, certDir, certs, egress...)
	conn = ptConn(t, ctx, certs, "rd-a2")
	ha, sd = pb.NewHostAgentClient(conn), sdpb.NewSandboxdClient(conn)
	br2, err := ha.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
	if err != nil || br2.GetBuilt() || br2.GetTemplate().GetVersion() != tpl.GetVersion() {
		t.Fatalf("build with CA 2: %v %v (want template %s kept)", br2, err, tpl.GetVersion())
	}
	t.Logf("CA 2 agent: template %s kept (built=%v)", br2.GetTemplate().GetVersion(), br2.GetBuilt())
	v2 := createInit(tpl.GetVersion())
	expect(v2, "VM 2 refuses CA 1", rdCurl, "mitm-ok", false)
	mitm.SetCA(ca2)
	expect(v2, "curl, CA 2", rdCurl, "mitm-ok deployment-two example.com", true)
	expect(v2, "one egress CA in the stores", `grep -c BEGIN /usr/local/share/ca-certificates/craft-egress-ca.crt; `+rdNSS, "1\n1\nowner=sandbox", true)
	stop(v2)
	t.Logf("proxy answered %d HTTPS requests", mitm.Requests.Load())
}
