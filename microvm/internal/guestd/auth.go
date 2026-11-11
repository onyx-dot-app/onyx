package guestd

import (
	"bytes"
	"context"
	"crypto/subtle"
	"fmt"
	"slices"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	"github.com/onyx-dot-app/onyx/microvm/internal/egressca"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// KeyHeader is the metadata key that carries the per-VM key.
const KeyHeader = "x-sandboxd-key"

// check enforces the per-VM key and the Init gate for one call. Health and
// SetKey need no key; SetKey checks the key itself.
func (s *Server) check(ctx context.Context, method string) error {
	if method == pb.Sandboxd_Health_FullMethodName || method == pb.Sandboxd_SetKey_FullMethodName {
		return nil
	}
	s.mu.Lock()
	key, initialized := s.state.Key, s.state.Initialized
	s.mu.Unlock()
	if key == "" {
		return apiError(pb.ErrorReason_KEY_NOT_SET, "the node agent has not set the key")
	}
	var got string
	if md, ok := metadata.FromIncomingContext(ctx); ok {
		if v := md.Get(KeyHeader); len(v) == 1 {
			got = v[0]
		}
	}
	if subtle.ConstantTimeCompare([]byte(got), []byte(key)) != 1 {
		return apiError(pb.ErrorReason_UNAUTHENTICATED, "missing or wrong %s", KeyHeader)
	}
	if !initialized && method != pb.Sandboxd_Init_FullMethodName {
		return apiError(pb.ErrorReason_NOT_INITIALIZED, "call Init first")
	}
	return nil
}

func validateKey(key string) error {
	if n := len(key); n < minKey || n > maxKey {
		return fmt.Errorf("key must be %d to %d bytes, got %d", minKey, maxKey, n)
	}
	// Later calls send the key as gRPC metadata, which allows only printable
	// ASCII. A space can be trimmed on the way, so it is not allowed either.
	for _, c := range []byte(key) {
		if c <= ' ' || c > '~' {
			return fmt.Errorf("key must be printable ASCII with no spaces (for example hex or base64url of random bytes)")
		}
	}
	return nil
}

// SetKey implements pb.SandboxdServer. The first key stays. A call with the
// right key and an egress CA keeps that CA for the next Init. A call with
// the right key and dial ports replaces the forwarded ports at once.
func (s *Server) SetKey(_ context.Context, r *pb.SetKeyRequest) (*pb.SetKeyResponse, error) {
	if err := validateKey(r.GetKey()); err != nil {
		return nil, apiError(pb.ErrorReason_INVALID_ARGUMENT, "%v", err)
	}
	var caPEM []byte
	if raw := r.GetEgressCaPem(); len(raw) > 0 {
		ca, err := egressca.Parse(raw)
		if err != nil {
			return nil, apiError(pb.ErrorReason_INVALID_ARGUMENT, "egress_ca_pem: %v", err)
		}
		caPEM = ca.PEM
	}
	var reserved uint32
	if s.cfg.Forwards != nil {
		reserved = s.cfg.Forwards.Reserved
	}
	ports, err := validateDialPorts(r.GetDialPorts(), reserved)
	if err != nil {
		return nil, apiError(pb.ErrorReason_INVALID_ARGUMENT, "%v", err)
	}
	s.initMu.Lock()
	defer s.initMu.Unlock()
	s.mu.Lock()
	st := s.state
	s.mu.Unlock()
	already := st.Key != ""
	if already && subtle.ConstantTimeCompare([]byte(r.GetKey()), []byte(st.Key)) != 1 {
		return nil, apiError(pb.ErrorReason_KEY_ALREADY_SET, "the daemon already has a different key")
	}
	switch {
	case len(ports) > 0:
	case already && len(st.DialPorts) > 0:
		ports = st.DialPorts
	default:
		ports = DefaultDialPorts
	}
	if !already || (caPEM != nil && !bytes.Equal(caPEM, st.EgressCA)) || !slices.Equal(ports, st.DialPorts) {
		st.Key = r.GetKey()
		if caPEM != nil {
			st.EgressCA = caPEM
		}
		st.DialPorts = ports
		if err := s.saveState(st); err != nil {
			return nil, apiError(pb.ErrorReason_INTERNAL, "save state: %v", err)
		}
		s.mu.Lock()
		s.state.Key, s.state.EgressCA, s.state.DialPorts = st.Key, st.EgressCA, st.DialPorts
		s.mu.Unlock()
		s.cfg.Log.Info("key set", "already_set", already, "egress_ca", caPEM != nil, "dial_ports", ports)
	}
	// Also on a repeat call: it opens a port that failed to listen before.
	// A failure fails the call, so the node agent's Create fails and can
	// be retried; the key and ports stay saved.
	var forwarded []uint32
	if s.cfg.Forwards != nil {
		if forwarded, err = s.cfg.Forwards.Set(ports); err != nil {
			return nil, apiError(pb.ErrorReason_INTERNAL, "forward dial ports: %v", err)
		}
	}
	return &pb.SetKeyResponse{AlreadySet: already, DialPorts: forwarded}, nil
}

// NewGRPCServer returns a gRPC server that serves s, with check applied to
// every call. It is the only way to serve s, so no caller can forget the
// auth interceptors. opts are added after them.
func (s *Server) NewGRPCServer(opts ...grpc.ServerOption) *grpc.Server {
	gs := grpc.NewServer(append(s.serverOptions(), opts...)...)
	pb.RegisterSandboxdServer(gs, s)
	return gs
}

// activity marks an accepted call as VM activity for the idle reclaim and
// returns the function that ends it. Health is not activity: the node agent
// and the api_server poll it.
func (s *Server) activity(method string) func() {
	r := s.cfg.Reclaimer
	if r == nil || method == pb.Sandboxd_Health_FullMethodName {
		return func() {}
	}
	r.Begin()
	return r.End
}

// serverOptions returns the interceptors that apply check to every call.
func (s *Server) serverOptions() []grpc.ServerOption {
	return []grpc.ServerOption{
		grpc.ChainUnaryInterceptor(func(ctx context.Context, req any, info *grpc.UnaryServerInfo, h grpc.UnaryHandler) (any, error) {
			if err := s.check(ctx, info.FullMethod); err != nil {
				return nil, err
			}
			defer s.activity(info.FullMethod)()
			return h(ctx, req)
		}),
		grpc.ChainStreamInterceptor(func(srv any, ss grpc.ServerStream, info *grpc.StreamServerInfo, h grpc.StreamHandler) error {
			if err := s.check(ss.Context(), info.FullMethod); err != nil {
				return err
			}
			defer s.activity(info.FullMethod)()
			return h(srv, ss)
		}),
	}
}
