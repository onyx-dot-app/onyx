package guestd

import (
	"context"
	"log/slog"
	"sync"
	"time"
)

// Reclaimer frees the guest page cache when the VM is idle. The
// balloon's free page reporting returns free guest pages to the node, but
// the page cache is not free: only a drop gives it back. Idle means no
// daemon call (other than Health) is open and none ended for Idle. One
// reclaim runs per idle period; the next call starts a new period.
// Programs that run without a daemon call (a dev server) do not count as
// activity: a reclaim only costs them page cache misses.
type Reclaimer struct {
	// Idle is the time without daemon calls before a reclaim. 0 turns the
	// Reclaimer off.
	Idle time.Duration
	// Reclaim drops caches and compacts memory (sysops.ReclaimMemory).
	Reclaim func() error
	Log     *slog.Logger
	// Now is the clock; nil means time.Now (monotonic).
	Now func() time.Time

	mu        sync.Mutex
	open      int
	last      time.Time
	reclaimed bool
	count     int
}

func (r *Reclaimer) now() time.Time {
	if r.Now != nil {
		return r.Now()
	}
	return time.Now()
}

// Begin marks the start of a daemon call.
func (r *Reclaimer) Begin() {
	if r == nil {
		return
	}
	r.mu.Lock()
	r.open++
	r.last, r.reclaimed = r.now(), false
	r.mu.Unlock()
}

// End marks the end of a daemon call.
func (r *Reclaimer) End() {
	if r == nil {
		return
	}
	r.mu.Lock()
	r.open--
	r.last = r.now()
	r.mu.Unlock()
}

// Check runs a reclaim if the VM has been idle for Idle and none ran in
// this idle period. It reports whether it ran one.
func (r *Reclaimer) Check() bool {
	if r == nil || r.Idle <= 0 {
		return false
	}
	r.mu.Lock()
	if r.last.IsZero() {
		r.last = r.now()
	}
	idle := r.now().Sub(r.last)
	if r.open > 0 || r.reclaimed || idle < r.Idle {
		r.mu.Unlock()
		return false
	}
	r.reclaimed = true
	r.count++
	n := r.count
	r.mu.Unlock()
	t0 := r.now()
	err := r.Reclaim()
	if r.Log != nil {
		if err != nil {
			r.Log.Warn("idle memory reclaim failed", "idle", idle.Round(time.Second), "err", err)
		} else {
			r.Log.Info("idle memory reclaim", "idle", idle.Round(time.Second), "ms", r.now().Sub(t0).Milliseconds(), "count", n)
		}
	}
	return true
}

// Run calls Check until ctx ends.
func (r *Reclaimer) Run(ctx context.Context) {
	if r == nil || r.Idle <= 0 {
		return
	}
	every := min(r.Idle/4, 30*time.Second)
	t := time.NewTicker(max(every, time.Second))
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			r.Check()
		}
	}
}
