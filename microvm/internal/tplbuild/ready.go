package tplbuild

import (
	"context"
	"fmt"
	"net"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/onyx-dot-app/onyx/microvm/internal/fcvm"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// DaemonHealth returns a Ready that waits until the guest daemon answers
// Health on vsock port.
func DaemonHealth(port uint32) Ready {
	return func(ctx context.Context, vsockPath string) error {
		var last error
		for {
			last = health(ctx, vsockPath, port)
			if last == nil {
				return nil
			}
			select {
			case <-ctx.Done():
				return fmt.Errorf("guest daemon did not answer Health on vsock %d: %v", port, last)
			case <-time.After(20 * time.Millisecond):
			}
		}
	}
}

func health(ctx context.Context, vsockPath string, port uint32) error {
	conn, err := grpc.NewClient("passthrough:///guestd",
		grpc.WithContextDialer(func(ctx context.Context, _ string) (net.Conn, error) {
			return fcvm.DialVsock(ctx, vsockPath, port)
		}),
		grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return err
	}
	defer func() { _ = conn.Close() }()
	hctx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
	defer cancel()
	_, err = sdpb.NewSandboxdClient(conn).Health(hctx, &sdpb.HealthRequest{})
	return err
}
