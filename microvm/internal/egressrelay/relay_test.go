package egressrelay

import (
	"bytes"
	"context"
	"crypto/rand"
	"errors"
	"io"
	"net"
	"path/filepath"
	"sync"
	"syscall"
	"testing"
	"time"
)

// upstream is a fake host side: a Unix socket in place of vsock. It echoes
// bytes and records each connection.
type upstream struct {
	ln    net.Listener
	mu    sync.Mutex
	conns []net.Conn
	ended chan struct{} // one value per upstream connection that ended
}

func newUpstream(t *testing.T) *upstream {
	t.Helper()
	ln, err := net.Listen("unix", filepath.Join(t.TempDir(), "up.sock"))
	if err != nil {
		t.Fatal(err)
	}
	u := &upstream{ln: ln, ended: make(chan struct{}, 64)}
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			u.mu.Lock()
			u.conns = append(u.conns, c)
			u.mu.Unlock()
			go func() {
				_, _ = io.Copy(c, c)
				_ = c.Close()
				u.ended <- struct{}{}
			}()
		}
	}()
	t.Cleanup(func() { _ = ln.Close() })
	return u
}

func (u *upstream) dial(ctx context.Context) (net.Conn, error) {
	var d net.Dialer
	return d.DialContext(ctx, "unix", u.ln.Addr().String())
}

func (u *upstream) waitEnded(t *testing.T, n int) {
	t.Helper()
	for range n {
		select {
		case <-u.ended:
		case <-time.After(5 * time.Second):
			t.Fatal("upstream connection was not closed")
		}
	}
}

func startRelay(t *testing.T, r *Relay) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- r.Serve(ln) }()
	t.Cleanup(func() {
		_ = ln.Close()
		if err := <-done; err != nil {
			t.Errorf("Serve: %v", err)
		}
		r.Reset()
	})
	return ln.Addr().String()
}

func dial(t *testing.T, addr string) net.Conn {
	t.Helper()
	c, err := net.Dial("tcp", addr)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = c.Close() })
	return c
}

// roundTrip writes msg and reads it back through the echo upstream.
func roundTrip(t *testing.T, c net.Conn, msg []byte) {
	t.Helper()
	go func() { _, _ = c.Write(msg) }()
	got := make([]byte, len(msg))
	_ = c.SetReadDeadline(time.Now().Add(10 * time.Second))
	if _, err := io.ReadFull(c, got); err != nil {
		t.Fatalf("read back: %v", err)
	}
	_ = c.SetReadDeadline(time.Time{})
	if !bytes.Equal(got, msg) {
		t.Fatal("data differs")
	}
}

func waitLive(t *testing.T, r *Relay, n int) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for r.Live() != n {
		if time.Now().After(deadline) {
			t.Fatalf("live = %d, want %d", r.Live(), n)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

func TestSplice(t *testing.T) {
	u := newUpstream(t)
	r := &Relay{Dial: u.dial}
	addr := startRelay(t, r)
	c := dial(t, addr)
	big := make([]byte, 4<<20)
	_, _ = rand.Read(big)
	roundTrip(t, c, big)
	roundTrip(t, c, []byte("small"))
}

func TestClientCloseClosesUpstream(t *testing.T) {
	u := newUpstream(t)
	r := &Relay{Dial: u.dial}
	addr := startRelay(t, r)
	c := dial(t, addr)
	roundTrip(t, c, []byte("x"))
	// A half-close from the client ends the whole pair (vsock has no half-close).
	_ = c.(*net.TCPConn).CloseWrite()
	u.waitEnded(t, 1)
	waitLive(t, r, 0)
}

func TestUpstreamCloseClosesClient(t *testing.T) {
	u := newUpstream(t)
	r := &Relay{Dial: u.dial}
	addr := startRelay(t, r)
	c := dial(t, addr)
	roundTrip(t, c, []byte("x"))
	u.mu.Lock()
	_ = u.conns[0].Close()
	u.mu.Unlock()
	_ = c.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := c.Read(make([]byte, 1)); !errors.Is(err, io.EOF) {
		t.Fatalf("client read after upstream close: %v", err)
	}
}

func TestResetClosesLiveConnections(t *testing.T) {
	u := newUpstream(t)
	r := &Relay{Dial: u.dial}
	addr := startRelay(t, r)
	var cs []net.Conn
	for range 3 {
		c := dial(t, addr)
		roundTrip(t, c, []byte("x"))
		cs = append(cs, c)
	}
	waitLive(t, r, 3)
	if n := r.Reset(); n != 3 {
		t.Fatalf("Reset closed %d, want 3", n)
	}
	for _, c := range cs {
		_ = c.SetReadDeadline(time.Now().Add(5 * time.Second))
		_, err := c.Read(make([]byte, 1))
		if !errors.Is(err, syscall.ECONNRESET) {
			t.Fatalf("client after reset: %v, want ECONNRESET", err)
		}
	}
	u.waitEnded(t, 3)
	waitLive(t, r, 0)
	// New connections still work.
	roundTrip(t, dial(t, addr), []byte("after reset"))
}

func TestConnectionCap(t *testing.T) {
	u := newUpstream(t)
	r := &Relay{Dial: u.dial, MaxConns: 2}
	addr := startRelay(t, r)
	c1, c2 := dial(t, addr), dial(t, addr)
	roundTrip(t, c1, []byte("1"))
	roundTrip(t, c2, []byte("2"))
	// The relay resets a client above the cap at once. The RST can arrive
	// before connect returns, so the dial itself may fail.
	if c3, err := net.Dial("tcp", addr); err == nil {
		defer func() { _ = c3.Close() }()
		_ = c3.SetReadDeadline(time.Now().Add(5 * time.Second))
		_, _ = c3.Write([]byte("3"))
		if _, err := c3.Read(make([]byte, 1)); err == nil {
			t.Fatal("third connection above the cap was served")
		}
	} else if !errors.Is(err, syscall.ECONNRESET) {
		t.Fatalf("third dial: %v", err)
	}
	_ = c1.Close()
	waitLive(t, r, 1)
	roundTrip(t, dial(t, addr), []byte("4"))
}

func TestUpstreamDownClosesClient(t *testing.T) {
	r := &Relay{Dial: func(context.Context) (net.Conn, error) { return nil, errors.New("no host") }}
	addr := startRelay(t, r)
	c := dial(t, addr)
	_ = c.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := c.Read(make([]byte, 1)); err == nil {
		t.Fatal("client stayed open without an upstream")
	}
}

// flakyListener fails Accept a few times with a transient error.
type flakyListener struct {
	net.Listener
	mu    sync.Mutex
	fails int
}

func (f *flakyListener) Accept() (net.Conn, error) {
	f.mu.Lock()
	if f.fails > 0 {
		f.fails--
		f.mu.Unlock()
		return nil, syscall.EMFILE
	}
	f.mu.Unlock()
	return f.Listener.Accept()
}

func TestServeSurvivesAcceptErrors(t *testing.T) {
	u := newUpstream(t)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	r := &Relay{Dial: u.dial}
	done := make(chan error, 1)
	go func() { done <- r.Serve(&flakyListener{Listener: ln, fails: 3}) }()
	roundTrip(t, dial(t, ln.Addr().String()), []byte("ok"))
	_ = ln.Close()
	if err := <-done; err != nil {
		t.Fatalf("Serve after Close: %v", err)
	}
	r.Reset()
}

func TestValidate(t *testing.T) {
	dialer := func(context.Context) (net.Conn, error) { return nil, nil }
	if err := (&Relay{Dial: dialer, IdleTimeout: time.Minute}).Validate(); err == nil {
		t.Fatal("idle timeout under 180s accepted")
	}
	if err := (&Relay{Dial: dialer, IdleTimeout: 5 * time.Minute}).Validate(); err != nil {
		t.Fatal(err)
	}
	if err := (&Relay{}).Validate(); err == nil {
		t.Fatal("missing Dial accepted")
	}
	if err := (&Relay{Dial: dialer, MaxConns: -1}).Validate(); err == nil {
		t.Fatal("negative MaxConns accepted")
	}
}

// Reset also resets a client whose upstream connection is still opening,
// and cancels that dial.
func TestResetClosesPendingDial(t *testing.T) {
	entered, canceled := make(chan struct{}, 1), make(chan struct{}, 1)
	r := &Relay{Dial: func(ctx context.Context) (net.Conn, error) {
		entered <- struct{}{}
		<-ctx.Done()
		canceled <- struct{}{}
		return nil, ctx.Err()
	}, DialTimeout: time.Minute}
	addr := startRelay(t, r)
	c := dial(t, addr)
	<-entered
	if n := r.Reset(); n != 1 {
		t.Fatalf("Reset closed %d, want 1", n)
	}
	select {
	case <-canceled:
	case <-time.After(5 * time.Second):
		t.Fatal("pending dial not canceled")
	}
	_ = c.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := c.Read(make([]byte, 1)); !errors.Is(err, syscall.ECONNRESET) {
		t.Fatalf("client after reset: %v, want ECONNRESET", err)
	}
}

// A dial that started before Reset and ends after it is not spliced.
func TestDialAfterResetIsNotSpliced(t *testing.T) {
	u := newUpstream(t)
	entered, release := make(chan struct{}, 1), make(chan struct{})
	r := &Relay{Dial: func(context.Context) (net.Conn, error) {
		entered <- struct{}{}
		<-release
		return u.dial(context.Background())
	}}
	addr := startRelay(t, r)
	c := dial(t, addr)
	<-entered
	r.Reset()
	close(release)
	u.waitEnded(t, 1)
	waitLive(t, r, 0)
	_ = c.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := c.Read(make([]byte, 1)); err == nil {
		t.Fatal("client was spliced after Reset")
	}
}
