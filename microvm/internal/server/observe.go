package server

import (
	"context"
	"crypto/x509"
	"errors"
	"log/slog"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/peer"
	"google.golang.org/grpc/status"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
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
	// Capture returns the VM of a spooled capture (UploadCaptureRequest and
	// DiscardCaptureRequest name only the capture). Nil skips the lookup.
	Capture func(captureID string) (CaptureVM, bool)
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
type captureMsg interface{ GetCaptureId() string }
type tenantMsg interface{ GetTenantId() string }
type attemptMsg interface{ GetAttempt() uint64 }
type generationMsg interface{ GetGeneration() uint64 }

func (o *Observer) unary(ctx context.Context, req any, info *grpc.UnaryServerInfo, h grpc.UnaryHandler) (any, error) {
	t0 := time.Now()
	c := &call{method: hostAgentMethod(info.FullMethod), caller: callerOf(ctx)}
	c.fromMsg(req, o.Tenant)
	c.fromCapture(req, o.Capture)
	admitted := func() bool { return false }
	if c.method == "Create" {
		ctx, admitted = agent.WithAdmission(ctx)
	}
	resp, err := h(ctx, req)
	d := time.Since(t0)
	if c.method == "Create" {
		o.Metrics.ObserveCreate(d, createResult(resp, err, admitted()), reasonOf(err))
	}
	o.finish(c, err, d)
	return resp, err
}

func (o *Observer) stream(srv any, ss grpc.ServerStream, info *grpc.StreamServerInfo, h grpc.StreamHandler) error {
	t0 := time.Now()
	c := &call{method: hostAgentMethod(info.FullMethod), caller: callerOf(ss.Context())}
	if daemon, ok := strings.CutPrefix(info.FullMethod, "/"+DaemonService+"/"); ok {
		c.passthrough = true
		c.method = knownMethod(daemonMethods, daemon)
		md, _ := metadata.FromIncomingContext(ss.Context())
		if ids := md.Get(SandboxIDHeader); len(ids) == 1 {
			c.sandboxID = clip(ids[0])
			c.lookupTenant(o.Tenant)
		}
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

// fromCapture names the VM of a request that names only a spooled capture.
// It runs before the call, which may delete the spool.
func (c *call) fromCapture(msg any, capture func(string) (CaptureVM, bool)) {
	m, ok := msg.(captureMsg)
	if !ok || capture == nil || c.sandboxID != "" {
		return
	}
	vm, ok := capture(m.GetCaptureId())
	if !ok {
		return
	}
	c.sandboxID, c.tenantID = clip(vm.SandboxID), clip(vm.TenantID)
	c.attempt, c.generation = vm.Attempt, vm.Generation
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

// Method names of the HostAgent and guest daemon services. Other names map
// to "unknown", so a client cannot add metric series.
var (
	hostAgentMethods = methodNames(pb.HostAgent_ServiceDesc)
	daemonMethods    = methodNames(sdpb.Sandboxd_ServiceDesc)
)

func methodNames(d grpc.ServiceDesc) map[string]bool {
	out := map[string]bool{}
	for _, m := range d.Methods {
		out[m.MethodName] = true
	}
	for _, s := range d.Streams {
		out[s.StreamName] = true
	}
	return out
}

func knownMethod(known map[string]bool, name string) string {
	if known[name] {
		return name
	}
	return "unknown"
}

// hostAgentMethod returns the method name of "/<HostAgent service>/Method",
// or "unknown".
func hostAgentMethod(full string) string {
	name, ok := strings.CutPrefix(full, "/"+pb.HostAgent_ServiceDesc.ServiceName+"/")
	if !ok {
		return "unknown"
	}
	return knownMethod(hostAgentMethods, name)
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

// createResult classifies a Create. admitted: the call passed admission or
// found its VM already placed, so an error is a failed start, not a refusal.
func createResult(resp any, err error, admitted bool) string {
	if err == nil {
		if r, ok := resp.(*pb.CreateResponse); ok && r.GetCreated() {
			return metrics.CreateCreated
		}
		return metrics.CreateExisting
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return metrics.CreateCanceled
	}
	if admitted {
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
