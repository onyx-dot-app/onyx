package guestd

import (
	"context"
	"errors"

	"google.golang.org/protobuf/types/known/durationpb"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/browser"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

var browserStates = map[browser.State]pb.BrowserState{
	browser.Stopped:    pb.BrowserState_BROWSER_STOPPED,
	browser.Starting:   pb.BrowserState_BROWSER_STARTING,
	browser.Running:    pb.BrowserState_BROWSER_RUNNING,
	browser.Restarting: pb.BrowserState_BROWSER_RESTARTING,
	browser.Stopping:   pb.BrowserState_BROWSER_STOPPING,
	browser.Failed:     pb.BrowserState_BROWSER_FAILED,
}

func toBrowserStatus(s browser.Status) *pb.BrowserStatus {
	out := &pb.BrowserStatus{
		State: browserStates[s.State], CdpPort: s.VsockPort, CdpPath: s.CDPPath, Pid: int32(s.PID),
		Restarts: uint32(s.Restarts), LastError: s.LastError, MemoryBytes: s.MemoryBytes,
		MemoryMaxBytes: s.MemoryMax, ProfileDir: s.ProfileDir,
	}
	if !s.StartedAt.IsZero() {
		out.StartedAt = timestamppb.New(s.StartedAt)
		out.StartDuration = durationpb.New(s.StartDuration)
	}
	return out
}

func browserError(err error) error {
	switch {
	case errors.Is(err, browser.ErrUnavailable):
		return apiError(pb.ErrorReason_BROWSER_NOT_AVAILABLE, "%v", err)
	case errors.Is(err, browser.ErrProfile):
		return apiError(pb.ErrorReason_BROWSER_PROFILE_FAILED, "%v", err)
	case errors.Is(err, browser.ErrStartFailed):
		return apiError(pb.ErrorReason_BROWSER_START_FAILED, "%v", err)
	default:
		return execError(err)
	}
}

func (s *Server) browserManager() (*browser.Manager, error) {
	if s.cfg.Browser == nil {
		return nil, apiError(pb.ErrorReason_BROWSER_NOT_AVAILABLE, "the daemon runs without a browser")
	}
	return s.cfg.Browser, nil
}

// BrowserStart implements pb.SandboxdServer.
func (s *Server) BrowserStart(ctx context.Context, _ *pb.BrowserStartRequest) (*pb.BrowserStartResponse, error) {
	b, err := s.browserManager()
	if err != nil {
		return nil, err
	}
	st, already, err := b.Start(ctx)
	if err != nil {
		return nil, browserError(err)
	}
	return &pb.BrowserStartResponse{Status: toBrowserStatus(st), AlreadyRunning: already}, nil
}

// BrowserStop implements pb.SandboxdServer.
func (s *Server) BrowserStop(ctx context.Context, _ *pb.BrowserStopRequest) (*pb.BrowserStopResponse, error) {
	b, err := s.browserManager()
	if err != nil {
		return nil, err
	}
	r, err := b.Stop(ctx)
	if err != nil {
		return nil, browserError(err)
	}
	return &pb.BrowserStopResponse{
		WasRunning: r.WasRunning, Clean: r.Clean, ProfileSaved: r.ProfileSaved,
		ProfileBytes: uint64(max(r.ProfileBytes, 0)), ProfileError: r.ProfileError, ProfileDir: b.Status().ProfileDir,
	}, nil
}

// BrowserStatus implements pb.SandboxdServer.
func (s *Server) BrowserStatus(context.Context, *pb.BrowserStatusRequest) (*pb.BrowserStatusResponse, error) {
	b, err := s.browserManager()
	if err != nil {
		return nil, err
	}
	return &pb.BrowserStatusResponse{Status: toBrowserStatus(b.Status())}, nil
}
