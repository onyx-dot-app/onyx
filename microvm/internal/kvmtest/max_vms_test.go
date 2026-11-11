//go:build kvm && linux

package kvmtest

import (
	"context"
	"fmt"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// TestMaxVMsKVM checks the VM cap with real VMs: a burst of cap+1 Creates
// admits exactly cap (starting VMs count), a Create at the cap is refused
// with CAPACITY_VM_SLOTS and starts no process, and a Stop frees a slot.
// KVM_MAX_VMS sets the cap (default 4).
func TestMaxVMsKVM(t *testing.T) {
	e := loadEnv()
	limit := 4
	if v := os.Getenv("KVM_MAX_VMS"); v != "" {
		_, _ = fmt.Sscanf(v, "%d", &limit)
	}
	cmd := newCommand(t, e)
	buildTemplate(t, &e, cmd)
	c := startAgentWith(t, e, cmd, func(cfg *agent.Config) { cfg.MaxVMs = limit })
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	req := func(id string) *pb.CreateRequest {
		return &pb.CreateRequest{SandboxId: id, Attempt: 1, Template: e.Template, Vcpus: tplVCPUs, MemMib: tplMemMiB, ScratchGib: scratchGiB, TenantId: "public"}
	}
	t.Cleanup(func() {
		l, err := c.List(context.Background(), &pb.ListRequest{})
		if err != nil {
			t.Errorf("cleanup list: %v", err)
			return
		}
		for _, vm := range l.GetVms() {
			if _, err := c.Stop(context.Background(), &pb.StopRequest{SandboxId: vm.GetSandboxId(), Attempt: vm.GetAttempt(), Generation: vm.GetGeneration()}); err != nil {
				t.Errorf("cleanup stop %s: %v", vm.GetSandboxId(), err)
			}
		}
	})

	ni, err := c.NodeInfo(ctx, &pb.NodeInfoRequest{})
	if err != nil || int(ni.GetMaxVms()) != limit {
		t.Fatalf("NodeInfo max_vms: %v %v", ni, err)
	}

	// 1. cap+1 Creates at once: the starting VMs hold their slots.
	errs := make([]error, limit+1)
	var wg sync.WaitGroup
	for i := range errs {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			_, errs[i] = c.Create(ctx, req(newUUID()))
		}(i)
	}
	wg.Wait()
	admitted := 0
	for i, err := range errs {
		switch {
		case err == nil:
			admitted++
		case apierr.FromStatus(err) == pb.ErrorReason_CAPACITY_VM_SLOTS:
			t.Logf("burst create %d refused: %v (metadata %v)", i, err, reasonMetadata(err))
		default:
			t.Fatalf("burst create %d: %v", i, err)
		}
	}
	if admitted != limit {
		t.Fatalf("burst admitted %d of %d, want %d", admitted, limit+1, limit)
	}

	// 2. A Create at the cap is refused and starts nothing.
	_, err = c.Create(ctx, req(newUUID()))
	wantReason(t, "create at the cap", err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	if md := reasonMetadata(err); md["max_vms"] != fmt.Sprint(limit) || md["vm_count"] != fmt.Sprint(limit) {
		t.Errorf("refusal metadata %v", md)
	}
	l, err := c.List(ctx, &pb.ListRequest{})
	if err != nil {
		t.Fatal(err)
	}
	running := 0
	for _, vm := range l.GetVms() {
		if vm.GetState() == pb.VMState_VM_STATE_RUNNING {
			running++
		}
	}
	if len(l.GetVms()) != limit || running != limit {
		t.Fatalf("list: %d VMs (%d running), want %d running", len(l.GetVms()), running, limit)
	}
	if ni, err := c.NodeInfo(ctx, &pb.NodeInfoRequest{}); err != nil || int(ni.GetVmCount()) != limit {
		t.Fatalf("NodeInfo vm_count: %v %v", ni, err)
	}

	// 3. A Stop frees one slot.
	first := l.GetVms()[0]
	if _, err := c.Stop(ctx, &pb.StopRequest{SandboxId: first.GetSandboxId(), Attempt: first.GetAttempt(), Generation: first.GetGeneration()}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Create(ctx, req(newUUID())); err != nil {
		t.Fatalf("create after a stop: %v", err)
	}
	_, err = c.Create(ctx, req(newUUID()))
	wantReason(t, "create at the cap again", err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	t.Logf("cap %d: burst admitted %d of %d, refusal at the cap, stop frees a slot", limit, admitted, limit+1)
}
