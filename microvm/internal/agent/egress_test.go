package agent

import (
	"context"
	"errors"
	"sync"
	"testing"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

type fakeEgress struct {
	mu       sync.Mutex
	attached map[string]VM
	detached []string
	closeAll map[string]int
	fail     error
}

func (f *fakeEgress) Attach(vm VM, _ ProcInfo) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.fail != nil {
		return f.fail
	}
	if f.attached == nil {
		f.attached = map[string]VM{}
	}
	f.attached[vm.SandboxID] = vm
	return nil
}

func (f *fakeEgress) Detach(id string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.attached, id)
	f.detached = append(f.detached, id)
}

func (f *fakeEgress) CloseAll(id string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.closeAll == nil {
		f.closeAll = map[string]int{}
	}
	f.closeAll[id]++
	return 3
}

func TestEgressFollowsVM(t *testing.T) {
	f := newFixture(t, 10)
	eg := &fakeEgress{}
	f.m.UseEgress(eg)
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	if a, ok := eg.attached[sb1]; !ok || a.TenantID != "public" || a.Generation != vm.Generation {
		t.Fatalf("attached %+v", eg.attached)
	}

	_, err = f.m.CloseConnections(sb1, 1, vm.Generation+1)
	wantReason(t, err, pb.ErrorReason_INSTANCE_MISMATCH)
	_, err = f.m.CloseConnections(sb2, 1, 1)
	wantReason(t, err, pb.ErrorReason_SANDBOX_NOT_FOUND)
	n, err := f.m.CloseConnections(sb1, 1, vm.Generation)
	if err != nil || n != 3 || eg.closeAll[sb1] != 1 {
		t.Fatalf("close connections: %d %v", n, err)
	}

	if _, err := f.m.Stop(ctx, sb1, 1, vm.Generation); err != nil {
		t.Fatal(err)
	}
	if _, ok := eg.attached[sb1]; ok || len(eg.detached) != 1 {
		t.Fatalf("after stop: attached %v detached %v", eg.attached, eg.detached)
	}

	// A VM that exits on its own is detached too.
	vm2, _, err := f.m.Create(ctx, req(sb2, 1))
	if err != nil {
		t.Fatal(err)
	}
	f.l.procs[sb2].exit()
	waitState(t, f.m, sb2, pb.VMState_VM_STATE_EXITED)
	if _, ok := eg.attached[sb2]; ok {
		t.Fatal("exited VM still attached")
	}
	if n, err := f.m.CloseConnections(sb2, 1, vm2.Generation); err != nil || n != 0 {
		t.Fatalf("close connections of an exited VM: %d %v", n, err)
	}
}

func TestEgressAttachFailureFailsCreate(t *testing.T) {
	f := newFixture(t, 10)
	f.m.UseEgress(&fakeEgress{fail: errors.New("no socket")})
	_, _, err := f.m.Create(context.Background(), req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_VMM_FAILED)
	if f.l.procs[sb1].killed.Load() != 1 || f.uids.InUse() != 0 || len(f.m.List()) != 0 {
		t.Fatalf("failed attach left a VM: killed=%d uids=%d vms=%d", f.l.procs[sb1].killed.Load(), f.uids.InUse(), len(f.m.List()))
	}
}

func TestTenantIDValidation(t *testing.T) {
	f := newFixture(t, 10)
	for _, bad := range []string{"", "a/b", "a b", "tenant.x"} {
		r := req(sb1, 1)
		r.TenantID = bad
		_, _, err := f.m.Create(context.Background(), r)
		wantReason(t, err, pb.ErrorReason_INVALID_ARGUMENT)
	}
}
