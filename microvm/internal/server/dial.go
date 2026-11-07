package server

import (
	"context"
	"errors"
	"io"
	"net"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// DefaultDialPorts are the guest ports Dial allows: the prototype guest
// daemon (52) and the app preview (3010).
var DefaultDialPorts = []uint32{52, 3010}

const (
	dialTimeout = 5 * time.Second
	dialChunk   = 32 << 10
)

// Dial implements pb.HostAgentServer.
func (s *Service) Dial(stream pb.HostAgent_DialServer) error {
	first, err := stream.Recv()
	if err != nil {
		return err
	}
	port := first.GetGuestPort()
	if !s.dialAllowed(port) {
		return toStatus(apierr.New(pb.ErrorReason_PORT_NOT_ALLOWED, "guest port %d is not allowed", port))
	}
	uds, err := s.M.DialTarget(first.GetSandboxId())
	if err != nil {
		return toStatus(err)
	}
	ctx := stream.Context()
	dctx, cancel := context.WithTimeout(ctx, dialTimeout)
	conn, err := fcvm.DialVsock(dctx, uds, port)
	cancel()
	if err != nil {
		return toStatus(apierr.New(pb.ErrorReason_GUEST_UNREACHABLE, "guest port %d: %v", port, err))
	}
	defer func() { _ = conn.Close() }()
	// Closing the connection when the call ends stops both copy loops.
	stop := context.AfterFunc(ctx, func() { _ = conn.Close() })
	defer stop()

	// Both directions run at once, from the first frame on: a guest that
	// writes while it reads must not block a large first frame.
	upErr := make(chan error, 1)
	go func() { upErr <- s.upload(stream, conn, first.GetData()) }()
	downErr := make(chan error, 1)
	go func() { downErr <- download(ctx, stream, conn) }()
	select {
	case err := <-downErr:
		return err
	case err := <-upErr:
		if err == nil {
			// The client is done sending. Keep reading the guest reply: a
			// vsock half-close would drop it.
			return <-downErr
		}
		_ = conn.Close()
		<-downErr
		return err
	}
}

// upload copies the client frames to the guest. It returns nil when the
// client ends its send side.
func (s *Service) upload(stream pb.HostAgent_DialServer, conn net.Conn, first []byte) error {
	data := first
	for {
		if len(data) > 0 {
			if _, err := conn.Write(data); err != nil {
				return toStatus(apierr.New(pb.ErrorReason_GUEST_UNREACHABLE, "write to guest: %v", err))
			}
		}
		f, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return err
		}
		data = f.GetData()
	}
}

// download copies the guest bytes to the client until the guest closes.
func download(ctx context.Context, stream pb.HostAgent_DialServer, conn net.Conn) error {
	buf := make([]byte, dialChunk)
	for {
		n, err := conn.Read(buf)
		if n > 0 {
			if sendErr := stream.Send(&pb.DialFrame{Data: buf[:n]}); sendErr != nil {
				return sendErr
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) || errors.Is(err, net.ErrClosed) {
				return ctx.Err()
			}
			return err
		}
	}
}

func (s *Service) dialAllowed(port uint32) bool {
	ports := s.DialPorts
	if ports == nil {
		ports = DefaultDialPorts
	}
	for _, p := range ports {
		if p == port {
			return true
		}
	}
	return false
}
