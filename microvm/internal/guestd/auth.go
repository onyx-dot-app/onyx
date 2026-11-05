package guestd

import (
	"context"
	"crypto/subtle"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// KeyHeader is the metadata key that carries the per-VM key.
const KeyHeader = "x-sandboxd-key"

// check enforces the Init gate and the per-VM key for one call.
func (s *Server) check(ctx context.Context, method string) error {
	if method == pb.Sandboxd_Health_FullMethodName {
		return nil
	}
	s.mu.Lock()
	key, initialized := s.state.Key, s.state.Initialized
	s.mu.Unlock()
	if !initialized {
		if method == pb.Sandboxd_Init_FullMethodName {
			return nil
		}
		return apiError(pb.ErrorReason_NOT_INITIALIZED, "call Init first")
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
	return nil
}

// NewGRPCServer returns a gRPC server that serves s, with check applied to
// every call. It is the only way to serve s, so no caller can forget the
// auth interceptors. opts are added after them.
func (s *Server) NewGRPCServer(opts ...grpc.ServerOption) *grpc.Server {
	gs := grpc.NewServer(append(s.serverOptions(), opts...)...)
	pb.RegisterSandboxdServer(gs, s)
	return gs
}

// serverOptions returns the interceptors that apply check to every call.
func (s *Server) serverOptions() []grpc.ServerOption {
	return []grpc.ServerOption{
		grpc.ChainUnaryInterceptor(func(ctx context.Context, req any, info *grpc.UnaryServerInfo, h grpc.UnaryHandler) (any, error) {
			if err := s.check(ctx, info.FullMethod); err != nil {
				return nil, err
			}
			return h(ctx, req)
		}),
		grpc.ChainStreamInterceptor(func(srv any, ss grpc.ServerStream, info *grpc.StreamServerInfo, h grpc.StreamHandler) error {
			if err := s.check(ss.Context(), info.FullMethod); err != nil {
				return err
			}
			return h(srv, ss)
		}),
	}
}
