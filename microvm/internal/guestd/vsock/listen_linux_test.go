package vsock

import (
	"context"
	"errors"
	"io"
	"net"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

// noVsock reports the errors of a kernel without vsock or its loopback.
func noVsock(err error) bool {
	for _, e := range []error{unix.EAFNOSUPPORT, unix.ENODEV, unix.ENETUNREACH, unix.EHOSTUNREACH, unix.EADDRNOTAVAIL} {
		if errors.Is(err, e) {
			return true
		}
	}
	return false
}

// The tests use the vsock loopback (CID 1, module vsock_loopback). They skip
// where it is missing.
func loopback(t *testing.T) (port uint32, accepted <-chan []byte) {
	t.Helper()
	for p := uint32(40000); p < 40100; p++ {
		ln, err := Listen(p)
		if noVsock(err) {
			t.Skipf("no vsock: %v", err)
		}
		if err != nil {
			continue
		}
		t.Cleanup(func() { _ = ln.Close() })
		ch := make(chan []byte, 8)
		go func() {
			for {
				c, err := ln.Accept()
				if err != nil {
					return
				}
				go func() {
					b, _ := io.ReadAll(c)
					_ = c.Close()
					ch <- b
				}()
			}
		}()
		probe, err := Dial(context.Background(), unix.VMADDR_CID_LOCAL, p)
		if noVsock(err) {
			t.Skipf("no vsock loopback: %v", err)
		}
		if err != nil {
			t.Fatalf("probe dial: %v", err)
		}
		_ = probe.Close()
		<-ch
		return p, ch
	}
	t.Fatal("no free vsock port in 40000-40099")
	return 0, nil
}

// Close makes a blocked Accept return net.ErrClosed, so serve loops end.
func TestListenerCloseEndsAccept(t *testing.T) {
	var ln net.Listener
	for p := uint32(40100); p < 40200; p++ {
		l, err := Listen(p)
		if noVsock(err) {
			t.Skipf("no vsock: %v", err)
		}
		if err == nil {
			ln = l
			break
		}
	}
	if ln == nil {
		t.Fatal("no free vsock port in 40100-40199")
	}
	done := make(chan error, 1)
	go func() {
		_, err := ln.Accept()
		done <- err
	}()
	time.Sleep(50 * time.Millisecond)
	if err := ln.Close(); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		if !errors.Is(err, net.ErrClosed) {
			t.Fatalf("accept after close: %v, want net.ErrClosed", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("accept did not return after close")
	}
	if _, err := ln.Accept(); !errors.Is(err, net.ErrClosed) {
		t.Fatalf("accept on a closed listener: %v, want net.ErrClosed", err)
	}
}

// A connection that the dial returns accepts writes: no expired deadline
// is left on it, also when the context ends right after the dial.
func TestDialConnWritable(t *testing.T) {
	port, accepted := loopback(t)
	for range 50 {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		c, err := Dial(ctx, unix.VMADDR_CID_LOCAL, port)
		cancel()
		if err != nil {
			t.Fatal(err)
		}
		time.Sleep(time.Millisecond)
		if _, err := c.Write([]byte("x")); err != nil {
			t.Fatalf("write after dial: %v", err)
		}
		_ = c.Close()
		if got := <-accepted; string(got) != "x" {
			t.Fatalf("got %q", got)
		}
	}
}

func TestDialCanceledContext(t *testing.T) {
	port, _ := loopback(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if c, err := Dial(ctx, unix.VMADDR_CID_LOCAL, port); err == nil {
		_ = c.Close()
		t.Fatal("dial with a canceled context succeeded")
	}
}

// A socket that polls writable before its connect ends is not connected.
// A new vsock socket polls writable (state TCP_CLOSE), so the poller can wake
// Dial before the host answers. The dial must wait, not return a socket whose
// first read and write fail with ENOTCONN.
func TestConnectDoneWaitsForPeer(t *testing.T) {
	sockets := map[string]int{"tcp": unix.AF_INET}
	if fd, err := unix.Socket(unix.AF_VSOCK, unix.SOCK_STREAM, 0); err == nil {
		_ = unix.Close(fd)
		sockets["vsock"] = unix.AF_VSOCK
	}
	for name, family := range sockets {
		fd, err := unix.Socket(family, unix.SOCK_STREAM|unix.SOCK_NONBLOCK, 0)
		if err != nil {
			t.Fatal(err)
		}
		if family == unix.AF_VSOCK {
			pfd := []unix.PollFd{{Fd: int32(fd), Events: unix.POLLOUT}}
			_, _ = unix.Poll(pfd, 0)
			t.Logf("new vsock socket polls writable: %v", pfd[0].Revents&unix.POLLOUT != 0)
		}
		done, err := connectDone(fd)
		_ = unix.Close(fd)
		if done || err != nil {
			t.Errorf("%s socket with no peer: done=%v err=%v, want false, nil", name, done, err)
		}
	}

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close() }()
	fd, err := unix.Socket(unix.AF_INET, unix.SOCK_STREAM, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = unix.Close(fd) }()
	port := ln.Addr().(*net.TCPAddr).Port
	if err := unix.Connect(fd, &unix.SockaddrInet4{Port: port, Addr: [4]byte{127, 0, 0, 1}}); err != nil {
		t.Fatal(err)
	}
	if done, err := connectDone(fd); !done || err != nil {
		t.Fatalf("connected socket: done=%v err=%v, want true, nil", done, err)
	}
}
