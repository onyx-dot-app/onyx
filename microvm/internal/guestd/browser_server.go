package guestd

import (
	"context"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

var errNoBrowser = status.Error(codes.Unimplemented, "this daemon has no browser")

// BrowserStart implements pb.SandboxdServer. Chrome gets the env that a
// command with no env of its own gets.
func (s *Server) BrowserStart(ctx context.Context, _ *pb.BrowserStartRequest) (*pb.BrowserStartResponse, error) {
	b := s.cfg.Browser
	if b == nil {
		return nil, errNoBrowser
	}
	port, started, err := b.Start(ctx, s.commandEnv(nil))
	if err != nil {
		return nil, apiError(pb.ErrorReason_BROWSER_START_FAILED, "%v", err)
	}
	return &pb.BrowserStartResponse{CdpPort: uint32(port), Started: started}, nil
}

// BrowserStop implements pb.SandboxdServer.
func (s *Server) BrowserStop(context.Context, *pb.BrowserStopRequest) (*pb.BrowserStopResponse, error) {
	b := s.cfg.Browser
	if b == nil {
		return nil, errNoBrowser
	}
	stopped, err := b.Stop()
	if err != nil {
		return nil, apiError(pb.ErrorReason_INTERNAL, "stop browser: %v", err)
	}
	return &pb.BrowserStopResponse{Stopped: stopped}, nil
}
