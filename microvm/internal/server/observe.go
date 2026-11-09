package server

import (
	"context"
	"crypto/x509"
	"log/slog"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/peer"
	"google.golang.org/grpc/status"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/metrics"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// maxAuditField caps a caller-supplied string in an audit line.
const maxAuditField = 128

// Observer writes one audit line and records metrics for every call on a
// server: HostAgent calls and guest daemon pass-through calls. The audit
// line names the caller, the sandbox, the tenant, the method, the result and
// the latency. It never logs a request or response body or any metadata
// value, so sandboxd_key and x-sandboxd-key never reach the log.
type Observer struct {
	// Log gets the audit lines (kind=audit).
	Log *slog.Logger
	// Metrics may be nil.
	Metrics *metrics.Metrics
	// Tenant returns the tenant of a sandbox on this node, or "". Nil skips
	// the lookup.
	Tenant func(sandboxID string) string
}

// ServerOptions returns the interceptors.
func (o *Observer) ServerOptions() []grpc.ServerOption {
	return []grpc.ServerOption{
		grpc.ChainUnaryInterceptor(o.unary),
		grpc.ChainStreamInterceptor(o.stream),
	}
}

// call is what one audit line reports.
type call struct {
	method      string
	passthrough bool
	caller      string
	sandboxID   string
	tenantID    string
	attempt     uint64
	generation  uint64
}

type sandboxMsg interface{ GetSandboxId() string }
type tenantMsg interface{ GetTenantId() string }
type attemptMsg interface{ GetAttempt() uint64 }
type generationMsg interface{ GetGeneration() uint64 }

func (o *Observer) unary(ctx context.Context, req any, info *grpc.UnaryServerInfo, h grpc.UnaryHandler) (any, error) {
	t0 := time.Now()
	c := &call{method: shortMethod(info.FullMethod), caller: callerOf(ctx)}
	c.fromMsg(req, o.Tenant)
	resp, err := h(ctx, req)
	d := time.Since(t0)
	if c.method == "Create" {
		o.Metrics.ObserveCreate(d, createResult(resp, err), reasonOf(err))
	}
	o.finish(c, err, d)
	return resp, err
}

func (o *Observer) stream(srv any, ss grpc.ServerStream, info *grpc.StreamServerInfo, h grpc.StreamHandler) error {
	t0 := time.Now()
	c := &call{method: shortMethod(info.FullMethod), caller: callerOf(ss.Context())}
	if daemon, ok := strings.CutPrefix(info.FullMethod, "/"+DaemonService+"/"); ok {
		c.passthrough = true
		c.method = daemonMethod(daemon)
		md, _ := metadata.FromIncomingContext(ss.Context())
		if ids := md.Get(SandboxIDHeader); len(ids) == 1 {
			c.sandboxID = clip(ids[0])
			c.lookupTenant(o.Tenant)
		}
	} else if !strings.HasPrefix(info.FullMethod, "/"+pb.HostAgent_ServiceDesc.ServiceName+"/") {
		c.method = "unknown"
	}
	err := h(srv, &observedStream{ServerStream: ss, c: c, tenant: o.Tenant})
	o.finish(c, err, time.Since(t0))
	return err
}

func (o *Observer) finish(c *call, err error, d time.Duration) {
	code := status.Code(err).String()
	if c.passthrough {
		o.Metrics.ObservePassthrough(c.method, code)
	} else {
		o.Metrics.ObserveRPC(c.method, code, d)
	}
	if o.Log == nil {
		return
	}
	attrs := []slog.Attr{
		slog.String("kind", "audit"),
		slog.String("method", c.method),
		slog.Bool("passthrough", c.passthrough),
		slog.String("caller", c.caller),
		slog.String("sandbox_id", c.sandboxID),
		slog.String("tenant_id", c.tenantID),
		slog.String("result", code),
		slog.Int64("ms", d.Milliseconds()),
	}
	if c.attempt != 0 {
		attrs = append(attrs, slog.Uint64("attempt", c.attempt))
	}
	if c.generation != 0 {
		attrs = append(attrs, slog.Uint64("generation", c.generation))
	}
	if r := reasonOf(err); r != "" {
		attrs = append(attrs, slog.String("reason", r))
	}
	o.Log.LogAttrs(context.Background(), slog.LevelInfo, "rpc", attrs...)
}

// fromMsg reads the identifying fields of a request. It reads no other field.
func (c *call) fromMsg(msg any, tenant func(string) string) {
	if m, ok := msg.(sandboxMsg); ok && c.sandboxID == "" {
		c.sandboxID = clip(m.GetSandboxId())
	}
	if m, ok := msg.(attemptMsg); ok && c.attempt == 0 {
		c.attempt = m.GetAttempt()
	}
	if m, ok := msg.(generationMsg); ok && c.generation == 0 {
		c.generation = m.GetGeneration()
	}
	if m, ok := msg.(tenantMsg); ok && c.tenantID == "" {
		c.tenantID = clip(m.GetTenantId())
	}
	c.lookupTenant(tenant)
}

func (c *call) lookupTenant(tenant func(string) string) {
	if c.tenantID == "" && c.sandboxID != "" && tenant != nil {
		c.tenantID = tenant(c.sandboxID)
	}
}

// observedStream reads the identifying fields of the first client message
// (Dial's first frame names the sandbox).
type observedStream struct {
	grpc.ServerStream
	c      *call
	tenant func(string) string
	seen   bool
}

func (s *observedStream) RecvMsg(m any) error {
	err := s.ServerStream.RecvMsg(m)
	if err == nil && !s.seen {
		s.seen = true
		s.c.fromMsg(m, s.tenant)
	}
	return err
}

// callerOf names the client: the SANs of its verified certificate on the
// mTLS listener, or "unix" on the root-only Unix socket.
func callerOf(ctx context.Context) string {
	p, ok := peer.FromContext(ctx)
	if !ok {
		return "unknown"
	}
	if ti, ok := p.AuthInfo.(credentials.TLSInfo); ok {
		if chains := ti.State.VerifiedChains; len(chains) > 0 && len(chains[0]) > 0 {
			return clip(certIdentity(chains[0][0]))
		}
		return "tls-unverified"
	}
	if p.Addr != nil && p.Addr.Network() == "unix" {
		return "unix"
	}
	return "unknown"
}

func certIdentity(leaf *x509.Certificate) string {
	var ids []string
	for _, u := range leaf.URIs {
		ids = append(ids, u.String())
	}
	ids = append(ids, leaf.DNSNames...)
	if len(ids) == 0 {
		return "cn=" + leaf.Subject.CommonName
	}
	return strings.Join(ids, ",")
}

// shortMethod returns the method name of "/pkg.Service/Method".
func shortMethod(full string) string {
	if i := strings.LastIndexByte(full, '/'); i >= 0 {
		return full[i+1:]
	}
	return full
}

// daemonMethods are the method names of the guest daemon service. Other
// names map to "unknown", so a client cannot add metric series.
var daemonMethods = func() map[string]bool {
	out := map[string]bool{}
	for _, m := range sdpb.Sandboxd_ServiceDesc.Methods {
		out[m.MethodName] = true
	}
	for _, s := range sdpb.Sandboxd_ServiceDesc.Streams {
		out[s.StreamName] = true
	}
	return out
}()

func daemonMethod(name string) string {
	if daemonMethods[name] {
		return name
	}
	return "unknown"
}

// reasonOf returns the ErrorReason name of an agent error, or "".
func reasonOf(err error) string {
	if err == nil {
		return ""
	}
	r := apierr.FromStatus(err)
	if r == pb.ErrorReason_ERROR_REASON_UNSPECIFIED {
		return ""
	}
	return r.String()
}

// Reasons of a Create that passed admission and then failed.
var createFailed = map[pb.ErrorReason]bool{
	pb.ErrorReason_INTERNAL:           true,
	pb.ErrorReason_VMM_FAILED:         true,
	pb.ErrorReason_GUEST_UNREACHABLE:  true,
	pb.ErrorReason_GUEST_KEY_REJECTED: true,
	pb.ErrorReason_VM_NOT_RUNNING:     true,
}

func createResult(resp any, err error) string {
	if err == nil {
		if r, ok := resp.(*pb.CreateResponse); ok && r.GetCreated() {
			return metrics.CreateCreated
		}
		return metrics.CreateExisting
	}
	r := apierr.FromStatus(err)
	if r == pb.ErrorReason_ERROR_REASON_UNSPECIFIED || createFailed[r] {
		return metrics.CreateFailed
	}
	return metrics.CreateRefused
}

// clip bounds a caller-supplied string.
func clip(s string) string {
	if len(s) > maxAuditField {
		return s[:maxAuditField]
	}
	return s
}
