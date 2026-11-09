package relay

import (
	"bufio"
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"sync"
	"sync/atomic"
	"time"
)

// Defaults of a Relay.
const (
	DefaultIdleTimeout = 15 * time.Minute
	DefaultHeadTimeout = 30 * time.Second
	DefaultDialTimeout = 10 * time.Second
	// DefaultMaxConns is the default per-VM connection cap.
	DefaultMaxConns = 256
	bufSize         = 64 << 10
	// Accept errors back off from minBackoff, doubling up to maxBackoff.
	minBackoff = 5 * time.Millisecond
	maxBackoff = time.Second
)

// Connection events for Relay.Events.
const (
	EventAccepted       = "accepted"
	EventOverCap        = "over_cap"
	EventUpstreamFailed = "upstream_failed"
)

// MinIdleTimeout is the shortest idle timeout the relay allows. LLM streams
// can be quiet for minutes.
const MinIdleTimeout = 180 * time.Second

// VM is the identity that the relay stamps for one VM.
type VM struct {
	SandboxID  string
	Subject    string
	Generation uint64
}

// Relay forwards VM egress to the proxy.
type Relay struct {
	Signer *Signer
	// Upstream is the proxy address (host:port).
	Upstream    string
	IdleTimeout time.Duration
	HeadTimeout time.Duration
	DialTimeout time.Duration
	// MaxConns caps the open connections of one VM. A connection over the
	// cap is closed at once. 0 means DefaultMaxConns.
	MaxConns int
	Log      *slog.Logger
	// Events, if set, gets one Event* value per VM connection.
	Events func(event string)
	// dial replaces the upstream dial in tests.
	dial func(ctx context.Context, network, addr string) (net.Conn, error)

	mu    sync.Mutex
	conns map[string]map[*pair]struct{}
	lns   map[string]net.Listener
}

type pair struct {
	mu     sync.Mutex
	vm, up net.Conn
	closed bool
}

func (p *pair) close() {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.closed {
		return
	}
	p.closed = true
	_ = p.vm.Close()
	if p.up != nil {
		_ = p.up.Close()
	}
}

// setUp stores the upstream connection. It returns false if the pair is
// already closed; the caller then closes up.
func (p *pair) setUp(up net.Conn) bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.closed {
		return false
	}
	p.up = up
	return true
}

func (r *Relay) idle() time.Duration {
	if r.IdleTimeout <= 0 {
		return DefaultIdleTimeout
	}
	return max(r.IdleTimeout, MinIdleTimeout)
}

func (r *Relay) maxConns() int {
	if r.MaxConns <= 0 {
		return DefaultMaxConns
	}
	return r.MaxConns
}

// Serve accepts the connections of one VM on ln until ln is closed or Detach
// is called. It does not return before all accepts stop.
func (r *Relay) Serve(ln net.Listener, vm VM) {
	r.register(ln, vm.SandboxID)
	r.accept(ln, vm)
}

// Start is Serve in a new goroutine. ln is registered before Start returns,
// so a Detach after Start always closes it.
func (r *Relay) Start(ln net.Listener, vm VM) {
	r.register(ln, vm.SandboxID)
	go r.accept(ln, vm)
}

func (r *Relay) register(ln net.Listener, id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.lns == nil {
		r.lns = map[string]net.Listener{}
		r.conns = map[string]map[*pair]struct{}{}
	}
	if old := r.lns[id]; old != nil && old != ln {
		// The old listener may have the same path: do not remove it.
		if ul, ok := old.(*net.UnixListener); ok {
			ul.SetUnlinkOnClose(false)
		}
		_ = old.Close()
	}
	r.lns[id] = ln
}

func (r *Relay) accept(ln net.Listener, vm VM) {
	sem := make(chan struct{}, r.maxConns())
	var backoff time.Duration
	full := false
	for {
		c, err := ln.Accept()
		if errors.Is(err, net.ErrClosed) {
			return
		}
		if err != nil {
			// EMFILE, ECONNABORTED and the like pass: keep serving.
			backoff = min(max(2*backoff, minBackoff), maxBackoff)
			r.Log.Warn("relay accept", "sandbox_id", vm.SandboxID, "err", err, "retry_in", backoff)
			time.Sleep(backoff)
			continue
		}
		backoff = 0
		select {
		case sem <- struct{}{}:
			full = false
			r.event(EventAccepted)
			go func() {
				defer func() { <-sem }()
				r.handle(c, vm)
			}()
		default:
			_ = c.Close()
			r.event(EventOverCap)
			if !full {
				full = true
				r.Log.Warn("relay connection cap reached; closing new connections", "sandbox_id", vm.SandboxID, "max", cap(sem))
			}
		}
	}
}

// CloseAll closes every relay connection of a sandbox and returns the count.
// The listener stays open, so new connections still work.
func (r *Relay) CloseAll(sandboxID string) int {
	r.mu.Lock()
	set := r.conns[sandboxID]
	delete(r.conns, sandboxID)
	r.mu.Unlock()
	for p := range set {
		p.close()
	}
	return len(set)
}

// Detach stops the listener of a sandbox and closes its connections.
func (r *Relay) Detach(sandboxID string) {
	r.mu.Lock()
	ln := r.lns[sandboxID]
	delete(r.lns, sandboxID)
	r.mu.Unlock()
	if ln != nil {
		_ = ln.Close()
	}
	r.CloseAll(sandboxID)
}

// Live returns the number of open connections of a sandbox.
func (r *Relay) Live(sandboxID string) int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.conns[sandboxID])
}

// Open returns the number of open connections of all sandboxes.
func (r *Relay) Open() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	n := 0
	for _, set := range r.conns {
		n += len(set)
	}
	return n
}

func (r *Relay) event(e string) {
	if r.Events != nil {
		r.Events(e)
	}
}

func (r *Relay) track(id string, p *pair) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.conns[id] == nil {
		r.conns[id] = map[*pair]struct{}{}
	}
	r.conns[id][p] = struct{}{}
}

func (r *Relay) untrack(id string, p *pair) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.conns[id], p)
	if len(r.conns[id]) == 0 {
		delete(r.conns, id)
	}
}

func (r *Relay) handle(vmConn net.Conn, vm VM) {
	p := &pair{vm: vmConn}
	r.track(vm.SandboxID, p)
	defer r.untrack(vm.SandboxID, p)
	defer p.close()

	headTimeout := r.HeadTimeout
	if headTimeout == 0 {
		headTimeout = DefaultHeadTimeout
	}
	_ = vmConn.SetReadDeadline(time.Now().Add(headTimeout))
	br := bufio.NewReaderSize(vmConn, bufSize)
	head, err := ReadHead(br)
	if err != nil {
		if errors.Is(err, ErrBadHead) {
			_, _ = io.WriteString(vmConn, "HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
		}
		r.Log.Debug("relay head", "sandbox_id", vm.SandboxID, "err", err)
		return
	}
	_ = vmConn.SetReadDeadline(time.Time{})
	token, err := r.Signer.Token(vm.Subject, vm.Generation)
	if err != nil {
		r.Log.Error("sign token", "sandbox_id", vm.SandboxID, "err", err)
		return
	}
	head.Stamp(token)

	dialTimeout := r.DialTimeout
	if dialTimeout == 0 {
		dialTimeout = DefaultDialTimeout
	}
	ctx, cancel := context.WithTimeout(context.Background(), dialTimeout)
	dial := r.dial
	if dial == nil {
		dial = (&net.Dialer{KeepAlive: 30 * time.Second}).DialContext
	}
	up, err := dial(ctx, "tcp", r.Upstream)
	cancel()
	if err != nil {
		_, _ = io.WriteString(vmConn, "HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
		r.event(EventUpstreamFailed)
		r.Log.Warn("relay dial", "sandbox_id", vm.SandboxID, "err", err)
		return
	}
	if !p.setUp(up) {
		// CloseAll ran during the head read or the dial.
		_ = up.Close()
		return
	}
	if _, err := up.Write(head.Bytes()); err != nil {
		return
	}
	// The VM may have sent body bytes after the head.
	if n := br.Buffered(); n > 0 {
		buf, _ := br.Peek(n)
		if _, err := up.Write(buf); err != nil {
			return
		}
	}
	r.splice(p, up)
}

// splice copies both ways. When either side ends or fails, both sides close:
// Firecracker vsock does not carry a half-close.
func (r *Relay) splice(p *pair, up net.Conn) {
	var last atomic.Int64
	last.Store(time.Now().UnixNano())
	idle := r.idle()
	done := make(chan struct{}, 2)
	cp := func(dst, src net.Conn) {
		defer func() { done <- struct{}{} }()
		buf := make([]byte, bufSize)
		for {
			_ = src.SetReadDeadline(time.Now().Add(idle))
			n, err := src.Read(buf)
			if n > 0 {
				last.Store(time.Now().UnixNano())
				if _, werr := dst.Write(buf[:n]); werr != nil {
					return
				}
			}
			if err != nil {
				var ne net.Error
				if errors.As(err, &ne) && ne.Timeout() && time.Since(time.Unix(0, last.Load())) < idle {
					continue
				}
				return
			}
		}
	}
	go cp(up, p.vm)
	go cp(p.vm, up)
	<-done
	p.close()
	<-done
}
