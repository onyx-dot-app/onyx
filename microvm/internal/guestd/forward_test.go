package guestd

import (
	"bufio"
	"context"
	"io"
	"net"
	"path/filepath"
	"slices"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// tcpForwards is a Forwards whose "vsock" listeners are TCP listeners on
// 127.0.0.1, and whose guest ports all reach target.
type tcpForwards struct {
	*Forwards
	mu    sync.Mutex
	addrs map[uint32]string
}

func newTCPForwards(t *testing.T, target string, maxConns int) *tcpForwards {
	t.Helper()
	f := &tcpForwards{addrs: map[uint32]string{}}
	f.Forwards = &Forwards{
		Reserved: 52, MaxConns: maxConns,
		Listen: func(port uint32) (net.Listener, error) {
			ln, err := net.Listen("tcp", "127.0.0.1:0")
			if err == nil {
				f.mu.Lock()
				f.addrs[port] = ln.Addr().String()
				f.mu.Unlock()
			}
			return ln, err
		},
		Dial: func(ctx context.Context, _ uint32) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, "tcp", target)
		},
	}
	t.Cleanup(f.Close)
	return f
}

func (f *tcpForwards) addr(port uint32) string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.addrs[port]
}

// echoServer echoes lines until the client closes.
func echoServer(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				defer func() { _ = c.Close() }()
				_, _ = io.Copy(c, c)
			}()
		}
	}()
	return ln.Addr().String()
}

func echoOnce(t *testing.T, c net.Conn, msg string) {
	t.Helper()
	_ = c.SetDeadline(time.Now().Add(5 * time.Second))
	if _, err := io.WriteString(c, msg+"\n"); err != nil {
		t.Fatal(err)
	}
	got, err := bufio.NewReader(c).ReadString('\n')
	if err != nil || got != msg+"\n" {
		t.Fatalf("echo: %q %v", got, err)
	}
}

// A forwarded port splices to the guest service, caps its live
// connections, and closes the client when the service closes.
func TestForwardsSplice(t *testing.T) {
	f := newTCPForwards(t, echoServer(t), 1)
	if got := f.Set([]uint32{3010}); !slices.Equal(got, []uint32{3010}) {
		t.Fatalf("Set: %v", got)
	}
	c1, err := net.Dial("tcp", f.addr(3010))
	if err != nil {
		t.Fatal(err)
	}
	echoOnce(t, c1, "one")
	// Over the cap: the second client is reset at once.
	// The reset can already fail the connect.
	if c2, err := net.Dial("tcp", f.addr(3010)); err == nil {
		_ = c2.SetReadDeadline(time.Now().Add(5 * time.Second))
		if n, err := c2.Read(make([]byte, 1)); err == nil || isTimeout(err) {
			t.Fatalf("second client over the cap: read %d bytes, %v", n, err)
		}
		_ = c2.Close()
	}
	_ = c1.Close()
	// The slot comes back after the first client closes.
	deadline := time.Now().Add(5 * time.Second)
	for {
		var got string
		c3, err := net.Dial("tcp", f.addr(3010))
		if err == nil {
			_ = c3.SetDeadline(time.Now().Add(time.Second))
			_, _ = io.WriteString(c3, "three\n")
			got, err = bufio.NewReader(c3).ReadString('\n')
			_ = c3.Close()
		}
		if err == nil && got == "three\n" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("slot not freed: %q %v", got, err)
		}
		time.Sleep(20 * time.Millisecond)
	}
	old := f.addr(3010)
	f.Set([]uint32{3011})
	if c, err := net.Dial("tcp", old); err == nil {
		_ = c.Close()
		t.Fatal("port 3010 still listens after Set([3011])")
	}

	// A guest port with no service: the client is closed, not left open.
	none := newTCPForwards(t, "127.0.0.1:1", 0)
	none.Set([]uint32{3011})
	c4, err := net.Dial("tcp", none.addr(3011))
	if err != nil {
		t.Fatal(err)
	}
	_ = c4.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := c4.Read(make([]byte, 1)); err == nil || isTimeout(err) {
		t.Fatalf("no guest service: %v", err)
	}
	_ = c4.Close()
}

func isTimeout(err error) bool {
	ne, ok := err.(net.Error)
	return ok && ne.Timeout()
}

// A restarted daemon forwards the ports of the SetKey it kept.
func TestForwardsSurviveRestart(t *testing.T) {
	state := filepath.Join(t.TempDir(), "run", "init.json")
	target := echoServer(t)
	h := newHarness(t, execs.Config{}, Config{StateFile: state, Forwards: newTCPForwards(t, target, 0).Forwards})
	if _, err := h.srv.SetKey(context.Background(), &pb.SetKeyRequest{Key: testKey, DialPorts: []uint32{3010, 3020}}); err != nil {
		t.Fatal(err)
	}
	h.initialized()

	m, err := execs.NewManager(execs.Config{Isolator: execs.ProcessGroups{}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(m.Shutdown)
	f2 := newTCPForwards(t, target, 0)
	srv, err := NewServer(Config{StateFile: state, Forwards: f2.Forwards}, (&fakeSys{}).system(), m)
	if err != nil {
		t.Fatal(err)
	}
	hr, err := srv.Health(context.Background(), &pb.HealthRequest{})
	if err != nil || !slices.Equal(hr.GetDialPorts(), []uint32{3010, 3020}) {
		t.Fatalf("restarted daemon forwards %v %v", hr.GetDialPorts(), err)
	}
	c, err := net.Dial("tcp", f2.addr(3020))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	echoOnce(t, c, "after restart")
}
