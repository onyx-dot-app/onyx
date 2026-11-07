package agent

import (
	"context"
	"errors"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// doubt is a sandbox whose Firecracker the agent leaves running although it
// could not verify it: an unreadable record, an Adopt that failed, a live
// process for a stopped VM, or a failed start whose process may still run.
// Create and Stop of the sandbox fail with SANDBOX_IN_DOUBT, and its record
// is never overwritten or removed. The doubt clears when a scan finds no
// Firecracker of the sandbox. An agent restart also re-applies the recover
// rules.
type doubt struct {
	reason string
	// uids are the jailer UIDs that the doubt holds in the pool.
	uids []uint32
}

// checkDoubt fails if sandbox id is in doubt. Before it fails, it scans
// again, so a doubt clears once its process has exited. With create set it
// also fails while the UIDs of kept processes are unknown.
func (m *Manager) checkDoubt(ctx context.Context, id string, create bool) error {
	m.mu.Lock()
	need := m.doubt[id] != nil || (create && m.needScan)
	m.mu.Unlock()
	if !need {
		return nil
	}
	if err := m.rescan(ctx); err != nil {
		m.log.Error("process scan failed", "sandbox_id", id, "err", err)
		m.mu.Lock()
		inDoubt := m.doubt[id] != nil
		m.mu.Unlock()
		if inDoubt {
			return m.doubtError(id)
		}
		return apierr.New(pb.ErrorReason_CAPACITY_VM_SLOTS,
			"the agent cannot scan its Firecracker processes (%v), so it starts no VM", err)
	}
	m.mu.Lock()
	inDoubt := m.doubt[id] != nil
	m.mu.Unlock()
	if inDoubt {
		return m.doubtError(id)
	}
	return nil
}

func (m *Manager) doubtError(id string) error {
	m.mu.Lock()
	reason := "unknown"
	if d := m.doubt[id]; d != nil {
		reason = d.reason
	}
	m.mu.Unlock()
	path := "the journal record"
	if m.journal != nil {
		path = m.journal.Path(id)
	}
	return apierr.New(pb.ErrorReason_SANDBOX_IN_DOUBT,
		"sandbox %s has a Firecracker process that the agent keeps but could not verify (%s). "+
			"This clears when that process exits. Or fix or remove %s and restart the agent", id, reason, path)
}

// rescan lists the Firecracker processes again. A live process that the
// agent does not track puts its sandbox in doubt and reserves its UID. A
// doubt with no live process clears: its leftover chroot is removed and its
// UIDs are freed.
func (m *Manager) rescan(ctx context.Context) error {
	if m.adopter == nil {
		return errors.New("no process scanner")
	}
	m.scanMu.Lock()
	defer m.scanMu.Unlock()
	cands, err := m.adopter.Scan()
	if err != nil {
		return err
	}
	live := map[string]bool{}
	m.mu.Lock()
	for _, c := range cands {
		d := m.doubt[c.ID]
		if c.PID == 0 || (d == nil && m.vms[c.ID] != nil) {
			continue
		}
		live[c.ID] = true
		if d == nil {
			d = &doubt{reason: "a Firecracker process with no verified record"}
			m.doubt[c.ID] = d
			m.log.Error("untracked Firecracker; the sandbox is in doubt", "sandbox_id", c.ID, "pid", c.PID)
		}
		m.reserveLocked(d, c.UID)
	}
	m.needScan = false
	var gone []string
	for id := range m.doubt {
		if !live[id] {
			gone = append(gone, id)
		}
	}
	m.mu.Unlock()

	for _, id := range gone {
		// No process: remove the files it left. Create cannot run for id
		// while the doubt is set.
		if err := m.adopter.Remove(ctx, Candidate{ID: id}); err != nil {
			m.log.Error("remove files of a cleared doubt", "sandbox_id", id, "err", err)
			continue
		}
		m.mu.Lock()
		if d := m.doubt[id]; d != nil {
			for _, uid := range d.uids {
				m.uids.Put(uid)
			}
			delete(m.doubt, id)
		}
		m.mu.Unlock()
		m.log.Info("doubt cleared: the process is gone", "sandbox_id", id)
	}
	return nil
}

// reserveLocked holds uid in the pool for d, if no one holds it yet.
func (m *Manager) reserveLocked(d *doubt, uid uint32) {
	for _, u := range d.uids {
		if u == uid {
			return
		}
	}
	if m.uids.Reserve(uid) {
		d.uids = append(d.uids, uid)
	}
}
