package server

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"io"
	"log/slog"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

const sandbox = "11111111-1111-4111-8111-111111111111"

// fakeGuest emulates the Firecracker vsock UDS: "CONNECT <port>\n" → "OK n\n",
// then a per-port handler. Port 52 answers one line; 3010 echoes; 4000 stops
// reading (shutdown of its read side) and stays open.
func fakeGuest(t *testing.T) string {
	t.Helper()
	sock := filepath.Join("/tmp", "fg-"+filepath.Base(t.TempDir())+".sock")
	ln, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	hold := make(chan struct{})
	t.Cleanup(func() { close(hold); _ = ln.Close(); _ = os.Remove(sock) })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer func() { _ = c.Close() }()
				br := bufio.NewReader(c)
				line, err := br.ReadString('\n')
				if err != nil {
					return
				}
				switch strings.TrimSpace(line) {
				case "CONNECT 52":
					_, _ = io.WriteString(c, "OK 1\n")
					cmd, _ := br.ReadString('\n')
					if strings.TrimSpace(cmd) == "ping" {
						_, _ = io.WriteString(c, "pong\n")
					}
				case "CONNECT 3010":
					_, _ = io.WriteString(c, "OK 2\n")
					_, _ = io.Copy(c, br)
				case "CONNECT 4000":
					_, _ = io.WriteString(c, "OK 3\n")
					_ = c.(*net.UnixConn).CloseRead()
					<-hold
				default:
					// Firecracker closes the connection when nothing listens.
				}
			}(c)
		}
	}()
	return sock
}

type guestProc struct {
	uds  string
	done chan struct{}
	once sync.Once
}

func (p *guestProc) Info() agent.ProcInfo       { return agent.ProcInfo{PID: 4242, VsockUDS: p.uds} }
func (p *guestProc) Done() <-chan struct{}      { return p.done }
func (p *guestProc) Kill(context.Context) error { p.once.Do(func() { close(p.done) }); return nil }

type guestLauncher struct{ uds string }

func (g guestLauncher) Launch(context.Context, agent.LaunchSpec) (agent.Process, error) {
	return &guestProc{uds: g.uds, done: make(chan struct{})}, nil
}

type bigStats struct{}

func (bigStats) MemInfo() (uint64, uint64, error) { return 64 << 10, 32 << 10, nil }
func (bigStats) DiskFreeBytes() (uint64, error)   { return 1 << 40, nil }

// mtlsAgent serves a Manager with one running VM over mTLS on 127.0.0.1.
func mtlsAgent(t *testing.T, ports ...uint32) (addr string, certs *testcerts.Set) {
	t.Helper()
	dir := t.TempDir()
	tdir := filepath.Join(dir, "tpl", "t1")
	if err := os.MkdirAll(tdir, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{template.RootfsFile, template.ScratchFile, template.VMStateFile, template.MemFile} {
		if err := os.WriteFile(filepath.Join(tdir, f), nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := template.WriteManifest(tdir, template.Manifest{Version: "t1", VCPUs: 2, MemMiB: 4096, ScratchGiB: 1, FirecrackerVersion: "v1.17.0"}); err != nil {
		t.Fatal(err)
	}
	uids, _ := jailer.NewUIDPool(1000, 10)
	m := agent.NewManager(agent.Config{StartTimeout: time.Second, StopTimeout: time.Second, MaxScratchGiB: 10},
		&template.Store{Dir: filepath.Join(dir, "tpl")}, guestLauncher{uds: fakeGuest(t)}, bigStats{}, uids,
		agent.Versions{Firecracker: "v1.17.0"}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if _, _, err := m.Create(context.Background(), agent.CreateRequest{SandboxID: sandbox, Attempt: 1, Template: "t1",
		VCPUs: 2, MemMiB: 4096, ScratchGiB: 1, TenantID: "public"}); err != nil {
		t.Fatal(err)
	}
	certs, err := testcerts.Write(dir)
	if err != nil {
		t.Fatal(err)
	}
	creds, err := MTLSCredentials(certs.ServerCert, certs.ServerKey, certs.ClientCA)
	if err != nil {
		t.Fatal(err)
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := NewServer(&Service{M: m, DialPorts: ports}, grpc.Creds(creds))
	go func() { _ = srv.Serve(ln) }()
	t.Cleanup(srv.Stop)
	return ln.Addr().String(), certs
}

func clientTLS(t *testing.T, certs *testcerts.Set, certFile, keyFile string) *tls.Config {
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
		// Always present the cert, so the server's CA check is what refuses it.
		cfg.GetClientCertificate = func(*tls.CertificateRequestInfo) (*tls.Certificate, error) { return &c, nil }
	}
	return cfg
}

func dialClient(t *testing.T, addr string, cfg *tls.Config) pb.HostAgentClient {
	t.Helper()
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(credentials.NewTLS(cfg)))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	return pb.NewHostAgentClient(conn)
}

func TestMTLSRejectsWrongCAAndNoCert(t *testing.T) {
	addr, certs := mtlsAgent(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	for name, cfg := range map[string]*tls.Config{
		"other CA": clientTLS(t, certs, certs.BadCert, certs.BadKey),
		"no cert":  clientTLS(t, certs, "", ""),
	} {
		if _, err := dialClient(t, addr, cfg).List(ctx, &pb.ListRequest{}); err == nil {
			t.Errorf("%s: List succeeded", name)
		} else {
			t.Logf("%s rejected: %v", name, err)
		}
	}
	// A plaintext client is rejected too.
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	if _, err := pb.NewHostAgentClient(conn).List(ctx, &pb.ListRequest{}); err == nil {
		t.Error("plaintext List succeeded")
	}
}

func TestMTLSGoodClientAndDial(t *testing.T) {
	addr, certs := mtlsAgent(t)
	c := dialClient(t, addr, clientTLS(t, certs, certs.GoodCert, certs.GoodKey))
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	l, err := c.List(ctx, &pb.ListRequest{})
	if err != nil || len(l.GetVms()) != 1 {
		t.Fatalf("list: %v %v", l, err)
	}

	// Daemon port: request, then the client ends its send side; the reply
	// still arrives.
	s, err := c.Dial(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: 52, Data: []byte("ping\n")}); err != nil {
		t.Fatal(err)
	}
	_ = s.CloseSend()
	if got := readAll(t, s); got != "pong\n" {
		t.Fatalf("daemon reply %q", got)
	}

	// Preview port: a stream both ways.
	s, err = c.Dial(ctx)
	if err != nil {
		t.Fatal(err)
	}
	_ = s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: 3010})
	for _, part := range []string{"GET / HTTP/1.1\r\n", "Host: x\r\n\r\n"} {
		_ = s.Send(&pb.DialFrame{Data: []byte(part)})
	}
	var echo strings.Builder
	for echo.Len() < len("GET / HTTP/1.1\r\nHost: x\r\n\r\n") {
		f, err := s.Recv()
		if err != nil {
			t.Fatal(err)
		}
		echo.Write(f.GetData())
	}
	if echo.String() != "GET / HTTP/1.1\r\nHost: x\r\n\r\n" {
		t.Fatalf("echo %q", echo.String())
	}

	for name, tc := range map[string]struct {
		id   string
		port uint32
		want pb.ErrorReason
	}{
		"unknown sandbox":  {"22222222-2222-4222-8222-222222222222", 52, pb.ErrorReason_SANDBOX_NOT_FOUND},
		"port not allowed": {sandbox, 22, pb.ErrorReason_PORT_NOT_ALLOWED},
	} {
		s, err := c.Dial(ctx)
		if err != nil {
			t.Fatal(err)
		}
		_ = s.Send(&pb.DialFrame{SandboxId: tc.id, GuestPort: tc.port})
		_, err = s.Recv()
		if got := apierr.FromStatus(err); got != tc.want {
			t.Errorf("%s: reason %s, want %s (%v)", name, got, tc.want, err)
		}
	}
}

func TestDialGuestNotListening(t *testing.T) {
	// 4096 is allowed here, but the fake guest does not serve it.
	addr, certs := mtlsAgent(t, 52, 3010, 4096)
	c := dialClient(t, addr, clientTLS(t, certs, certs.GoodCert, certs.GoodKey))
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	s, err := c.Dial(ctx)
	if err != nil {
		t.Fatal(err)
	}
	_ = s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: 4096})
	_, err = s.Recv()
	if got := apierr.FromStatus(err); got != pb.ErrorReason_GUEST_UNREACHABLE {
		t.Fatalf("reason %s (%v)", got, err)
	}
}

func readAll(t *testing.T, s pb.HostAgent_DialClient) string {
	t.Helper()
	var b strings.Builder
	for {
		f, err := s.Recv()
		if errors.Is(err, io.EOF) {
			return b.String()
		}
		if err != nil {
			t.Fatalf("recv: %v", err)
		}
		b.Write(f.GetData())
	}
}

func TestDialLargeFirstFrameDoesNotBlock(t *testing.T) {
	addr, certs := mtlsAgent(t)
	c := dialClient(t, addr, clientTLS(t, certs, certs.GoodCert, certs.GoodKey))
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	s, err := c.Dial(ctx)
	if err != nil {
		t.Fatal(err)
	}
	// Larger than the socket buffers: the echo guest writes while it reads.
	big := bytes.Repeat([]byte("0123456789abcdef"), 3<<20/16)
	go func() { _ = s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: 3010, Data: big}) }()
	got := 0
	for got < len(big) {
		f, err := s.Recv()
		if err != nil {
			t.Fatalf("after %d of %d echo bytes: %v", got, len(big), err)
		}
		got += len(f.GetData())
	}
}

func TestDialReturnsUploadErrors(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("only Linux fails a write after the peer's SHUT_RD")
	}
	addr, certs := mtlsAgent(t, 52, 3010, 4000)
	c := dialClient(t, addr, clientTLS(t, certs, certs.GoodCert, certs.GoodKey))
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	s, err := c.Dial(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: 4000}); err != nil {
		t.Fatal(err)
	}
	// The guest reads nothing and never closes: only the failed write can
	// end the call.
	go func() {
		chunk := bytes.Repeat([]byte("x"), 32<<10)
		for s.Send(&pb.DialFrame{Data: chunk}) == nil {
		}
	}()
	_, err = s.Recv()
	if got := apierr.FromStatus(err); got != pb.ErrorReason_GUEST_UNREACHABLE {
		t.Fatalf("reason %s, want GUEST_UNREACHABLE (%v)", got, err)
	}
}
