package browser

import (
	"errors"
	"io"
	"log/slog"
	"net"
	"sync"
	"time"
)

// maxForwards caps the open CDP forwards. Each forward is one vsock and one
// TCP connection. The node agent caps Dial streams per VM at 64 by default.
const maxForwards = 128

// forwarder copies each connection on ln (vsock) to target, Chromium's
// DevTools port on 127.0.0.1.
type forwarder struct {
	ln     net.Listener
	target string
	log    *slog.Logger

	mu       sync.Mutex
	conns    map[net.Conn]struct{} // both ends of every forward, for close
	forwards int
	closed   bool
	wg       sync.WaitGroup
}

func newForwarder(ln net.Listener, target string, log *slog.Logger) *forwarder {
	f := &forwarder{ln: ln, target: target, log: log, conns: map[net.Conn]struct{}{}}
	f.wg.Go(f.serve)
	return f
}

func (f *forwarder) serve() {
	for {
		c, err := f.ln.Accept()
		if err != nil {
			f.mu.Lock()
			closed := f.closed
			f.mu.Unlock()
			if closed || errors.Is(err, net.ErrClosed) {
				return
			}
			f.log.Warn("cdp accept", "err", err)
			// A transient error (for example EMFILE): do not spin.
			time.Sleep(50 * time.Millisecond)
			continue
		}
		if !f.accept(c) {
			f.log.Warn("cdp connection refused: too many forwards", "max", maxForwards)
			_ = c.Close()
			continue
		}
		f.wg.Go(func() { f.handle(c) })
	}
}

// accept tracks a new vsock connection as one forward. It refuses it after
// close or over maxForwards.
func (f *forwarder) accept(c net.Conn) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.closed || f.forwards >= maxForwards {
		return false
	}
	f.forwards++
	f.conns[c] = struct{}{}
	return true
}

// release untracks the vsock connection of a forward.
func (f *forwarder) release(c net.Conn) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.forwards--
	delete(f.conns, c)
}

// track adds or removes the TCP end of a forward. It does not count against
// maxForwards; it refuses an addition after close.
func (f *forwarder) track(c net.Conn, add bool) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	if !add {
		delete(f.conns, c)
		return true
	}
	if f.closed {
		return false
	}
	f.conns[c] = struct{}{}
	return true
}

func (f *forwarder) handle(c net.Conn) {
	defer f.release(c)
	defer func() { _ = c.Close() }()
	t, err := net.DialTimeout("tcp", f.target, 5*time.Second)
	if err != nil {
		f.log.Debug("cdp dial", "err", err)
		return
	}
	if !f.track(t, true) {
		_ = t.Close()
		return
	}
	defer f.track(t, false)
	defer func() { _ = t.Close() }()
	// vsock has no half-close: when one side ends, close both.
	done := make(chan struct{}, 2)
	go func() { _, _ = io.Copy(t, c); done <- struct{}{} }()
	go func() { _, _ = io.Copy(c, t); done <- struct{}{} }()
	<-done
	_ = c.Close()
	_ = t.Close()
	<-done
}

// close stops the listener and every forwarded connection, and waits.
func (f *forwarder) close() {
	f.mu.Lock()
	f.closed = true
	f.mu.Unlock()
	_ = f.ln.Close()
	f.mu.Lock()
	for c := range f.conns {
		_ = c.Close()
	}
	f.mu.Unlock()
	f.wg.Wait()
}
