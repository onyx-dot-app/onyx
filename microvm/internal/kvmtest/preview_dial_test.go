//go:build kvm && linux

package kvmtest

import (
	"context"
	"crypto/rand"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

const previewGet = "GET /index.html HTTP/1.0\r\nHost: localhost\r\n\r\n"

// TestPreviewDialKVM checks the app preview path on the production root
// drive image: the agent sends its --dial-ports with SetKey, and the guest
// daemon forwards exactly those ports to 127.0.0.1, where a web server of
// the sandbox user listens.
//
// Inputs: KVM_RD_IMAGE (the root drive image, Dockerfile.image), KVM_RD_DIR,
// the template build inputs, and optional KVM_DAEMON_VERSION (the version
// that the daemon must report).
func TestPreviewDialKVM(t *testing.T) {
	e := loadEnv()
	cmd := newCommand(t, e)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
	defer cancel()
	image := getenv("KVM_RD_IMAGE", "craft-fc-rootfs:dev")
	work := getenv("KVM_RD_DIR", "/opt/rd/work")
	rootfsDir := filepath.Join(e.DataDir, "rootfs")
	const agentName = "pd-a1"
	_ = exec.Command("docker", "rm", "-f", agentName).Run()
	t.Cleanup(func() { _ = exec.Command("docker", "rm", "-f", agentName).Run() })
	for _, d := range []string{filepath.Join(e.DataDir, "templates"), rootfsDir, work} {
		if err := os.RemoveAll(d); err != nil {
			t.Fatal(err)
		}
	}
	certDir, caDir := filepath.Join(work, "certs"), filepath.Join(work, "ca")
	for _, d := range []string{certDir, caDir} {
		if err := os.MkdirAll(d, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	certs, err := testcerts.Write(certDir)
	if err != nil {
		t.Fatal(err)
	}
	ca, err := testcerts.NewCA("preview-dial")
	if err != nil {
		t.Fatal(err)
	}
	caFile := filepath.Join(caDir, "ca.crt")
	if err := os.WriteFile(caFile, ca.PEM, 0o644); err != nil {
		t.Fatal(err)
	}
	if out, err := exec.Command("docker", "run", "--rm", "-v", e.DataDir+":"+e.DataDir, image, rootfsDir).CombinedOutput(); err != nil {
		t.Fatalf("install the root drive: %v: %s", err, out)
	}

	startTBAgent(t, e, agentName, rootfsDir, caFile, certDir, certs, "--dial-ports", "3010,3011")
	conn := ptConn(t, ctx, certs, agentName)
	ha, sd := pb.NewHostAgentClient(conn), sdpb.NewSandboxdClient(conn)
	br, err := ha.BuildTemplate(ctx, &pb.BuildTemplateRequest{})
	if err != nil {
		t.Fatalf("build: %v\n%s", err, containerLogs(agentName))
	}
	id, key := newUUID(), randKey()
	r, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: id, Attempt: 1, Template: br.GetTemplate().GetVersion(), Vcpus: tplVCPUs,
		MemMib: tplMemMiB, ScratchGib: tplScratchGiB, TenantId: "public", SandboxdKey: key})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	gen := r.GetVm().GetGeneration()
	defer func() {
		_, _ = ha.Stop(context.Background(), &pb.StopRequest{SandboxId: id, Attempt: 1, Generation: gen})
	}()
	vctx := vmCtx(ctx, id, key)
	ent := make([]byte, 64)
	_, _ = rand.Read(ent)
	ir, err := sd.Init(vctx, &sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: ent, SandboxId: id, Generation: gen,
		ScratchBytes: tplScratchGiB << 30})
	if err != nil {
		t.Fatalf("init: %v", err)
	}
	h, err := sd.Health(vctx, &sdpb.HealthRequest{})
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("daemon version: Init %q, Health %q; dial_ports %v", ir.GetVersion(), h.GetVersion(), h.GetDialPorts())
	if want := os.Getenv("KVM_DAEMON_VERSION"); want != "" && (h.GetVersion() != want || ir.GetVersion() != want) {
		t.Errorf("daemon version: want %q, got Health %q Init %q", want, h.GetVersion(), ir.GetVersion())
	}
	if !slices.Equal(h.GetDialPorts(), []uint32{3010, 3011}) {
		t.Fatalf("Health.dial_ports: %v", h.GetDialPorts())
	}

	// Web servers of the sandbox user on 127.0.0.1: an allowed port and a
	// port that the agent does not allow.
	if out, err := ptRun(vctx, sd, "bash", "-c",
		`mkdir -p /tmp/www && echo preview-ok > /tmp/www/index.html && chmod -R a+rX /tmp/www && echo OK`); err != nil || !strings.Contains(out.stdout, "OK") {
		t.Fatalf("page: %v %v", out, err)
	}
	for _, port := range []string{"3010", "3012"} {
		if _, err := sd.Start(vctx, &sdpb.StartRequest{Command: &sdpb.Command{Argv: []string{"runuser", "-u", "sandbox", "--",
			"bash", "-c", "for p in /opt/onyx/python/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do [ -x $p ] && exec $p -m http.server " +
				port + " --bind 127.0.0.1 --directory /tmp/www; done; exit 127"}}}); err != nil {
			t.Fatalf("start server %s: %v", port, err)
		}
	}
	page := ""
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		if page, err = dialOnce(ctx, ha, id, 3010, previewGet); err == nil && strings.Contains(page, "preview-ok") {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}
	if !strings.HasPrefix(page, "HTTP/1.0 200") || !strings.Contains(page, "preview-ok") {
		t.Fatalf("dial 3010: %q %v\n%s", page, err, containerLogs(agentName))
	}
	t.Logf("Dial 3010: %s ... preview-ok", strings.SplitN(page, "\r\n", 2)[0])
	if out, err := ptRun(vctx, sd, "bash", "-c", `ps -o user=,args= -C python3 | grep http.server | sort`); err == nil {
		t.Logf("guest servers: %s", strings.ReplaceAll(strings.TrimSpace(out.stdout), "\n", " | "))
		if strings.Contains(out.stdout, "root") || !strings.Contains(out.stdout, "sandbox") {
			t.Errorf("the servers do not run as the sandbox user: %q", out.stdout)
		}
	}

	// Parallel streams, then timing.
	var wg sync.WaitGroup
	errs := make(chan error, 16)
	for i := range 16 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if out, err := dialOnce(ctx, ha, id, 3010, previewGet); err != nil || !strings.Contains(out, "preview-ok") {
				errs <- fmt.Errorf("parallel dial %d: %q %v", i, out, err)
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Error(err)
	}
	var lat []float64
	for i := range 20 {
		s := time.Now()
		if out, err := dialOnce(ctx, ha, id, 3010, previewGet); err != nil || !strings.Contains(out, "preview-ok") {
			t.Fatalf("dial 3010 #%d: %q %v", i, out, err)
		}
		lat = append(lat, msOf(time.Since(s)))
	}
	t.Logf("BENCH dial_get_ms p50=%.2f p95=%.2f max=%.2f (20 calls)", pctl(lat, 0.5), pctl(lat, 0.95), pctl(lat, 1))

	// Refused: a port off the agent's list, also with a server behind it,
	// and the daemon port.
	for _, port := range []uint32{3012, 52} {
		if _, err := dialOnce(ctx, ha, id, port, previewGet); apierr.FromStatus(err) != pb.ErrorReason_PORT_NOT_ALLOWED {
			t.Errorf("dial %d: want PORT_NOT_ALLOWED, got %v", port, err)
		} else {
			t.Logf("dial %d refused: %v", port, err)
		}
	}
	// An allowed port with no server: the stream ends with no bytes.
	if out, err := dialOnce(ctx, ha, id, 3011, previewGet); out != "" {
		t.Errorf("dial 3011 with no server: %q %v", out, err)
	} else {
		t.Logf("dial 3011 with no server: empty stream (%v)", err)
	}
	// The guest has no vsock listener on 3012: a direct vsock connect fails.
	uds := cmd.Layout.HostPath(id, template.VsockUDS)
	dctx, dcancel := context.WithTimeout(ctx, 5*time.Second)
	defer dcancel()
	if c, err := fcvm.DialVsock(dctx, uds, 3012); err == nil {
		_ = c.Close()
		t.Error("the guest listens on vsock 3012")
	} else {
		t.Logf("direct vsock 3012: %v", err)
	}
	if c, err := fcvm.DialVsock(dctx, uds, 3010); err != nil {
		t.Errorf("direct vsock 3010: %v", err)
	} else {
		_ = c.Close()
	}
}
