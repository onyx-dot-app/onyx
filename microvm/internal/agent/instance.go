package agent

import (
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// Instance returns the guest target of a running VM if sandbox_id, attempt
// and generation all match it (the preconditions of Stop).
func (m *Manager) Instance(sandboxID string, attempt, generation uint64) (GuestTarget, error) {
	t, err := m.GuestTarget(sandboxID)
	if err != nil {
		return t, err
	}
	m.mu.Lock()
	e := m.vms[sandboxID]
	var vm VM
	if e != nil {
		vm = e.vm
	}
	m.mu.Unlock()
	if e == nil || vm.Attempt != attempt || vm.Generation != generation || t.Generation != generation {
		return GuestTarget{}, apierr.New(pb.ErrorReason_INSTANCE_MISMATCH,
			"sandbox %s runs attempt %d generation %d, the request names attempt %d generation %d",
			sandboxID, vm.Attempt, vm.Generation, attempt, generation)
	}
	return t, nil
}
