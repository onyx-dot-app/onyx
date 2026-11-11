package server

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"strings"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/backoff"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/encoding"
	"google.golang.org/grpc/mem"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	// Registers the "proto" codec that rawCodec falls back to.
	_ "google.golang.org/grpc/encoding/proto"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

const (
	// DaemonService is the only service the pass-through forwards.
	DaemonService = "craft.sandboxd.v1.Sandboxd"
	// SandboxIDHeader routes a pass-through call to one VM.
	SandboxIDHeader = "x-sandbox-id"
	// DefaultDaemonPort is the guest daemon's vsock port.
	DefaultDaemonPort = 52
	// MaxMessageBytes caps one message in both directions (daemon chunks are
	// 64 KiB).
	MaxMessageBytes = 16 << 20
	// upstreamIdle closes an idle vsock connection. The next call dials again.
	upstreamIdle = 10 * time.Minute
	// DefaultKeyTimeout bounds the wait for the daemon in InstallKey.
	DefaultKeyTimeout = 10 * time.Second
)

// Passthrough forwards craft.sandboxd.v1.Sandboxd calls to the guest daemon
// of the VM named by the x-sandbox-id metadata, over vsock. It never decodes
// the messages, so new daemon calls need no agent change.
type Passthrough struct {
	M *agent.Manager
	// Port is the guest daemon's vsock port. 0 means DefaultDaemonPort.
	Port uint32
	// KeyTimeout bounds InstallKey. 0 means DefaultKeyTimeout.
	KeyTimeout time.Duration
	Log        *slog.Logger

	mu    sync.Mutex
	conns map[string]*upstream
}

// upstream is one client connection to the daemon of one VM instance.
type upstream struct {
	gen  uint64
	conn *grpc.ClientConn
	// dropped is closed when the VM stops or exits.
	dropped chan struct{}
	once    sync.Once
}

// NewPassthrough returns a Passthrough and registers it with m, so that a
// VM's connection closes before its vsock socket and UID are freed. Call it
// before Recover and before the API serves.
func NewPassthrough(m *agent.Manager, port uint32, log *slog.Logger) *Passthrough {
	p := &Passthrough{M: m, Port: port, Log: log, conns: map[string]*upstream{}}
	m.OnRelease(func(vm agent.VM) { p.Drop(vm.SandboxID) })
	return p
}

// ServerOptions returns the options that install the pass-through on a
// gRPC server.
func (p *Passthrough) ServerOptions() []grpc.ServerOption {
	return []grpc.ServerOption{
		grpc.UnknownServiceHandler(p.handle),
		grpc.ForceServerCodecV2(rawCodec{}),
		grpc.MaxRecvMsgSize(MaxMessageBytes),
		grpc.MaxSendMsgSize(MaxMessageBytes),
	}
}

// Drop closes the cached connection of a sandbox. Calls on it end with
// VM_NOT_RUNNING.
func (p *Passthrough) Drop(sandboxID string) {
	p.mu.Lock()
	u := p.conns[sandboxID]
	delete(p.conns, sandboxID)
	p.mu.Unlock()
	if u != nil {
		u.close()
	}
}

// Cached returns the generation of the cached connection of a sandbox.
func (p *Passthrough) Cached(sandboxID string) (uint64, bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	u := p.conns[sandboxID]
	if u == nil {
		return 0, false
	}
	return u.gen, true
}

func (u *upstream) close() {
	u.once.Do(func() {
		close(u.dropped)
		_ = u.conn.Close()
	})
}

func (u *upstream) isDropped() bool {
	select {
	case <-u.dropped:
		return true
	default:
		return false
	}
}

// get returns the connection of the running VM instance, and makes one if
// there is none for this generation.
func (p *Passthrough) get(sandboxID string) (*upstream, error) {
	t, err := p.M.GuestTarget(sandboxID)
	if err != nil {
		return nil, err
	}
	p.mu.Lock()
	u := p.conns[sandboxID]
	if u != nil && u.gen == t.Generation {
		p.mu.Unlock()
		return u, nil
	}
	if u != nil && u.gen > t.Generation {
		// Generations only grow. This call read an older instance's target
		// before a newer one was cached: never replace or close the newer
		// connection for it.
		p.mu.Unlock()
		return nil, apierr.New(pb.ErrorReason_VM_NOT_RUNNING, "sandbox %s was replaced during the call", sandboxID)
	}
	nu, err := p.dial(t)
	if err != nil {
		p.mu.Unlock()
		return nil, err
	}
	p.conns[sandboxID] = nu
	p.mu.Unlock()
	if u != nil {
		// An older instance of the sandbox: its VM is gone.
		u.close()
	}
	// A Stop that began after GuestTarget has run (or will run) Drop. Check
	// again so that a connection is never kept for a VM that stops.
	if t2, err := p.M.GuestTarget(sandboxID); err != nil || t2.Generation != t.Generation {
		p.mu.Lock()
		if p.conns[sandboxID] == nu {
			delete(p.conns, sandboxID)
		}
		p.mu.Unlock()
		nu.close()
		if err == nil {
			err = apierr.New(pb.ErrorReason_VM_NOT_RUNNING, "sandbox %s was replaced during the call", sandboxID)
		}
		return nil, err
	}
	return nu, nil
}

func (p *Passthrough) dial(t agent.GuestTarget) (*upstream, error) {
	port := p.Port
	if port == 0 {
		port = DefaultDaemonPort
	}
	uds := t.VsockUDS
	conn, err := grpc.NewClient("passthrough:///guest-daemon",
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) {
			dctx, cancel := context.WithTimeout(ctx, dialTimeout)
			defer cancel()
			return fcvm.DialVsock(dctx, uds, port)
		}),
		grpc.WithConnectParams(grpc.ConnectParams{
			Backoff:           backoff.Config{BaseDelay: 50 * time.Millisecond, Multiplier: 2, Jitter: 0.2, MaxDelay: time.Second},
			MinConnectTimeout: dialTimeout,
		}),
		grpc.WithIdleTimeout(upstreamIdle),
		grpc.WithDefaultCallOptions(
			grpc.ForceCodecV2(rawCodec{}),
			grpc.MaxCallRecvMsgSize(MaxMessageBytes),
			grpc.MaxCallSendMsgSize(MaxMessageBytes),
		),
	)
	if err != nil {
		return nil, err
	}
	return &upstream{gen: t.Generation, conn: conn, dropped: make(chan struct{})}, nil
}

// InstallKey sets the daemon key and the egress CA of vm (SetKey over
// vsock). It waits for the daemon to accept the connection, up to KeyTimeout.
func (p *Passthrough) InstallKey(ctx context.Context, vm agent.VM, key string, egressCA []byte) error {
	u, err := p.get(vm.SandboxID)
	if err != nil {
		return err
	}
	if u.gen != vm.Generation {
		return apierr.New(pb.ErrorReason_VM_NOT_RUNNING, "sandbox %s was replaced during Create", vm.SandboxID)
	}
	timeout := p.KeyTimeout
	if timeout == 0 {
		timeout = DefaultKeyTimeout
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	_, err = sdpb.NewSandboxdClient(u.conn).SetKey(ctx, &sdpb.SetKeyRequest{Key: key, EgressCaPem: egressCA}, grpc.WaitForReady(true))
	switch {
	case err == nil:
		return nil
	case u.isDropped():
		return apierr.New(pb.ErrorReason_VM_NOT_RUNNING, "sandbox %s VM stopped during Create", vm.SandboxID)
	case status.Code(err) == codes.Unavailable, status.Code(err) == codes.DeadlineExceeded:
		if errors.Is(ctx.Err(), context.Canceled) {
			return ctx.Err()
		}
		return apierr.New(pb.ErrorReason_GUEST_UNREACHABLE, "guest daemon of sandbox %s did not take the key: %s", vm.SandboxID, status.Convert(err).Message())
	default:
		return apierr.New(pb.ErrorReason_GUEST_KEY_REJECTED, "guest daemon of sandbox %s: %s", vm.SandboxID, status.Convert(err).Message())
	}
}

var bothStreams = &grpc.StreamDesc{ClientStreams: true, ServerStreams: true}

// handle is the grpc.UnknownServiceHandler.
func (p *Passthrough) handle(_ any, ss grpc.ServerStream) error {
	method, ok := grpc.MethodFromServerStream(ss)
	if !ok || !strings.HasPrefix(method, "/"+DaemonService+"/") {
		return status.Errorf(codes.Unimplemented, "unknown method %s", method)
	}
	if method == sdpb.Sandboxd_SetKey_FullMethodName {
		return toStatus(apierr.New(pb.ErrorReason_METHOD_NOT_ALLOWED, "only the node agent sets the guest daemon key (Create)"))
	}
	ctx := ss.Context()
	md, _ := metadata.FromIncomingContext(ctx)
	ids := md.Get(SandboxIDHeader)
	if len(ids) != 1 {
		return toStatus(apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "set exactly one %s metadata value", SandboxIDHeader))
	}
	u, err := p.get(ids[0])
	if err != nil {
		return toStatus(err)
	}

	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	cs, err := u.conn.NewStream(metadata.NewOutgoingContext(ctx, forwardMD(md)), bothStreams, method)
	if err != nil {
		return p.upstreamErr(ctx, u, ids[0], err, true)
	}
	upErr := make(chan error, 1)
	go func() { upErr <- pumpUp(ss, cs) }()
	downErr := make(chan error, 1)
	go func() { downErr <- pumpDown(cs, ss) }()
	for {
		select {
		case err := <-upErr:
			if err == nil {
				// The client is done sending; wait for the daemon's reply.
				upErr = nil
				continue
			}
			// The client failed. Cancel the daemon call.
			cancel()
			<-downErr
			return err
		case err := <-downErr:
			if err == nil {
				return nil
			}
			var dErr *downstreamErr
			if errors.As(err, &dErr) {
				return dErr.err
			}
			return p.upstreamErr(ctx, u, ids[0], err, false)
		}
	}
}

// upstreamErr maps an error of the daemon side. A daemon status passes
// through unchanged. The agent's own reasons say when the VM stopped during
// the call or the daemon did not accept the connection.
func (p *Passthrough) upstreamErr(ctx context.Context, u *upstream, id string, err error, opening bool) error {
	if u.isDropped() {
		return toStatus(apierr.New(pb.ErrorReason_VM_NOT_RUNNING, "sandbox %s VM stopped during the call", id))
	}
	if ctx.Err() != nil {
		return err
	}
	if opening && status.Code(err) == codes.Unavailable {
		return toStatus(apierr.New(pb.ErrorReason_GUEST_UNREACHABLE, "guest daemon of sandbox %s: %v", id, status.Convert(err).Message()))
	}
	return err
}

// downstreamErr is a failure to send to the agent's client.
type downstreamErr struct{ err error }

func (e *downstreamErr) Error() string { return e.err.Error() }

// pumpUp copies client messages to the daemon. It returns nil when the client
// ends its send side, or when the daemon has ended the call (its status
// comes from pumpDown).
func pumpUp(ss grpc.ServerStream, cs grpc.ClientStream) error {
	for {
		f := &rawFrame{}
		if err := ss.RecvMsg(f); err != nil {
			if errors.Is(err, io.EOF) {
				_ = cs.CloseSend()
				return nil
			}
			return err
		}
		if err := cs.SendMsg(f); err != nil {
			// io.EOF: the daemon ended the call; RecvMsg gets the status.
			return nil
		}
	}
}

// pumpDown copies the daemon's header, messages and trailer to the client.
// It returns nil at a clean end, the daemon's status, or a downstreamErr.
func pumpDown(cs grpc.ClientStream, ss grpc.ServerStream) error {
	sentHeader := false
	for {
		f := &rawFrame{}
		err := cs.RecvMsg(f)
		if err != nil {
			if !sentHeader {
				if md, hErr := cs.Header(); hErr == nil && len(md) > 0 {
					_ = ss.SetHeader(md)
				}
			}
			ss.SetTrailer(cs.Trailer())
			if errors.Is(err, io.EOF) {
				return nil
			}
			return err
		}
		if !sentHeader {
			md, hErr := cs.Header()
			if hErr != nil {
				return hErr
			}
			if err := ss.SendHeader(md); err != nil {
				return &downstreamErr{err: err}
			}
			sentHeader = true
		}
		if err := ss.SendMsg(f); err != nil {
			return &downstreamErr{err: err}
		}
	}
}

// forwardMD copies the caller's metadata without the routing key and the
// headers that gRPC sets itself. The daemon key (x-sandboxd-key) goes
// through.
func forwardMD(in metadata.MD) metadata.MD {
	out := metadata.MD{}
	for k, v := range in {
		if k == SandboxIDHeader || strings.HasPrefix(k, ":") || strings.HasPrefix(k, "grpc-") {
			continue
		}
		switch k {
		case "content-type", "user-agent", "te", "authority":
			continue
		}
		out[k] = append([]string(nil), v...)
	}
	return out
}

// rawFrame is one message as bytes, as it is on the wire.
type rawFrame struct{ data []byte }

// rawCodec passes rawFrame bytes as they are and encodes other messages
// (the typed HostAgent service) with the proto codec.
type rawCodec struct{}

func (rawCodec) Name() string { return "proto" }

func (rawCodec) Marshal(v any) (mem.BufferSlice, error) {
	if f, ok := v.(*rawFrame); ok {
		return mem.BufferSlice{mem.SliceBuffer(f.data)}, nil
	}
	return encoding.GetCodecV2("proto").Marshal(v)
}

func (rawCodec) Unmarshal(data mem.BufferSlice, v any) error {
	if f, ok := v.(*rawFrame); ok {
		f.data = data.Materialize()
		return nil
	}
	return encoding.GetCodecV2("proto").Unmarshal(data, v)
}
