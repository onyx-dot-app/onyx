package agent

import (
	"sort"
	"time"
)

// DefaultEndedRetention is the default Config.EndedRetention.
const DefaultEndedRetention = 10 * time.Minute

// EndedReason says how a VM instance ended.
type EndedReason string

const (
	// EndedExited: the Firecracker process ended without a Stop.
	EndedExited EndedReason = "EXITED"
	// EndedStopped: a Stop ended it.
	EndedStopped EndedReason = "STOPPED"
)

// EndedVM is one VM instance that ended on this node.
type EndedVM struct {
	SandboxID  string
	TenantID   string
	Attempt    uint64
	Generation uint64
	Reason     EndedReason
	EndedAt    time.Time
}

type endedKey struct {
	sandboxID  string
	generation uint64
}

// addEndedLocked keeps vm in the ended list for Config.EndedRetention. The
// node state report sends the list in every report in that window, so the
// api_server clears the VM's record even if it misses some reports. A Stop
// of an exited VM keeps the first reason. Needs m.mu.
func (m *Manager) addEndedLocked(vm VM, reason EndedReason) {
	if m.cfg.EndedRetention <= 0 {
		return
	}
	k := endedKey{sandboxID: vm.SandboxID, generation: vm.Generation}
	if _, ok := m.ended[k]; ok {
		return
	}
	m.ended[k] = EndedVM{
		SandboxID: vm.SandboxID, TenantID: vm.TenantID, Attempt: vm.Attempt, Generation: vm.Generation,
		Reason: reason, EndedAt: m.now(),
	}
}

// Ended returns the VM instances that ended within Config.EndedRetention,
// oldest first. The list is in memory only: after an agent restart the
// api_server confirms gone VMs with List.
func (m *Manager) Ended() []EndedVM {
	m.mu.Lock()
	defer m.mu.Unlock()
	cut := m.now().Add(-m.cfg.EndedRetention)
	out := make([]EndedVM, 0, len(m.ended))
	for k, e := range m.ended {
		if e.EndedAt.Before(cut) {
			delete(m.ended, k)
			continue
		}
		out = append(out, e)
	}
	sort.Slice(out, func(i, j int) bool {
		if !out[i].EndedAt.Equal(out[j].EndedAt) {
			return out[i].EndedAt.Before(out[j].EndedAt)
		}
		return out[i].SandboxID < out[j].SandboxID
	})
	return out
}
