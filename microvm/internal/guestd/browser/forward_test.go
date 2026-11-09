package browser

import (
	"errors"
	"io"
	"log/slog"
	"net"
	"sync"
	"testing"
	"time"
)

// closedErrListener returns a non-net.ErrClosed error after Close, as the
// guest vsock listener's raw poller read does ("use of closed file").
type closedErrListener struct {
	once sync.Once
	done chan struct{}
}

func (l *closedErrListener) Accept() (net.Conn, error) {
	<-l.done
	return nil, errors.New("use of closed file")
}

func (l *closedErrListener) Close() error {
	l.once.Do(func() { close(l.done) })
	return nil
}

func (l *closedErrListener) Addr() net.Addr { return &net.UnixAddr{} }

func TestForwarderCloseEndsAcceptLoop(t *testing.T) {
	f := newForwarder(&closedErrListener{done: make(chan struct{})}, "127.0.0.1:1", slog.New(slog.NewTextHandler(io.Discard, nil)))
	done := make(chan struct{})
	go func() { f.close(); close(done) }()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("close did not return: the accept loop keeps running")
	}
}

func TestForwarderClosesOpenConnections(t *testing.T) {
	target, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = target.Close() }()
	go func() {
		for {
			c, err := target.Accept()
			if err != nil {
				return
			}
			go func() { _, _ = io.Copy(c, c) }()
		}
	}()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	f := newForwarder(ln, target.Addr().String(), slog.New(slog.NewTextHandler(io.Discard, nil)))
	c, err := net.Dial("tcp", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	if _, err := c.Write([]byte("ping")); err != nil {
		t.Fatal(err)
	}
	buf := make([]byte, 4)
	if _, err := io.ReadFull(c, buf); err != nil || string(buf) != "ping" {
		t.Fatalf("echo %q %v", buf, err)
	}
	f.close()
	_ = c.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := c.Read(buf); err == nil {
		t.Fatal("connection still open after close")
	}
}
