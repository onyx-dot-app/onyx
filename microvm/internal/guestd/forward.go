package guestd

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"slices"
	"strconv"
	"sync"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/egressrelay"
)

// DefaultDialPorts are the forwarded ports when SetKey names none. They
// match the node agent's default --dial-ports.
var DefaultDialPorts = []uint32{3010}

const (
	// MaxDialPorts is the largest SetKey port list.
	MaxDialPorts = 64
	// DefaultForwardConns caps the live connections of one forwarded port.
	// It matches the node agent's default Dial streams per VM.
	DefaultForwardConns = 64
)

// Forwards serves the node agent's Dial ports: each accepted vsock
// connection on a port is spliced to TCP 127.0.0.1:<port> in the guest,
// where the sandbox user's services listen.
type Forwards struct {
	// Listen opens the vsock listener of a port.
	Listen func(port uint32) (net.Listener, error)
	// Dial connects to a guest port. Nil dials TCP 127.0.0.1:<port>.
	Dial func(ctx context.Context, port uint32) (net.Conn, error)
	// Reserved is the daemon's own vsock port. It is never forwarded.
	Reserved uint32
	// MaxConns caps the live connections per port. 0 means DefaultForwardConns.
	MaxConns int
	Log      *slog.Logger

	mu   sync.Mutex
	open map[uint32]net.Listener
}

// validateDialPorts checks a SetKey port list and returns it sorted with no
// duplicates.
func validateDialPorts(ports []uint32, reserved uint32) ([]uint32, error) {
	if len(ports) > MaxDialPorts {
		return nil, fmt.Errorf("at most %d dial_ports, got %d", MaxDialPorts, len(ports))
	}
	out := slices.Clone(ports)
	slices.Sort(out)
	out = slices.Compact(out)
	for _, p := range out {
		if p == 0 || p > 65535 {
			return nil, fmt.Errorf("dial port %d is not a TCP port", p)
		}
		if reserved != 0 && p == reserved {
			return nil, fmt.Errorf("dial port %d is the guest daemon port", p)
		}
	}
	return out, nil
}

func (f *Forwards) log() *slog.Logger {
	if f.Log == nil {
		return slog.Default()
	}
	return f.Log
}

func (f *Forwards) dial(ctx context.Context, port uint32) (net.Conn, error) {
	if f.Dial != nil {
		return f.Dial(ctx, port)
	}
	var d net.Dialer
	return d.DialContext(ctx, "tcp", net.JoinHostPort("127.0.0.1", strconv.FormatUint(uint64(port), 10)))
}

// Set makes the forwarded ports equal to ports: it closes the listeners of
// other ports and opens the missing ones. A port that fails to listen is
// left out, and Set returns the error; a later Set tries it again. Live
// connections of a removed port run until they end. Set returns the
// forwarded ports.
func (f *Forwards) Set(ports []uint32) ([]uint32, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.open == nil {
		f.open = map[uint32]net.Listener{}
	}
	for p, ln := range f.open {
		if !slices.Contains(ports, p) {
			_ = ln.Close()
			delete(f.open, p)
			f.log().Info("dial port closed", "port", p)
		}
	}
	var errs []error
	for _, p := range ports {
		if _, ok := f.open[p]; ok || p == f.Reserved {
			continue
		}
		ln, err := f.Listen(p)
		if err != nil {
			f.log().Warn("dial port not forwarded", "port", p, "err", err)
			errs = append(errs, fmt.Errorf("listen on dial port %d: %w", p, err))
			continue
		}
		maxConns := f.MaxConns
		if maxConns <= 0 {
			maxConns = DefaultForwardConns
		}
		r := &egressrelay.Relay{
			Dial:     func(ctx context.Context) (net.Conn, error) { return f.dial(ctx, p) },
			MaxConns: maxConns, DialTimeout: 5 * time.Second, Log: f.log().With("dial_port", p),
		}
		go func() {
			if err := r.Serve(ln); err != nil {
				f.log().Error("dial port forward stopped", "port", p, "err", err)
			}
		}()
		f.open[p] = ln
		f.log().Info("dial port forwarded", "port", p)
	}
	return f.ports(), errors.Join(errs...)
}

// Ports returns the forwarded ports, sorted.
func (f *Forwards) Ports() []uint32 {
	if f == nil {
		return nil
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.ports()
}

func (f *Forwards) ports() []uint32 {
	out := make([]uint32, 0, len(f.open))
	for p := range f.open {
		out = append(out, p)
	}
	slices.Sort(out)
	return out
}

// Close closes every listener.
func (f *Forwards) Close() {
	_, _ = f.Set(nil)
}
