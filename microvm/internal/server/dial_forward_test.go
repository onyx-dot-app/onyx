package server

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// dialAll sends req on a Dial stream, ends the send side and returns what
// the guest sends until it closes.
func dialAll(ctx context.Context, c pb.HostAgentClient, port uint32, req string) (string, error) {
	s, err := c.Dial(ctx)
	if err != nil {
		return "", err
	}
	if err := s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: port, Data: []byte(req)}); err != nil {
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

// Create sends the agent's Dial ports (without the daemon port) with the
// key. The guest daemon forwards exactly those ports to 127.0.0.1, so Dial
// reaches a guest web server, and the guest listens on no other port.
func TestCreateSendsDialPorts(t *testing.T) {
	web := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "preview-ok")
	}))
	defer web.Close()
	var mu sync.Mutex
	var dialed []uint32
	fwd := &guestd.Forwards{Reserved: DefaultDaemonPort, Dial: func(ctx context.Context, port uint32) (net.Conn, error) {
		mu.Lock()
		dialed = append(dialed, port)
		mu.Unlock()
		var d net.Dialer
		return d.DialContext(ctx, "tcp", web.Listener.Addr().String())
	}}
	vm := startFakeVMWith(t, guestd.Config{Version: "test", Forwards: fwd})
	a := newPTAgent(t, false, map[string]string{sandbox: vm.uds}, func(s *Service) {
		s.DialPorts = []uint32{3010, DefaultDaemonPort, 4000}
	})
	ha := pb.NewHostAgentClient(a.conn)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if _, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: sandbox, Attempt: 1, Template: "t1", Vcpus: 2, MemMib: 4096,
		ScratchGib: 1, TenantId: "public", SandboxdKey: vmKey}); err != nil {
		t.Fatal(err)
	}
	h, err := a.daemon().Health(to(ctx, sandbox), &sdpb.HealthRequest{})
	if err != nil || !slices.Equal(h.GetDialPorts(), []uint32{3010, 4000}) {
		t.Fatalf("health dial_ports: %v %v", h.GetDialPorts(), err)
	}
	if vm.portListener(DefaultDaemonPort) != nil || vm.portListener(3011) != nil {
		t.Fatal("the guest listens on a port that Dial does not allow")
	}

	// Retry: a guest TCP connect that fails ends the stream with no bytes.
	var page string
	for range 50 {
		if page, err = dialAll(ctx, ha, 3010, "GET / HTTP/1.0\r\nHost: localhost\r\n\r\n"); err != nil || page != "" {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	if err != nil || !strings.HasPrefix(page, "HTTP/1.0 200") || !strings.HasSuffix(page, "preview-ok") {
		t.Fatalf("dial 3010: %q %v", page, err)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(dialed) == 0 || slices.ContainsFunc(dialed, func(p uint32) bool { return p != 3010 }) {
		t.Fatalf("guest dialed %v", dialed)
	}
	if _, err := dialAll(ctx, ha, 3011, ""); apierr.FromStatus(err) != pb.ErrorReason_PORT_NOT_ALLOWED {
		t.Fatalf("dial 3011: want PORT_NOT_ALLOWED, got %v", err)
	}
}

// SetKey checks the port list. A repeat call replaces it; one with no
// ports keeps it. A first call with no ports forwards the default.
func TestSetKeyDialPorts(t *testing.T) {
	newVM := func() (*fakeVM, sdpb.SandboxdClient) {
		fwd := &guestd.Forwards{Reserved: DefaultDaemonPort}
		vm := startFakeVMWith(t, guestd.Config{Version: "test", Forwards: fwd})
		conn, err := grpc.NewClient("passthrough:///guest-daemon", grpc.WithTransportCredentials(insecure.NewCredentials()),
			grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) {
				return fcvm.DialVsock(ctx, vm.uds, DefaultDaemonPort)
			}))
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = conn.Close() })
		return vm, sdpb.NewSandboxdClient(conn)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	_, sd := newVM()
	for _, bad := range [][]uint32{{0}, {70000}, {DefaultDaemonPort}, make([]uint32, 65)} {
		if _, err := sd.SetKey(ctx, &sdpb.SetKeyRequest{Key: vmKey, DialPorts: bad}); err == nil {
			t.Errorf("SetKey with dial_ports %v succeeded", bad[:min(len(bad), 3)])
		}
	}
	r, err := sd.SetKey(ctx, &sdpb.SetKeyRequest{Key: vmKey})
	if err != nil || !slices.Equal(r.GetDialPorts(), guestd.DefaultDialPorts) {
		t.Fatalf("first SetKey with no ports: %v %v", r, err)
	}

	vm, sd := newVM()
	steps := []struct {
		ports, want []uint32
	}{
		{[]uint32{3012, 3011, 3011}, []uint32{3011, 3012}},
		{nil, []uint32{3011, 3012}},
		{[]uint32{3013}, []uint32{3013}},
	}
	for i, st := range steps {
		r, err := sd.SetKey(ctx, &sdpb.SetKeyRequest{Key: vmKey, DialPorts: st.ports})
		if err != nil || !slices.Equal(r.GetDialPorts(), st.want) {
			t.Fatalf("step %d: %v %v", i, r, err)
		}
	}
	for _, p := range []uint32{3011, 3012} {
		if vm.portListener(p) != nil {
			t.Errorf("port %d still listens", p)
		}
	}
	if vm.portListener(3013) == nil {
		t.Error("port 3013 does not listen")
	}
	if _, err := sd.SetKey(ctx, &sdpb.SetKeyRequest{Key: strings.Repeat("x", 32), DialPorts: []uint32{3014}}); err == nil {
		t.Fatal("SetKey with another key changed the ports")
	}
	if vm.portListener(3014) != nil {
		t.Fatal("port 3014 listens after a refused SetKey")
	}
}
