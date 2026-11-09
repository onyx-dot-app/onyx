package guestd

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

type fakeClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *fakeClock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *fakeClock) add(d time.Duration) {
	c.mu.Lock()
	c.t = c.t.Add(d)
	c.mu.Unlock()
}

func newReclaimer(clock *fakeClock, runs *int, err error) *Reclaimer {
	return &Reclaimer{Idle: 5 * time.Minute, Now: clock.now, Reclaim: func() error { *runs++; return err }}
}

func TestReclaimOncePerIdlePeriod(t *testing.T) {
	clock := &fakeClock{t: time.Unix(1000, 0)}
	runs := 0
	r := newReclaimer(clock, &runs, nil)
	if r.Check() {
		t.Fatal("reclaim at start")
	}
	clock.add(5*time.Minute - time.Second)
	if r.Check() {
		t.Fatal("reclaim before Idle")
	}
	clock.add(time.Second)
	if !r.Check() || runs != 1 {
		t.Fatalf("no reclaim after Idle (runs %d)", runs)
	}
	clock.add(time.Hour)
	if r.Check() || runs != 1 {
		t.Fatal("second reclaim in the same idle period")
	}

	// A call that stays open (a Stream that follows a command) is activity.
	r.Begin()
	clock.add(time.Hour)
	if r.Check() {
		t.Fatal("reclaim during an open call")
	}
	r.End()
	clock.add(5*time.Minute - time.Second)
	if r.Check() {
		t.Fatal("reclaim before Idle after the call ended")
	}
	clock.add(time.Second)
	if !r.Check() || runs != 2 {
		t.Fatalf("no reclaim in the new idle period (runs %d)", runs)
	}

	// A failed reclaim does not repeat in the same period.
	failing := newReclaimer(clock, &runs, errors.New("EACCES"))
	failing.Check()
	clock.add(5 * time.Minute)
	if !failing.Check() || failing.Check() {
		t.Fatal("failed reclaim: want one try per period")
	}
}

func TestReclaimOff(t *testing.T) {
	var r *Reclaimer
	r.Begin()
	r.End()
	if r.Check() {
		t.Fatal("nil Reclaimer reclaimed")
	}
	r = &Reclaimer{Reclaim: func() error { t.Fatal("reclaim with Idle 0"); return nil }}
	r.Check()
	r.Run(context.Background()) // returns at once
}

// Daemon calls are activity; Health is not (the agent and api_server poll it).
func TestDaemonCallsAreActivity(t *testing.T) {
	clock := &fakeClock{t: time.Unix(1000, 0)}
	runs := 0
	r := newReclaimer(clock, &runs, nil)
	h := newHarness(t, execs.Config{}, Config{Reclaimer: r})
	c := h.initialized()
	ctx := context.Background()
	clock.add(5 * time.Minute)
	if _, err := c.Health(ctx, &pb.HealthRequest{}); err != nil {
		t.Fatal(err)
	}
	if !r.Check() || runs != 1 {
		t.Fatalf("Health counted as activity (runs %d)", runs)
	}
	if _, err := c.List(keyed(ctx), &pb.ListRequest{}); err != nil {
		t.Fatal(err)
	}
	clock.add(5*time.Minute - time.Second)
	if r.Check() {
		t.Fatal("List did not count as activity")
	}
	// A refused call (no key) is not activity.
	clock.add(time.Second)
	if _, err := c.List(ctx, &pb.ListRequest{}); err == nil {
		t.Fatal("call without key accepted")
	}
	if !r.Check() || runs != 2 {
		t.Fatalf("refused call counted as activity (runs %d)", runs)
	}
	// A stream call is open until it ends.
	s, err := c.Run(keyed(ctx), &pb.RunRequest{Command: sh("echo hi")})
	if err != nil {
		t.Fatal(err)
	}
	collect(t, s)
	clock.add(5*time.Minute - time.Second)
	if r.Check() {
		t.Fatal("Run did not count as activity")
	}
}
