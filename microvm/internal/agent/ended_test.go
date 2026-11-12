package agent

import (
	"context"
	"sync"
	"testing"
	"time"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// clock is a test clock that Manager goroutines can read.
type clock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *clock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *clock) add(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.t = c.t.Add(d)
}

func TestEndedListsExitAndStopForTheRetention(t *testing.T) {
	f := newFixture(t, 10)
	c := &clock{t: time.Unix(1_800_000_000, 0)}
	f.m.now = c.now
	ctx := context.Background()

	exited, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	stopped, _, err := f.m.Create(ctx, req(sb2, 3))
	if err != nil {
		t.Fatal(err)
	}
	if got := f.m.Ended(); len(got) != 0 {
		t.Fatalf("ended before any end: %+v", got)
	}

	f.l.procs[sb1].exit()
	waitState(t, f.m, sb1, pb.VMState_VM_STATE_EXITED)
	c.add(time.Minute)
	if _, err := f.m.Stop(ctx, sb2, 3, stopped.Generation); err != nil {
		t.Fatal(err)
	}
	// A Stop of the exited VM keeps its first reason.
	if _, err := f.m.Stop(ctx, sb1, 1, exited.Generation); err != nil {
		t.Fatal(err)
	}

	got := f.m.Ended()
	if len(got) != 2 {
		t.Fatalf("ended %+v", got)
	}
	if got[0].SandboxID != sb1 || got[0].Reason != EndedExited || got[0].Attempt != 1 ||
		got[0].Generation != exited.Generation || got[0].TenantID != "public" {
		t.Fatalf("exited entry %+v", got[0])
	}
	if got[1].SandboxID != sb2 || got[1].Reason != EndedStopped || got[1].Attempt != 3 ||
		got[1].Generation != stopped.Generation || !got[1].EndedAt.Equal(c.now()) {
		t.Fatalf("stopped entry %+v", got[1])
	}
	// Every read lists them again until the retention ends.
	if again := f.m.Ended(); len(again) != 2 {
		t.Fatalf("second read %+v", again)
	}

	c.add(DefaultEndedRetention - time.Minute + time.Second)
	if got := f.m.Ended(); len(got) != 1 || got[0].SandboxID != sb2 {
		t.Fatalf("after the first retention ended: %+v", got)
	}
	c.add(time.Minute)
	if got := f.m.Ended(); len(got) != 0 {
		t.Fatalf("after the retention: %+v", got)
	}
}

func TestEndedOffWithZeroRetention(t *testing.T) {
	f := newFixture(t, 10)
	f.m.cfg.EndedRetention = 0
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.m.Stop(ctx, sb1, 1, vm.Generation); err != nil {
		t.Fatal(err)
	}
	if got := f.m.Ended(); len(got) != 0 {
		t.Fatalf("ended with retention 0: %+v", got)
	}
}
