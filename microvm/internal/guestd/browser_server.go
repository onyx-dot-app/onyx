package guestd

import (
	"context"
	"path/filepath"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/browser"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

var errNoBrowser = status.Error(codes.Unimplemented, "this daemon has no browser")

// BrowserStart implements pb.SandboxdServer. Chrome and the service get the
// env that a command with no env of its own gets. The profile is
// <session dir>/chrome. service_protocol is set only when the service runs
// and the relay listens.
func (s *Server) BrowserStart(ctx context.Context, req *pb.BrowserStartRequest) (*pb.BrowserStartResponse, error) {
	b := s.cfg.Browser
	if b == nil {
		return nil, errNoBrowser
	}
	dir, err := s.files.SessionDir(req.GetProfileSessionId())
	if err != nil {
		return nil, fileError(err)
	}
	if _, _, err := b.Start(ctx, filepath.Join(dir, "chrome"), s.commandEnv(nil)); err != nil {
		return nil, apiError(pb.ErrorReason_BROWSER_START_FAILED, "%v", err)
	}
	resp := &pb.BrowserStartResponse{}
	if s.cfg.BrowserRelay && b.HasService() {
		resp.ServiceProtocol = browser.ServiceProtocol
	}
	return resp, nil
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
