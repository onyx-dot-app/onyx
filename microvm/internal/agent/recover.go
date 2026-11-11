package agent

import (
	"context"
	"errors"
	"fmt"

	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// ErrGone means the journaled VM no longer runs: its process exited, or its
// PID now belongs to another process.
var ErrGone = errors.New("VM is not running")

// ErrAPINotResponding means the process is the journaled Firecracker, but its
// API socket did not report a running VM.
var ErrAPINotResponding = errors.New("firecracker API did not report a running VM")

// Candidate is a Firecracker process, or a leftover chroot, that matches the
// agent's jailer layout.
type Candidate struct {
	ID string
	// PID is 0 for a chroot without a process.
	PID int
	// UID is the real UID of the process (the jailer UID).
	UID uint32
}

// Adopter reconnects to VMs after an agent restart. The real one is
// fcvm.Launcher.
type Adopter interface {
	// Adopt verifies that the journaled process is our Firecracker and
	// returns a handle to it. It returns ErrGone if the VM no longer runs. It
	// returns a handle together with ErrAPINotResponding if the process
	// matches but its API does not answer.
	Adopt(ctx context.Context, rec journal.Record) (Process, error)
	// Scan lists the processes and chroots that match the jailer layout. It
	// fails if it cannot read a process: an unreadable process is not absent.
	Scan() ([]Candidate, error)
	// Remove kills a candidate (after it checks it again) and removes its
	// scope and chroot.
	Remove(ctx context.Context, c Candidate) error
}

// RecoverReport counts what Recover did.
type RecoverReport struct {
	Adopted, Unresponsive, Exited, Abandoned, Unverified, Unreadable, Tombstones, Orphans, Leftovers int
}

// What Recover does with the processes and chroots of one sandbox ID.
type action int

const (
	// No journal entry: an orphan. Kill it and remove its files.
	actOrphan action = iota
	// Leave everything alone (adopted, or in doubt).
	actKeep
	// The VM is gone: remove a leftover chroot, keep the record.
	actFilesOnly
	// Create never returned: remove the VM and the record.
	actAbandon
)

// Recover reads the journal and rebuilds the VM table. Call it once, before
// the API serves.
//
//   - running: adopt the VM if its PID is still our Firecracker. A VM that is
//     gone shows as EXITED.
//   - starting: Create never returned, so its VM (if any) is removed.
//   - stopped: restore the tombstone.
//   - unreadable record: log it and leave its VM alone.
//   - a VM in our layout with no record: an orphan; kill it.
//
// It never kills on doubt: if the process scan fails, it removes nothing.
// A VM that it leaves alone without a verified record puts its sandbox in
// doubt (doubt.go) and keeps its UID reserved.
func (m *Manager) Recover(ctx context.Context, a Adopter) (RecoverReport, error) {
	var rep RecoverReport
	if m.journal == nil {
		return rep, errors.New("recover needs a journal")
	}
	m.adopter = a
	recs, bad, err := m.journal.Load()
	if err != nil {
		return rep, fmt.Errorf("read journal: %w", err)
	}
	acts := map[string]action{}
	m.mu.Lock()
	for _, b := range bad {
		acts[b.SandboxID] = actKeep
		m.doubt[b.SandboxID] = &doubt{reason: "journal record unreadable: " + b.Err.Error()}
		rep.Unreadable++
		m.log.Error("journal record unreadable; leaving its VM alone", "sandbox_id", b.SandboxID, "path", b.Path, "err", b.Err)
	}

	for _, r := range recs {
		m.lastGen = max(m.lastGen, r.Generation)
		switch r.State {
		case journal.Stopped:
			acts[r.SandboxID] = actFilesOnly
			if m.now().Sub(r.StoppedAt) > m.cfg.TombstoneTTL {
				m.removeRecord(r.SandboxID)
				continue
			}
			m.tombs[r.SandboxID] = tombstone{attempt: r.Attempt, generation: r.Generation, at: r.StoppedAt}
			rep.Tombstones++
		case journal.Starting:
			acts[r.SandboxID] = actAbandon
			rep.Abandoned++
			// Keep the stopped attempt that this start was replacing.
			if p := r.Prev; p != nil && m.now().Sub(p.StoppedAt) <= m.cfg.TombstoneTTL {
				m.tombs[r.SandboxID] = tombstone{attempt: p.Attempt, generation: p.Generation, at: p.StoppedAt}
				rep.Tombstones++
			}
		case journal.Running:
			acts[r.SandboxID] = m.adoptLocked(ctx, a, r, &rep)
		}
	}
	m.mu.Unlock()

	cands, err := a.Scan()
	if err != nil {
		m.log.Error("scan for VMs failed; nothing is removed, and no VM starts until a scan works", "err", err)
		m.mu.Lock()
		m.needScan = true
		m.mu.Unlock()
		return rep, nil
	}
	for _, c := range cands {
		act := acts[c.ID] // actOrphan when there is no record
		switch {
		case act == actKeep:
			m.mu.Lock()
			if d := m.doubt[c.ID]; d != nil && c.PID != 0 {
				m.reserveLocked(d, c.UID)
			}
			m.mu.Unlock()
			continue
		case act == actFilesOnly && c.PID != 0:
			// A live Firecracker for a sandbox whose journaled VM is gone or
			// stopped: in doubt, leave it.
			m.log.Error("unexpected Firecracker for a stopped or gone VM; leaving it alone", "sandbox_id", c.ID, "pid", c.PID)
			m.mu.Lock()
			d := m.doubt[c.ID]
			if d == nil {
				d = &doubt{reason: "a Firecracker process for a stopped or gone VM"}
				m.doubt[c.ID] = d
			}
			m.reserveLocked(d, c.UID)
			m.mu.Unlock()
			continue
		}
		if c.PID != 0 && act == actOrphan {
			rep.Orphans++
		} else if c.PID == 0 {
			rep.Leftovers++
		}
		m.log.Warn("removing VM files", "sandbox_id", c.ID, "pid", c.PID, "journal", act != actOrphan)
		if err := a.Remove(ctx, c); err != nil {
			m.log.Error("remove VM", "sandbox_id", c.ID, "pid", c.PID, "err", err)
			delete(acts, c.ID)
			continue
		}
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	for id, act := range acts {
		if act != actAbandon {
			continue
		}
		if t, ok := m.tombs[id]; ok {
			if err := m.writeTombstone(id, t); err != nil {
				m.log.Error("write journal tombstone", "sandbox_id", id, "err", err)
			}
		} else {
			m.removeRecord(id)
		}
	}
	return rep, nil
}

func (m *Manager) adoptLocked(ctx context.Context, a Adopter, r journal.Record, rep *RecoverReport) action {
	reserved := m.uids.Reserve(r.UID)
	if !reserved {
		m.log.Warn("journaled UID is out of range or in use", "sandbox_id", r.SandboxID, "uid", r.UID)
	}
	e := &entry{vm: VM{
		SandboxID: r.SandboxID, Attempt: r.Attempt, Generation: r.Generation, Template: r.Template,
		VCPUs: r.VCPUs, MemMiB: r.MemMiB, ScratchGiB: r.ScratchGiB, PID: r.PID, UID: r.UID, StartedAt: r.StartedAt, TenantID: r.TenantID,
		State: pb.VMState_VM_STATE_RUNNING, Managed: managedFromRecord(r.Managed),
	}}
	proc, err := a.Adopt(ctx, r)
	switch {
	case err == nil:
		rep.Adopted++
	case proc != nil && errors.Is(err, ErrAPINotResponding):
		// Same process, but the API did not answer. Keep it: never kill on
		// doubt. Stop can still kill it.
		rep.Unresponsive++
		m.log.Error("adopted VM whose API does not answer", "sandbox_id", r.SandboxID, "pid", r.PID, "err", err)
	case errors.Is(err, ErrGone):
		rep.Exited++
		e.vm.State = pb.VMState_VM_STATE_EXITED
		m.vms[r.SandboxID] = e
		m.log.Warn("journaled VM is gone", "sandbox_id", r.SandboxID, "pid", r.PID)
		return actFilesOnly
	default:
		rep.Unverified++
		m.log.Error("cannot verify journaled VM; leaving it alone", "sandbox_id", r.SandboxID, "pid", r.PID, "err", err)
		d := &doubt{reason: "cannot verify the journaled VM: " + err.Error()}
		if reserved {
			d.uids = []uint32{r.UID}
		}
		m.doubt[r.SandboxID] = d
		return actKeep
	}
	e.proc = proc
	m.vms[r.SandboxID] = e
	if m.egress != nil {
		if err := m.egress.Attach(e.vm, proc.Info()); err != nil {
			m.log.Error("attach egress relay to adopted VM", "sandbox_id", r.SandboxID, "err", err)
		}
	}
	go m.watch(r.SandboxID, e)
	return actKeep
}
