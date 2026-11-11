package agent

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// steps records the release order of one VM.
type steps struct {
	mu  sync.Mutex
	log []string
}

func (s *steps) add(step string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.log = append(s.log, step)
}

func (s *steps) String() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return strings.Join(s.log, ",")
}

type orderEgress struct {
	fakeEgress
	s *steps
}

func (o *orderEgress) Detach(id string) {
	o.s.add("relay-identity-removed")
	o.fakeEgress.Detach(id)
}

// orderProc records Kill (which frees the vsock socket with the chroot) and
// whether the jailer UID was still held at that moment.
type orderProc struct {
	fakeProc
	s    *steps
	f    *fixture
	held bool
}

func (p *orderProc) Kill(ctx context.Context) error {
	p.held = p.f.uids.InUse() == 1
	p.s.add("vm-killed")
	return p.fakeProc.Kill(ctx)
}

type orderLauncher struct {
	s    *steps
	f    *fixture
	proc *orderProc
}

func (l *orderLauncher) Launch(context.Context, LaunchSpec) (Process, error) {
	l.proc = &orderProc{fakeProc: fakeProc{pid: 4242, done: make(chan struct{})}, s: l.s, f: l.f}
	return l.proc, nil
}

func newOrderFixture(t *testing.T) (*fixture, *steps, *orderLauncher, *orderEgress) {
	t.Helper()
	f := newFixture(t, 10)
	s := &steps{}
	l := &orderLauncher{s: s, f: f}
	f.m.launcher = l
	eg := &orderEgress{s: s}
	f.m.UseEgress(eg)
	f.m.OnRelease(func(vm VM) { s.add("passthrough-dropped") })
	return f, s, l, eg
}

// TestStopReleasesIdentityBeforeCIDAndUID: Stop removes the relay identity
// and the daemon connection before it kills the VM (freeing its vsock
// socket) and frees the jailer UID (ENG-4606).
func TestStopReleasesIdentityBeforeCIDAndUID(t *testing.T) {
	f, s, l, _ := newOrderFixture(t)
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.m.Stop(ctx, sb1, vm.Attempt, vm.Generation); err != nil {
		t.Fatal(err)
	}
	if got, want := s.String(), "relay-identity-removed,passthrough-dropped,vm-killed"; got != want {
		t.Fatalf("order %s, want %s", got, want)
	}
	if !l.proc.held {
		t.Fatal("jailer UID was freed before the VM was killed")
	}
	if n := f.uids.InUse(); n != 0 {
		t.Fatalf("%d UIDs in use after Stop", n)
	}
}

// TestExitReleasesIdentityBeforeCleanup: a VM that exits without Stop also
// loses its identity before the cleanup, and keeps its UID until Stop.
func TestExitReleasesIdentityBeforeCleanup(t *testing.T) {
	f, s, l, _ := newOrderFixture(t)
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	l.proc.exit()
	deadline := time.Now().Add(5 * time.Second)
	for s.String() != "relay-identity-removed,passthrough-dropped,vm-killed" {
		if time.Now().After(deadline) {
			t.Fatalf("order %s", s)
		}
		time.Sleep(time.Millisecond)
	}
	if _, err := f.m.GuestTarget(sb1); apierr.ReasonOf(err) != pb.ErrorReason_VM_NOT_RUNNING {
		t.Fatalf("guest target of an exited VM: %v", err)
	}
	if n := f.uids.InUse(); n != 1 {
		t.Fatalf("%d UIDs in use after exit, want 1 until Stop", n)
	}
	if _, err := f.m.Stop(ctx, sb1, vm.Attempt, vm.Generation); err != nil {
		t.Fatal(err)
	}
	if n := f.uids.InUse(); n != 0 {
		t.Fatalf("%d UIDs in use after Stop", n)
	}
}

// TestFailedStartReleasesIdentityBeforeUID: a start that fails after the
// launch releases the VM in the same order.
func TestFailedStartReleasesIdentityBeforeUID(t *testing.T) {
	f, s, l, eg := newOrderFixture(t)
	eg.fail = errors.New("listen: address in use")
	if _, _, err := f.m.Create(context.Background(), req(sb1, 1)); err == nil {
		t.Fatal("create worked")
	}
	if got, want := s.String(), "relay-identity-removed,passthrough-dropped,vm-killed"; got != want {
		t.Fatalf("order %s, want %s", got, want)
	}
	if !l.proc.held {
		t.Fatal("jailer UID was freed before the VM was killed")
	}
	if n := f.uids.InUse(); n != 0 {
		t.Fatalf("%d UIDs in use", n)
	}
}

// TestGenerationIsPerInstance: every Create gets a new, larger generation,
// also for a new attempt of the same sandbox (the host-side boot_id).
func TestGenerationIsPerInstance(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	seen := map[uint64]bool{}
	var last uint64
	for attempt := uint64(1); attempt <= 3; attempt++ {
		vm, _, err := f.m.Create(ctx, req(sb1, attempt))
		if err != nil {
			t.Fatal(err)
		}
		if seen[vm.Generation] || vm.Generation <= last {
			t.Fatalf("attempt %d generation %d after %d", attempt, vm.Generation, last)
		}
		seen[vm.Generation], last = true, vm.Generation
		if _, err := f.m.Stop(ctx, sb1, vm.Attempt, vm.Generation); err != nil {
			t.Fatal(err)
		}
	}
}
