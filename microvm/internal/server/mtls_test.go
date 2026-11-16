package server

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
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
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

const sandbox = "11111111-1111-4111-8111-111111111111"

// pingPort is a fake guest service that answers one line. Dial never allows
// the daemon port (52), so tests do not use it as a stand-in.
const pingPort = 3020

// fakeGuest emulates the Firecracker vsock UDS: "CONNECT <port>\n" → "OK n\n",
// then a per-port handler. pingPort answers one line; 3010 echoes; 4000 stops
// reading (shutdown of its read side) and stays open.
func fakeGuest(t *testing.T) string {
	t.Helper()
	sock := shortSock(t, "fg")
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
				case fmt.Sprintf("CONNECT %d", pingPort):
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
	return mtlsAgentWith(t, &Service{DialPorts: ports}, nil)
}

// mtlsAgentWith is mtlsAgent with a Service setup and a client SAN allowlist.
func mtlsAgentWith(t *testing.T, svc *Service, sans []string) (addr string, certs *testcerts.Set) {
	t.Helper()
	dir := t.TempDir()
	if _, err := template.WriteFake(filepath.Join(dir, "tpl"), "t1", template.Key{VCPUs: 2, MemMiB: 4096, ScratchGiB: 1, FirecrackerVersion: "v1.17.0"}); err != nil {
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
	creds, err := (&MTLS{CertFile: certs.ServerCert, KeyFile: certs.ServerKey, ClientCAFile: certs.ClientCA,
		AllowedSANs: sans}).Credentials()
	if err != nil {
		t.Fatal(err)
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	svc.M = m
	srv := NewServer(svc, grpc.Creds(creds))
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
	addr, certs := mtlsAgent(t, pingPort, 3010)
	c := dialClient(t, addr, clientTLS(t, certs, certs.GoodCert, certs.GoodKey))
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	l, err := c.List(ctx, &pb.ListRequest{})
	if err != nil || len(l.GetVms()) != 1 {
		t.Fatalf("list: %v %v", l, err)
	}

	// Request, then the client ends its send side; the reply still arrives.
	s, err := c.Dial(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: pingPort, Data: []byte("ping\n")}); err != nil {
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
		"unknown sandbox":  {"22222222-2222-4222-8222-222222222222", pingPort, pb.ErrorReason_SANDBOX_NOT_FOUND},
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
	addr, certs := mtlsAgent(t, pingPort, 3010, 4096)
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
	addr, certs := mtlsAgent(t, pingPort, 3010, 4000)
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

func TestMTLSAllowedSANs(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	addr, certs := mtlsAgentWith(t, &Service{}, []string{"spiffe://test/api_server"})
	if _, err := dialClient(t, addr, clientTLS(t, certs, certs.GoodCert, certs.GoodKey)).List(ctx, &pb.ListRequest{}); err != nil {
		t.Fatalf("allowed client: %v", err)
	}
	if _, err := dialClient(t, addr, clientTLS(t, certs, certs.OtherCert, certs.OtherKey)).List(ctx, &pb.ListRequest{}); err == nil {
		t.Fatal("client with another SAN was accepted")
	}
	// No allowlist: any client of the CA.
	addr, certs = mtlsAgent(t)
	if _, err := dialClient(t, addr, clientTLS(t, certs, certs.OtherCert, certs.OtherKey)).List(ctx, &pb.ListRequest{}); err != nil {
		t.Fatalf("no allowlist: %v", err)
	}
}

func TestMTLSReloadsRotatedFiles(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	addr, old := mtlsAgent(t)
	list := func(certs *testcerts.Set) error {
		_, err := dialClient(t, addr, clientTLS(t, certs, certs.GoodCert, certs.GoodKey)).List(ctx, &pb.ListRequest{})
		return err
	}
	if err := list(old); err != nil {
		t.Fatal(err)
	}
	// A half-written rotation keeps the last good files.
	future := time.Now().Add(time.Hour)
	writeAt(t, old.ClientCA, []byte("not a PEM"), future)
	if err := list(old); err != nil {
		t.Fatalf("after a bad CA file: %v", err)
	}

	rotated, err := testcerts.Write(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	for src, dst := range map[string]string{
		rotated.ServerCert: old.ServerCert, rotated.ServerKey: old.ServerKey, rotated.ClientCA: old.ClientCA,
	} {
		raw, err := os.ReadFile(src)
		if err != nil {
			t.Fatal(err)
		}
		writeAt(t, dst, raw, future.Add(time.Minute))
	}
	// Clients of the new CA work; clients of the old CA do not.
	if err := list(rotated); err != nil {
		t.Fatalf("rotated client: %v", err)
	}
	if err := list(old); err == nil {
		t.Fatal("old client accepted after the rotation")
	}
}

func writeAt(t *testing.T, path string, data []byte, mod time.Time) {
	t.Helper()
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(path, mod, mod); err != nil {
		t.Fatal(err)
	}
}

func TestDialChecksGeneration(t *testing.T) {
	addr, certs := mtlsAgent(t, pingPort)
	c := dialClient(t, addr, clientTLS(t, certs, certs.GoodCert, certs.GoodKey))
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	l, err := c.List(ctx, &pb.ListRequest{})
	if err != nil {
		t.Fatal(err)
	}
	gen := l.GetVms()[0].GetGeneration()
	s, _ := c.Dial(ctx)
	_ = s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: pingPort, Generation: gen + 1})
	if _, err := s.Recv(); apierr.FromStatus(err) != pb.ErrorReason_INSTANCE_MISMATCH {
		t.Fatalf("old generation: %v", err)
	}
	s, _ = c.Dial(ctx)
	_ = s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: pingPort, Generation: gen, Data: []byte("ping\n")})
	_ = s.CloseSend()
	if got := readAll(t, s); got != "pong\n" {
		t.Fatalf("daemon reply %q", got)
	}
}

func TestDialCapPerVM(t *testing.T) {
	addr, certs := mtlsAgentWith(t, &Service{DialPorts: []uint32{pingPort, 3010}, MaxDialsPerVM: 1}, nil)
	c := dialClient(t, addr, clientTLS(t, certs, certs.GoodCert, certs.GoodKey))
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	// A finished stream gives its slot back.
	s, _ := c.Dial(ctx)
	_ = s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: pingPort, Data: []byte("ping\n")})
	_ = s.CloseSend()
	if got := readAll(t, s); got != "pong\n" {
		t.Fatalf("daemon reply %q", got)
	}
	// An open stream holds the only slot.
	hold, _ := c.Dial(ctx)
	_ = hold.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: 3010, Data: []byte("x")})
	if f, err := hold.Recv(); err != nil || string(f.GetData()) != "x" {
		t.Fatalf("echo: %v %v", f, err)
	}
	s, _ = c.Dial(ctx)
	_ = s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: pingPort})
	_, err := s.Recv()
	if got := apierr.FromStatus(err); got != pb.ErrorReason_DIAL_LIMIT || status.Code(err) != codes.ResourceExhausted {
		t.Fatalf("over the cap: %s %v", got, err)
	}
}

func TestDialRefusesDaemonPort(t *testing.T) {
	for name, svc := range map[string]*Service{
		// 52 is on the allow-list, but it is the daemon port.
		"default daemon port": {DialPorts: []uint32{DefaultDaemonPort, 3010}},
		"custom daemon port":  {DialPorts: []uint32{pingPort, 3010}, DaemonPort: pingPort},
	} {
		addr, certs := mtlsAgentWith(t, svc, nil)
		c := dialClient(t, addr, clientTLS(t, certs, certs.GoodCert, certs.GoodKey))
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		port := svc.DaemonPort
		if port == 0 {
			port = DefaultDaemonPort
		}
		s, err := c.Dial(ctx)
		if err != nil {
			t.Fatal(err)
		}
		_ = s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: port, Data: []byte("ping\n")})
		_, err = s.Recv()
		if got := apierr.FromStatus(err); got != pb.ErrorReason_PORT_NOT_ALLOWED || status.Code(err) != codes.PermissionDenied {
			t.Errorf("%s: %s %v", name, got, err)
		}
		cancel()
	}
}

func TestAcquireDial(t *testing.T) {
	s := &Service{MaxDialsPerVM: 2}
	r1, err := s.acquireDial(sandbox)
	if err != nil {
		t.Fatal(err)
	}
	r2, _ := s.acquireDial(sandbox)
	if _, err := s.acquireDial(sandbox); apierr.ReasonOf(err) != pb.ErrorReason_DIAL_LIMIT {
		t.Fatalf("third dial: %v", err)
	}
	if _, err := s.acquireDial("other"); err != nil {
		t.Fatalf("other VM: %v", err)
	}
	r1()
	r3, err := s.acquireDial(sandbox)
	if err != nil {
		t.Fatalf("after release: %v", err)
	}
	r2()
	r3()
	if n := s.dials[sandbox]; n != 0 {
		t.Fatalf("count %d after release", n)
	}
}
