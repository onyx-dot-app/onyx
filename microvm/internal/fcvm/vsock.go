package fcvm

import (
	"bufio"
	"context"
	"fmt"
	"net"
	"strings"
	"time"
)

// DialVsock opens a stream to a guest vsock port through the Firecracker
// vsock UDS (host-initiated connection: "CONNECT <port>\n", then "OK <n>\n").
func DialVsock(ctx context.Context, udsPath string, port uint32) (net.Conn, error) {
	var d net.Dialer
	c, err := d.DialContext(ctx, "unix", udsPath)
	if err != nil {
		return nil, err
	}
	if dl, ok := ctx.Deadline(); ok {
		_ = c.SetDeadline(dl)
	}
	if _, err := fmt.Fprintf(c, "CONNECT %d\n", port); err != nil {
		_ = c.Close()
		return nil, err
	}
	br := bufio.NewReader(c)
	ack, err := br.ReadString('\n')
	if err != nil {
		_ = c.Close()
		return nil, fmt.Errorf("vsock CONNECT %d: %w", port, err)
	}
	if !strings.HasPrefix(ack, "OK ") {
		_ = c.Close()
		return nil, fmt.Errorf("vsock CONNECT %d: %q", port, strings.TrimSpace(ack))
	}
	_ = c.SetDeadline(time.Time{})
	if br.Buffered() > 0 {
		return &bufferedConn{Conn: c, r: br}, nil
	}
	return c, nil
}

type bufferedConn struct {
	net.Conn
	r *bufio.Reader
}

func (b *bufferedConn) Read(p []byte) (int, error) { return b.r.Read(p) }
