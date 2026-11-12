package server

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus/testutil"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd"
	"github.com/onyx-dot-app/onyx/microvm/internal/metrics"
	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// syncBuf is a bytes.Buffer that the server goroutines can write to.
type syncBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *syncBuf) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.Write(p)
}

func (s *syncBuf) String() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.String()
}

func (s *syncBuf) lines(t *testing.T) []map[string]any {
	t.Helper()
	var out []map[string]any
	for _, l := range strings.Split(strings.TrimSpace(s.String()), "\n") {
		if l == "" {
			continue
		}
		var m map[string]any
		if err := json.Unmarshal([]byte(l), &m); err != nil {
			t.Fatalf("audit line is not JSON: %q", l)
		}
		out = append(out, m)
	}
	return out
}

// observedAgent serves a ptAgent's Manager and pass-through over mTLS with an
// Observer that logs to buf.
func observedAgent(t *testing.T, a *ptAgent) (*syncBuf, *metrics.Metrics, *grpc.ClientConn) {
	t.Helper()
	buf := &syncBuf{}
	mt, err := metrics.New(metrics.Source{VMs: a.m.List})
	if err != nil {
		t.Fatal(err)
	}
	obs := &Observer{Log: slog.New(slog.NewJSONHandler(buf, nil)), Metrics: mt, Tenant: a.m.Tenant}
	certs, err := testcerts.Write(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	creds, err := MTLSCredentials(certs.ServerCert, certs.ServerKey, certs.ClientCA)
	if err != nil {
		t.Fatal(err)
	}
	opts := append(append(a.pt.ServerOptions(), obs.ServerOptions()...), grpc.Creds(creds))
	srv := NewServer(&Service{M: a.m, Keys: a.pt}, opts...)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	go func() { _ = srv.Serve(ln) }()
	t.Cleanup(srv.Stop)
	conn, err := grpc.NewClient(ln.Addr().String(),
		grpc.WithTransportCredentials(credentials.NewTLS(clientTLS(t, certs, certs.GoodCert, certs.GoodKey))))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	return buf, mt, conn
}

func TestAuditLineFieldsAndNoSecrets(t *testing.T) {
	vm := startFakeVM(t)
	a := newPTAgent(t, false, map[string]string{sandbox: vm.uds})
	buf, mt, conn := observedAgent(t, a)
	ha := pb.NewHostAgentClient(conn)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// A repeat Create (same attempt) with the key: the key is installed and
	// must never be logged.
	if _, err := ha.Create(ctx, &pb.CreateRequest{SandboxId: sandbox, Attempt: 1, Template: "t1", Vcpus: 2, MemMib: 4096,
		ScratchGib: 1, TenantId: "public", SandboxdKey: vmKey}); err != nil {
		t.Fatal(err)
	}
	// A refused Create.
	_, _ = ha.Create(ctx, &pb.CreateRequest{SandboxId: sandbox2, Attempt: 1, Template: "missing", Vcpus: 2, MemMib: 4096,
		ScratchGib: 1, TenantId: "t2", SandboxdKey: vmKey})
	// A pass-through call with the daemon key header.
	d := sdpb.NewSandboxdClient(conn)
	if _, err := d.Init(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, sandbox, guestd.KeyHeader, vmKey),
		&sdpb.InitRequest{HostTime: timestamppb.Now(), Entropy: make([]byte, 32), SandboxId: sandbox}); err != nil {
		t.Fatal(err)
	}
	// An unknown daemon method must not add a metric series.
	_ = conn.Invoke(metadata.AppendToOutgoingContext(ctx, SandboxIDHeader, sandbox), "/"+DaemonService+"/NoSuchCall",
		&sdpb.HealthRequest{}, &sdpb.HealthResponse{})

	out := buf.String()
	if strings.Contains(out, vmKey) {
		t.Fatalf("audit log has the daemon key:\n%s", out)
	}
	lines := buf.lines(t)
	if len(lines) != 4 {
		t.Fatalf("want 4 audit lines, got %d:\n%s", len(lines), out)
	}
	want := []map[string]any{
		{"method": "Create", "sandbox_id": sandbox, "tenant_id": "public", "result": "OK", "passthrough": false, "attempt": float64(1)},
		{"method": "Create", "sandbox_id": sandbox2, "tenant_id": "t2", "result": "NotFound", "reason": "TEMPLATE_MISSING"},
		{"method": "Init", "sandbox_id": sandbox, "tenant_id": "public", "result": "OK", "passthrough": true},
		{"method": "unknown", "sandbox_id": sandbox, "passthrough": true},
	}
	for i, w := range want {
		l := lines[i]
		if l["kind"] != "audit" || l["caller"] != "spiffe://test/api_server" {
			t.Errorf("line %d: kind %v caller %v", i, l["kind"], l["caller"])
		}
		if _, ok := l["ms"]; !ok {
			t.Errorf("line %d has no latency", i)
		}
		for k, v := range w {
			if l[k] != v {
				t.Errorf("line %d: %s = %v, want %v", i, k, l[k], v)
			}
		}
	}

	if err := testutil.GatherAndCompare(mt.Registry(), strings.NewReader(`
# HELP craft_fc_host_agent_passthrough_calls_total Guest daemon pass-through calls by daemon method and gRPC status code.
# TYPE craft_fc_host_agent_passthrough_calls_total counter
craft_fc_host_agent_passthrough_calls_total{code="OK",method="Init"} 1
craft_fc_host_agent_passthrough_calls_total{code="Unimplemented",method="unknown"} 1
`), "craft_fc_host_agent_passthrough_calls_total"); err != nil {
		t.Error(err)
	}
	if err := testutil.GatherAndCompare(mt.Registry(), strings.NewReader(`
# HELP craft_fc_host_agent_admissions_total Create admission decisions. result: admitted, refused (reason = ErrorReason), failed (the start failed after admission).
# TYPE craft_fc_host_agent_admissions_total counter
craft_fc_host_agent_admissions_total{reason="TEMPLATE_MISSING",result="refused"} 1
`), "craft_fc_host_agent_admissions_total"); err != nil {
		t.Error(err)
	}
	if n, err := testutil.GatherAndCount(mt.Registry(), "craft_fc_host_agent_create_duration_seconds"); err != nil || n != 2 {
		t.Errorf("create_duration_seconds series = %d, want 2 (existing, refused)", n)
	}
}

func TestAuditDialUsesFirstFrame(t *testing.T) {
	vm := startFakeVM(t)
	a := newPTAgent(t, false, map[string]string{sandbox: vm.uds})
	buf, mt, conn := observedAgent(t, a)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	s, err := pb.NewHostAgentClient(conn).Dial(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Send(&pb.DialFrame{SandboxId: sandbox, GuestPort: 9999}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Recv(); err == nil {
		t.Fatal("dial to a port that is not allowed worked")
	}
	lines := buf.lines(t)
	if len(lines) != 1 {
		t.Fatalf("want 1 audit line, got %d", len(lines))
	}
	l := lines[0]
	if l["method"] != "Dial" || l["sandbox_id"] != sandbox || l["tenant_id"] != "public" || l["reason"] != "PORT_NOT_ALLOWED" {
		t.Errorf("dial audit line: %v", l)
	}
	if err := testutil.GatherAndCompare(mt.Registry(), strings.NewReader(`
# HELP craft_fc_host_agent_rpc_requests_total HostAgent API calls by method and gRPC status code.
# TYPE craft_fc_host_agent_rpc_requests_total counter
craft_fc_host_agent_rpc_requests_total{code="PermissionDenied",method="Dial"} 1
`), "craft_fc_host_agent_rpc_requests_total"); err != nil {
		t.Error(err)
	}
}

func TestCallerOfNoPeer(t *testing.T) {
	if got := callerOf(context.Background()); got != "unknown" {
		t.Errorf("no peer: %q", got)
	}
}

// Unknown HostAgent methods share one metric series.
func TestUnknownHostAgentMethodsShareOneSeries(t *testing.T) {
	a := newPTAgent(t, false, map[string]string{})
	buf, mt, conn := observedAgent(t, a)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	for _, name := range []string{"NoSuch1", "NoSuch2", "NoSuch3"} {
		_ = conn.Invoke(ctx, "/"+pb.HostAgent_ServiceDesc.ServiceName+"/"+name, &pb.ListRequest{}, &pb.ListResponse{})
	}
	if err := testutil.GatherAndCompare(mt.Registry(), strings.NewReader(`
# HELP craft_fc_host_agent_rpc_requests_total HostAgent API calls by method and gRPC status code.
# TYPE craft_fc_host_agent_rpc_requests_total counter
craft_fc_host_agent_rpc_requests_total{code="Unimplemented",method="unknown"} 3
`), "craft_fc_host_agent_rpc_requests_total"); err != nil {
		t.Error(err)
	}
	for _, l := range buf.lines(t) {
		if l["method"] != "unknown" {
			t.Errorf("audit method %v", l["method"])
		}
	}
}

// A Create that passed admission and then failed counts as failed.
func TestCreateFailedAfterAdmission(t *testing.T) {
	a := newPTAgent(t, false, map[string]string{})
	a.l.fail = errors.New("boom")
	_, mt, conn := observedAgent(t, a)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_, err := pb.NewHostAgentClient(conn).Create(ctx, &pb.CreateRequest{SandboxId: sandbox2, Attempt: 1, Template: "t1",
		Vcpus: 2, MemMib: 4096, ScratchGib: 1, TenantId: "t2"})
	if reasonOf(err) != "VMM_FAILED" {
		t.Fatalf("create: %v", err)
	}
	if err := testutil.GatherAndCompare(mt.Registry(), strings.NewReader(`
# HELP craft_fc_host_agent_admissions_total Create admission decisions. result: admitted, refused (reason = ErrorReason), failed (the start failed after admission).
# TYPE craft_fc_host_agent_admissions_total counter
craft_fc_host_agent_admissions_total{reason="VMM_FAILED",result="failed"} 1
`), "craft_fc_host_agent_admissions_total"); err != nil {
		t.Error(err)
	}
}

func TestAuditNamesTheVMOfACapture(t *testing.T) {
	buf := &syncBuf{}
	vm := CaptureVM{SandboxID: sandbox, TenantID: "public", Attempt: 2, Generation: 7}
	o := &Observer{Log: slog.New(slog.NewJSONHandler(buf, nil)), Capture: func(id string) (CaptureVM, bool) {
		return vm, id == "c1"
	}}
	// The call deletes the spool; the lookup must run before it.
	h := func(context.Context, any) (any, error) { vm = CaptureVM{}; return &pb.UploadCaptureResponse{}, nil }
	info := func(m string) *grpc.UnaryServerInfo {
		return &grpc.UnaryServerInfo{FullMethod: "/" + pb.HostAgent_ServiceDesc.ServiceName + "/" + m}
	}
	ctx := context.Background()
	_, _ = o.unary(ctx, &pb.UploadCaptureRequest{CaptureId: "c1"}, info("UploadCapture"), h)
	_, _ = o.unary(ctx, &pb.DiscardCaptureRequest{CaptureId: "gone"}, info("DiscardCapture"), h)

	lines := buf.lines(t)
	if len(lines) != 2 {
		t.Fatalf("lines %v", lines)
	}
	first, second := lines[0], lines[1]
	if first["method"] != "UploadCapture" || first["sandbox_id"] != sandbox || first["tenant_id"] != "public" ||
		first["attempt"] != float64(2) || first["generation"] != float64(7) {
		t.Errorf("upload line %v", first)
	}
	if second["method"] != "DiscardCapture" || second["sandbox_id"] != "" || second["tenant_id"] != "" {
		t.Errorf("unknown capture line %v", second)
	}
}
