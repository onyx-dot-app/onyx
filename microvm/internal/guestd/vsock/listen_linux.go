// Package vsock is the guest side of AF_VSOCK: a net.Listener and a dialer.
package vsock

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"sync/atomic"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

// Addr is a vsock address.
type Addr struct {
	CID  uint32
	Port uint32
}

func (a Addr) Network() string { return "vsock" }
func (a Addr) String() string  { return fmt.Sprintf("vsock:%d:%d", a.CID, a.Port) }

type listener struct {
	f      *os.File
	rc     syscall.RawConn
	addr   Addr
	closed atomic.Bool
}

// Listen listens on port for any CID.
func Listen(port uint32) (net.Listener, error) {
	fd, err := unix.Socket(unix.AF_VSOCK, unix.SOCK_STREAM|unix.SOCK_CLOEXEC|unix.SOCK_NONBLOCK, 0)
	if err != nil {
		return nil, fmt.Errorf("vsock socket: %w", err)
	}
	if err := unix.Bind(fd, &unix.SockaddrVM{CID: unix.VMADDR_CID_ANY, Port: port}); err != nil {
		_ = unix.Close(fd)
		return nil, fmt.Errorf("vsock bind %d: %w", port, err)
	}
	if err := unix.Listen(fd, 128); err != nil {
		_ = unix.Close(fd)
		return nil, fmt.Errorf("vsock listen: %w", err)
	}
	// A non-blocking fd joins the Go poller, so Accept and Close interact.
	f := os.NewFile(uintptr(fd), "vsock-listener")
	rc, err := f.SyscallConn()
	if err != nil {
		_ = f.Close()
		return nil, err
	}
	return &listener{f: f, rc: rc, addr: Addr{CID: unix.VMADDR_CID_ANY, Port: port}}, nil
}

func (l *listener) Accept() (net.Conn, error) {
	var nfd int
	var sa unix.Sockaddr
	var aerr error
	err := l.rc.Read(func(fd uintptr) bool {
		nfd, sa, aerr = unix.Accept4(int(fd), unix.SOCK_CLOEXEC|unix.SOCK_NONBLOCK)
		return !errors.Is(aerr, unix.EAGAIN)
	})
	if err != nil {
		// RawConn.Read returns the poller's own "use of closed file" error,
		// not os.ErrClosed.
		if l.closed.Load() || errors.Is(err, os.ErrClosed) {
			return nil, net.ErrClosed
		}
		return nil, err
	}
	if aerr != nil {
		return nil, aerr
	}
	var remote Addr
	if vm, ok := sa.(*unix.SockaddrVM); ok {
		remote = Addr{CID: vm.CID, Port: vm.Port}
	}
	return &conn{File: os.NewFile(uintptr(nfd), "vsock-conn"), local: l.addr, remote: remote}, nil
}

func (l *listener) Close() error {
	l.closed.Store(true)
	return l.f.Close()
}
func (l *listener) Addr() net.Addr { return l.addr }

// conn is a vsock stream. os.File gives poller-backed reads and deadlines.
type conn struct {
	*os.File
	local, remote Addr
}

func (c *conn) LocalAddr() net.Addr  { return c.local }
func (c *conn) RemoteAddr() net.Addr { return c.remote }

// Dial connects to port on cid (2 is the host).
func Dial(ctx context.Context, cid, port uint32) (net.Conn, error) {
	if err := ctx.Err(); err != nil {
		return nil, fmt.Errorf("vsock connect %d:%d: %w", cid, port, err)
	}
	fd, err := unix.Socket(unix.AF_VSOCK, unix.SOCK_STREAM|unix.SOCK_CLOEXEC|unix.SOCK_NONBLOCK, 0)
	if err != nil {
		return nil, fmt.Errorf("vsock socket: %w", err)
	}
	f := os.NewFile(uintptr(fd), "vsock-conn")
	rc, err := f.SyscallConn()
	if err != nil {
		_ = f.Close()
		return nil, err
	}
	if dl, ok := ctx.Deadline(); ok {
		_ = f.SetWriteDeadline(dl)
	}
	// Cancel ends the wait for the connect through an expired write deadline.
	cbDone := make(chan struct{})
	stop := context.AfterFunc(ctx, func() {
		_ = f.SetWriteDeadline(time.Unix(1, 0))
		close(cbDone)
	})
	var cerr error
	started := false
	err = rc.Write(func(fd uintptr) bool {
		if !started {
			started = true
			cerr = unix.Connect(int(fd), &unix.SockaddrVM{CID: cid, Port: port})
			// After EINTR the connect goes on in the background, as after
			// EINPROGRESS: wait until the socket is writable.
			return !errors.Is(cerr, unix.EINPROGRESS) && !errors.Is(cerr, unix.EINTR)
		}
		// Writable: the connect finished.
		v, gerr := unix.GetsockoptInt(int(fd), unix.SOL_SOCKET, unix.SO_ERROR)
		switch {
		case gerr != nil:
			cerr = gerr
		case v != 0:
			cerr = unix.Errno(v)
		default:
			cerr = nil
		}
		return true
	})
	if err == nil {
		err = cerr
	}
	if !stop() {
		// The callback runs (or ran): wait for it, so it cannot set the
		// expired deadline on a connection that is returned. The context
		// ended, so the dial fails.
		<-cbDone
		_ = f.Close()
		return nil, fmt.Errorf("vsock connect %d:%d: %w", cid, port, ctx.Err())
	}
	if err != nil {
		_ = f.Close()
		return nil, fmt.Errorf("vsock connect %d:%d: %w", cid, port, err)
	}
	_ = f.SetWriteDeadline(time.Time{})
	return &conn{File: f, local: Addr{CID: unix.VMADDR_CID_ANY}, remote: Addr{CID: cid, Port: port}}, nil
}
