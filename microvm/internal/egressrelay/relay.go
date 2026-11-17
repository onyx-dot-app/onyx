// Package egressrelay is the in-guest egress relay. The VM has no network
// card: programs use HTTP(S)_PROXY=http://127.0.0.1:3128, and the relay
// splices each TCP connection to a vsock connection to the host (CID 2, port
// 3128), where the node agent relays it to the egress proxy.
package egressrelay

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"sync"
	"sync/atomic"
	"time"
)

// MinIdleTimeout is the shortest allowed idle timeout. LLM streams can be
// quiet for minutes.
const MinIdleTimeout = 180 * time.Second

// Relay splices client connections to upstream connections.
type Relay struct {
	// Dial opens one upstream connection.
	Dial func(ctx context.Context) (net.Conn, error)
	// MaxConns caps live client connections. Above it a new client is
	// reset at once. Default 256.
	MaxConns int
	// IdleTimeout closes a pair after no bytes in either direction for this
	// long. Zero means no timeout; otherwise at least MinIdleTimeout.
	IdleTimeout time.Duration
	// DialTimeout bounds the upstream connect. Default 10 s.
	DialTimeout time.Duration
	Log         *slog.Logger

	mu      sync.Mutex
	slots   int // clients being served, including ones still dialing
	live    map[*pair]struct{}
	dialing map[*pendingDial]struct{}
	resets  uint64 // number of Reset calls
}

// pendingDial is a client whose upstream connection is still opening.
type pendingDial struct {
	client net.Conn
	cancel context.CancelFunc
}

type pair struct {
	client net.Conn
	up     net.Conn
	once   sync.Once
	last   atomic.Int64 // unix nanos of the last byte
}

// close closes both sides. With rst, a TCP client gets RST, not FIN.
func (p *pair) close(rst bool) {
	p.once.Do(func() {
		if rst {
			resetConn(p.client)
		} else {
			_ = p.client.Close()
		}
		_ = p.up.Close()
	})
}

// resetConn closes c; a TCP client gets RST, not FIN.
func resetConn(c net.Conn) {
	if tc, ok := c.(*net.TCPConn); ok {
		_ = tc.SetLinger(0)
	}
	_ = c.Close()
}

func (r *Relay) log() *slog.Logger {
	if r.Log == nil {
		return slog.Default()
	}
	return r.Log
}

func (r *Relay) maxConns() int {
	if r.MaxConns <= 0 {
		return 256
	}
	return r.MaxConns
}

// Validate checks the settings.
func (r *Relay) Validate() error {
	if r.Dial == nil {
		return errors.New("egressrelay: Dial is required")
	}
	if r.IdleTimeout != 0 && r.IdleTimeout < MinIdleTimeout {
		return errors.New("egressrelay: idle timeout must be 0 or at least 180s")
	}
	if r.MaxConns < 0 || r.DialTimeout < 0 {
		return errors.New("egressrelay: MaxConns and DialTimeout must not be negative")
	}
	return nil
}

// Serve accepts clients until ln is closed. It keeps accepting after
// transient Accept errors (for example EMFILE). It returns nil after
// ln.Close.
func (r *Relay) Serve(ln net.Listener) error {
	if err := r.Validate(); err != nil {
		return err
	}
	backoff := 5 * time.Millisecond
	for {
		c, err := ln.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return nil
			}
			r.log().Warn("accept failed", "err", err, "retry_in", backoff)
			time.Sleep(backoff)
			backoff = min(backoff*2, time.Second)
			continue
		}
		backoff = 5 * time.Millisecond
		go r.handle(c)
	}
}

func (r *Relay) handle(c net.Conn) {
	r.mu.Lock()
	if r.live == nil {
		r.live = map[*pair]struct{}{}
		r.dialing = map[*pendingDial]struct{}{}
	}
	full := r.slots >= r.maxConns()
	if !full {
		r.slots++
	}
	r.mu.Unlock()
	if full {
		resetConn(c)
		r.log().Warn("connection cap reached; client reset", "max_conns", r.maxConns())
		return
	}
	timeout := r.DialTimeout
	if timeout == 0 {
		timeout = 10 * time.Second
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	// Reset also covers this client while its upstream connection opens.
	d := &pendingDial{client: c, cancel: cancel}
	r.mu.Lock()
	r.dialing[d] = struct{}{}
	epoch := r.resets
	r.mu.Unlock()
	up, err := r.Dial(ctx)
	cancel()
	p := &pair{client: c, up: up}
	r.mu.Lock()
	delete(r.dialing, d)
	stale := r.resets != epoch
	if err == nil && !stale {
		p.last.Store(time.Now().UnixNano())
		r.live[p] = struct{}{}
	} else {
		r.slots--
	}
	r.mu.Unlock()
	if err != nil || stale {
		if up != nil {
			_ = up.Close()
		}
		if stale {
			resetConn(c)
			return
		}
		_ = c.Close()
		r.log().Warn("upstream connect failed", "err", err)
		return
	}
	defer func() {
		p.close(false)
		r.mu.Lock()
		delete(r.live, p)
		r.slots--
		r.mu.Unlock()
	}()

	if r.IdleTimeout > 0 {
		var t *time.Timer
		t = time.AfterFunc(r.IdleTimeout, func() {
			idle := time.Since(time.Unix(0, p.last.Load()))
			if idle >= r.IdleTimeout {
				p.close(false)
				return
			}
			t.Reset(r.IdleTimeout - idle)
		})
		defer t.Stop()
	}

	done := make(chan struct{}, 2)
	pump := func(dst, src net.Conn) {
		_, _ = io.Copy(activity{dst, p}, src)
		// Firecracker vsock has no half-close: when one side ends, close both.
		p.close(false)
		done <- struct{}{}
	}
	go pump(up, c)
	go pump(c, up)
	<-done
	<-done
}

// activity records the time of each write.
type activity struct {
	w io.Writer
	p *pair
}

func (a activity) Write(b []byte) (int, error) {
	a.p.last.Store(time.Now().UnixNano())
	return a.w.Write(b)
}

// Reset closes every live connection and every client whose upstream
// connection is still opening (RST to TCP clients), and returns how many it
// closed. A dial that started before Reset is never spliced after it. New
// connections still work. Send SIGHUP after a snapshot restore so pooled
// clients and open streams fail at once instead of hanging.
func (r *Relay) Reset() int {
	r.mu.Lock()
	r.resets++
	pairs := make([]*pair, 0, len(r.live))
	for p := range r.live {
		pairs = append(pairs, p)
	}
	dials := make([]*pendingDial, 0, len(r.dialing))
	for d := range r.dialing {
		dials = append(dials, d)
	}
	r.mu.Unlock()
	for _, p := range pairs {
		p.close(true)
	}
	for _, d := range dials {
		d.cancel()
		resetConn(d.client)
	}
	return len(pairs) + len(dials)
}

// Live returns the number of live connections.
func (r *Relay) Live() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.live)
}
