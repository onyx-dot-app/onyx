package agent

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// The cap counts starting VMs, template build VMs and processes in doubt,
// and a repeat Create of a VM on the node is never refused.
func TestMaxVMsCountsEveryFirecrackerProcess(t *testing.T) {
	f := newFixture(t, 10)
	f.m.cfg.MaxVMs = 2
	ctx := context.Background()

	f.l.gate = make(chan struct{})
	started := make(chan error, 1)
	go func() {
		_, _, err := f.m.Create(ctx, req(sb1, 1))
		started <- err
	}()
	deadline := time.Now().Add(5 * time.Second)
	for len(f.m.List()) == 0 {
		if time.Now().After(deadline) {
			t.Fatal("sb1 never started")
		}
		time.Sleep(time.Millisecond)
	}
	_, done, err := f.m.BuildSlot("tpl-abc", 1024)
	if err != nil {
		t.Fatal(err)
	}
	_, _, err = f.m.Create(ctx, req(sb2, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	var ae *apierr.Error
	if !errors.As(err, &ae) || ae.Metadata["max_vms"] != "2" || ae.Metadata["vm_count"] != "2" {
		t.Fatalf("metadata of %v", err)
	}
	_, _, err = f.m.BuildSlot("tpl-def", 1024)
	wantReason(t, err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	if info, err := f.m.NodeInfo(); err != nil || info.VMCount != 1 || info.VMSlotsUsed != 2 {
		t.Fatalf("NodeInfo with a build %+v %v", info, err)
	}

	close(f.l.gate)
	if err := <-started; err != nil {
		t.Fatal(err)
	}
	done(false)
	vm2, _, err := f.m.Create(ctx, req(sb2, 1))
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := f.m.Create(ctx, req(sb1, 1)); err != nil {
		t.Fatalf("repeat Create at the cap: %v", err)
	}
	_, _, err = f.m.Create(ctx, req(sb3, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	if info, err := f.m.NodeInfo(); err != nil || info.MaxVMs != 2 || info.VMCount != 2 || info.VMSlotsUsed != 2 {
		t.Fatalf("NodeInfo %+v %v", info, err)
	}

	if _, err := f.m.Stop(ctx, sb2, 1, vm2.Generation); err != nil {
		t.Fatal(err)
	}
	f.m.mu.Lock()
	f.m.doubt["kept"] = &doubt{reason: "test"}
	f.m.mu.Unlock()
	_, _, err = f.m.Create(ctx, req(sb3, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	// Two processes of one sandbox in doubt take two slots.
	if _, err := f.m.Stop(ctx, sb1, 1, f.m.List()[0].Generation); err != nil {
		t.Fatal(err)
	}
	f.m.mu.Lock()
	f.m.doubt["kept"].uids = []uint32{7, 8}
	f.m.mu.Unlock()
	_, _, err = f.m.Create(ctx, req(sb3, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	f.m.mu.Lock()
	delete(f.m.doubt, "kept")
	f.m.mu.Unlock()
	if _, _, err := f.m.Create(ctx, req(sb3, 1)); err != nil {
		t.Fatal(err)
	}
	if f.l.count() != 3 {
		t.Fatalf("launches %d, want 3", f.l.count())
	}
}

func TestNoCapByDefault(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	for _, id := range []string{sb1, sb2, sb3} {
		if _, _, err := f.m.Create(ctx, req(id, 1)); err != nil {
			t.Fatal(err)
		}
	}
}
