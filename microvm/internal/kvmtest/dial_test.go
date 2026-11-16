//go:build kvm && linux

package kvmtest

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"io"
	"log/slog"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/hostinfo"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/server"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

func mtlsClient(t *testing.T, addr string, certs *testcerts.Set, certFile, keyFile string) pb.HostAgentClient {
	t.Helper()
	raw, err := os.ReadFile(certs.ServerCA)
	if err != nil {
		t.Fatal(err)
	}
	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(raw)
	cfg := &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS13}
	if certFile != "" {
		c, err := tls.LoadX509KeyPair(certFile, keyFile)
		if err != nil {
			t.Fatal(err)
		}
		// Always present the cert, even if the server does not list its CA,
		// so the server's own CA check is what refuses a bad client.
		cfg.GetClientCertificate = func(*tls.CertificateRequestInfo) (*tls.Certificate, error) { return &c, nil }
	}
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(credentials.NewTLS(cfg)))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	return pb.NewHostAgentClient(conn)
}

// dialOnce sends req on a new Dial stream, ends the send side and returns
// everything the guest sends until it closes.
func dialOnce(ctx context.Context, c pb.HostAgentClient, sandboxID string, port uint32, req string) (string, error) {
	s, err := c.Dial(ctx)
	if err != nil {
		return "", err
	}
	if err := s.Send(&pb.DialFrame{SandboxId: sandboxID, GuestPort: port, Data: []byte(req)}); err != nil {
		return "", err
	}
	_ = s.CloseSend()
	var b strings.Builder
	for {
		f, err := s.Recv()
		if errors.Is(err, io.EOF) {
			return b.String(), nil
		}
		if err != nil {
			return b.String(), err
		}
		b.Write(f.GetData())
	}
}

func TestDialKVM(t *testing.T) {
	e := loadEnv()
	cmd := newCommand(t, e)
	buildTemplate(t, &e, cmd)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()

	log := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelWarn}))
	uids, _ := jailer.NewUIDPool(uidBase, 65536)
	m := agent.NewManager(agent.Config{MinFreeMemMiB: 2048, MinFreeDiskBytes: 10 * uint64(scratch.GiB), MaxScratchGiB: 100,
		StartTimeout: time.Minute, StopTimeout: 30 * time.Second, TombstoneTTL: time.Hour},
		&template.Store{Dir: filepath.Join(e.DataDir, "templates")}, &fcvm.Launcher{Cmd: cmd, Log: log},
		hostinfo.Stats{DataDir: e.DataDir}, uids, kvmVersions(t, e), log)
	certs, err := testcerts.Write(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	creds, err := server.MTLSCredentials(certs.ServerCert, certs.ServerKey, certs.ClientCA)
	if err != nil {
		t.Fatal(err)
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := server.NewServer(&server.Service{M: m}, grpc.Creds(creds))
	go func() { _ = srv.Serve(ln) }()
	defer srv.Stop()
	addr := ln.Addr().String()
	good := mtlsClient(t, addr, certs, certs.GoodCert, certs.GoodKey)

	r, err := good.Create(ctx, &pb.CreateRequest{SandboxId: newUUID(), Attempt: 1, Template: e.Template,
		Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: tplScratchGiB, TenantId: "public"})
	if err != nil {
		t.Fatalf("create over mTLS: %v", err)
	}
	vm := r.GetVm()
	defer func() {
		_, _ = good.Stop(context.Background(), &pb.StopRequest{SandboxId: vm.GetSandboxId(), Attempt: 1, Generation: vm.GetGeneration()})
	}()
	t.Logf("Create over mTLS: generation %d", vm.GetGeneration())

	// The guest daemon port is never open to Dial (only the agent sets the
	// daemon key, through the pass-through and Create).
	if _, err := dialOnce(ctx, good, vm.GetSandboxId(), server.DefaultDaemonPort, "ping\n"); apierr.FromStatus(err) != pb.ErrorReason_PORT_NOT_ALLOWED {
		t.Fatalf("dial %d: want PORT_NOT_ALLOWED, got %v", server.DefaultDaemonPort, err)
	}

	// Preview port 3010: a web server in the guest, through the prototype
	// agent's vsock 3010 → 127.0.0.1:3010 forward.
	v := cmd.Layout.HostPath(vm.GetSandboxId(), template.VsockUDS)
	if out, err := guestRun(ctx, v, "run", `mkdir -p /tmp/www && echo preview-ok > /tmp/www/index.html &&
(setsid nohup python3 -m http.server 3010 --bind 127.0.0.1 --directory /tmp/www >/dev/null 2>&1 </dev/null &) ; echo STARTED`); err != nil || !strings.Contains(out, "STARTED") {
		t.Fatalf("start preview: %q %v", out, err)
	}
	var page string
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		page, err = dialOnce(ctx, good, vm.GetSandboxId(), 3010, "GET /index.html HTTP/1.0\r\nHost: localhost\r\n\r\n")
		if err == nil && strings.Contains(page, "preview-ok") {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if !strings.HasPrefix(page, "HTTP/1.0 200") || !strings.Contains(page, "preview-ok") {
		t.Fatalf("dial 3010: %q %v", page, err)
	}
	t.Logf("Dial 3010: %s ... preview-ok", strings.SplitN(page, "\r\n", 2)[0])
	var lat []float64
	for i := 0; i < 20; i++ {
		s := time.Now()
		out, err := dialOnce(ctx, good, vm.GetSandboxId(), 3010, "GET /index.html HTTP/1.0\r\nHost: localhost\r\n\r\n")
		if err != nil || !strings.Contains(out, "preview-ok") {
			t.Fatalf("dial 3010 #%d: %q %v", i, out, err)
		}
		lat = append(lat, float64(time.Since(s).Microseconds())/1000)
	}
	t.Logf("BENCH dial_get_ms p50=%.2f p95=%.2f max=%.2f (20 calls)", pct(lat, 0.5), pct(lat, 0.95), pct(lat, 1))

	// Refused: a client cert from another CA, and a client with no cert.
	for name, c := range map[string]pb.HostAgentClient{
		"other CA": mtlsClient(t, addr, certs, certs.BadCert, certs.BadKey),
		"no cert":  mtlsClient(t, addr, certs, "", ""),
	} {
		if _, err := dialOnce(ctx, c, vm.GetSandboxId(), 3010, ""); err == nil {
			t.Errorf("%s: Dial succeeded", name)
		} else {
			t.Logf("%s refused: %v", name, err)
		}
		if _, err := c.List(ctx, &pb.ListRequest{}); err == nil {
			t.Errorf("%s: List succeeded", name)
		}
	}
	// An allowed port that nothing in the guest serves, and a port off the list.
	if _, err := dialOnce(ctx, good, vm.GetSandboxId(), 22, ""); err == nil {
		t.Error("port 22 was allowed")
	}
	if _, err := dialOnce(ctx, good, newUUID(), 3010, ""); err == nil {
		t.Error("unknown sandbox was dialed")
	}
}
