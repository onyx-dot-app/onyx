package agent

import (
	"context"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// ManagedState is the managed drive slots of a VM (ENG-4614).
type ManagedState struct {
	// Slots is 2 for a VM that can swap its managed drive, else 1.
	Slots int
	// Active is the slot on /workspace/managed after the last swap.
	Active pb.ManagedSlot
	// A and B are the image IDs behind the slots ("" = the placeholder).
	A, B string
	// PendingSlot and PendingImage are set while a swap runs.
	PendingSlot  pb.ManagedSlot
	PendingImage string
}

// Image returns the image behind slot.
func (s ManagedState) Image(slot pb.ManagedSlot) string {
	if slot == pb.ManagedSlot_MANAGED_SLOT_B {
		return s.B
	}
	return s.A
}

func (s *ManagedState) setImage(slot pb.ManagedSlot, id string) {
	if slot == pb.ManagedSlot_MANAGED_SLOT_B {
		s.B = id
	} else {
		s.A = id
	}
}

var slotNames = map[pb.ManagedSlot]string{pb.ManagedSlot_MANAGED_SLOT_A: "a", pb.ManagedSlot_MANAGED_SLOT_B: "b"}

func slotByName(n string) pb.ManagedSlot {
	for s, name := range slotNames {
		if name == n {
			return s
		}
	}
	return pb.ManagedSlot_MANAGED_SLOT_UNSPECIFIED
}

func (s ManagedState) record() *journal.Managed {
	r := &journal.Managed{Slots: s.Slots, Active: slotNames[s.Active], A: s.A, B: s.B}
	if s.PendingSlot != pb.ManagedSlot_MANAGED_SLOT_UNSPECIFIED {
		r.Pending = &journal.PendingSwap{Slot: slotNames[s.PendingSlot], Image: s.PendingImage}
	}
	return r
}

func managedFromRecord(r *journal.Managed) ManagedState {
	if r == nil {
		return ManagedState{Slots: 1, Active: pb.ManagedSlot_MANAGED_SLOT_A}
	}
	s := ManagedState{Slots: r.Slots, Active: slotByName(r.Active), A: r.A, B: r.B}
	if s.Active == pb.ManagedSlot_MANAGED_SLOT_UNSPECIFIED {
		s.Active = pb.ManagedSlot_MANAGED_SLOT_A
	}
	if r.Pending != nil {
		s.PendingSlot, s.PendingImage = slotByName(r.Pending.Slot), r.Pending.Image
	}
	return s
}

// SlotDrive returns the Firecracker drive ID and chroot file of a slot.
func SlotDrive(slot pb.ManagedSlot) (driveID, file string) {
	if slot == pb.ManagedSlot_MANAGED_SLOT_B {
		return template.ManagedBDriveID, template.ManagedBFile
	}
	return template.ManagedDriveID, template.ManagedFile
}

// OtherSlot returns the idle slot when slot is active. With no managed
// drive mounted (UNSPECIFIED), slot B is used, so slot A keeps the
// template placeholder.
func OtherSlot(active pb.ManagedSlot) pb.ManagedSlot {
	if active == pb.ManagedSlot_MANAGED_SLOT_B {
		return pb.ManagedSlot_MANAGED_SLOT_A
	}
	return pb.ManagedSlot_MANAGED_SLOT_B
}

// ManagedImage is a managed image on the node.
type ManagedImage struct {
	ID   string
	Path string
	Size uint64
	UUID string
}

// GuestSlot is what the guest daemon reports for one slot.
type GuestSlot struct {
	Present bool
	InUse   bool
	UUID    string
}

// GuestManaged is the guest daemon's ManagedStatus.
type GuestManaged struct {
	Active pb.ManagedSlot
	Slots  map[pb.ManagedSlot]GuestSlot
}

// GuestMount is the guest daemon's MountManaged result.
type GuestMount struct {
	Active        pb.ManagedSlot
	Changed       bool
	PreviousInUse bool
}

// ManagedGuest calls the guest daemon of one VM with its key. Errors are
// apierr errors with the host agent reasons. The real one is in
// internal/server.
type ManagedGuest interface {
	Status(ctx context.Context, t GuestTarget, key string) (GuestManaged, error)
	Mount(ctx context.Context, t GuestTarget, key string, slot pb.ManagedSlot, size uint64, uuid string) (GuestMount, error)
}

// DriveReplacer is a Process that can change the file behind a drive
// (Firecracker PATCH /drives). fcvm.Proc implements it.
type DriveReplacer interface {
	// ReplaceDrive puts a reflink copy of src at /<file> in the VM chroot
	// and makes Firecracker open it for drive driveID.
	ReplaceDrive(ctx context.Context, driveID, file, src string) error
}

// UseManagedGuest enables SwapManaged. Call it before the API serves.
func (m *Manager) UseManagedGuest(g ManagedGuest, timeout time.Duration) {
	m.managedGuest, m.swapTimeout = g, timeout
}

// SwapTarget is one VM of SwapManaged.
type SwapTarget struct {
	SandboxID  string
	Attempt    uint64
	Generation uint64
	Key        string
}

// SwapResult is the result of one VM.
type SwapResult struct {
	SandboxID     string
	Err           error
	Active        pb.ManagedSlot
	Changed       bool
	PreviousInUse bool
	Took          time.Duration
}

// SwapManaged puts img into each target VM, one at a time, in order. A
// swap that has begun finishes even if ctx ends; the VMs after it get the
// context error.
func (m *Manager) SwapManaged(ctx context.Context, img ManagedImage, targets []SwapTarget) []SwapResult {
	out := make([]SwapResult, 0, len(targets))
	for _, t := range targets {
		if err := ctx.Err(); err != nil {
			out = append(out, SwapResult{SandboxID: t.SandboxID, Err: err})
			continue
		}
		t0 := m.now()
		r := m.swapOne(context.WithoutCancel(ctx), img, t)
		r.SandboxID, r.Took = t.SandboxID, m.now().Sub(t0)
		lvl := m.log.Info
		if r.Err != nil {
			lvl = m.log.Warn
		}
		lvl("managed swap", "sandbox_id", t.SandboxID, "image", img.ID, "active", r.Active, "changed", r.Changed,
			"previous_in_use", r.PreviousInUse, "ms", r.Took.Milliseconds(), "err", r.Err)
		out = append(out, r)
	}
	return out
}

// beginSwap marks the VM as swapping. Create and Stop of the sandbox wait
// for the swap to end.
func (m *Manager) beginSwap(ctx context.Context, t SwapTarget) (*entry, error) {
	if !sandboxIDRE.MatchString(t.SandboxID) {
		return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "sandbox_id %q is not a lowercase UUID", t.SandboxID)
	}
	for {
		m.mu.Lock()
		e := m.vms[t.SandboxID]
		if e == nil {
			m.mu.Unlock()
			return nil, apierr.New(pb.ErrorReason_SANDBOX_NOT_FOUND, "sandbox %s has no VM on this node", t.SandboxID)
		}
		if e.vm.Attempt != t.Attempt || e.vm.Generation != t.Generation {
			vm := e.vm
			m.mu.Unlock()
			return nil, apierr.New(pb.ErrorReason_INSTANCE_MISMATCH,
				"sandbox %s runs attempt %d generation %d, the request names attempt %d generation %d",
				t.SandboxID, vm.Attempt, vm.Generation, t.Attempt, t.Generation)
		}
		if e.swap != nil {
			ch := e.swap
			m.mu.Unlock()
			if err := waitFor(ctx, ch); err != nil {
				return nil, err
			}
			continue
		}
		if e.proc == nil || e.busy != nil || e.vm.State != pb.VMState_VM_STATE_RUNNING {
			state := e.vm.State.String()
			m.mu.Unlock()
			return nil, apierr.New(pb.ErrorReason_VM_NOT_RUNNING, "sandbox %s VM is %s", t.SandboxID, state)
		}
		if e.vm.Managed.Slots < 2 {
			tpl := e.vm.Template
			m.mu.Unlock()
			return nil, apierr.New(pb.ErrorReason_MANAGED_SWAP_UNSUPPORTED,
				"sandbox %s runs template %s, which has no managed slot B", t.SandboxID, tpl)
		}
		e.swap = make(chan struct{})
		m.mu.Unlock()
		return e, nil
	}
}

func (m *Manager) endSwap(e *entry) {
	m.mu.Lock()
	defer m.mu.Unlock()
	close(e.swap)
	e.swap = nil
}

// setManaged updates the VM's slots and writes its journal record.
func (m *Manager) setManaged(e *entry, f func(*ManagedState)) error {
	m.mu.Lock()
	f(&e.vm.Managed)
	rec := m.record(e, journal.Running, e.proc.Info())
	m.mu.Unlock()
	if err := m.writeRecord(rec); err != nil {
		return apierr.New(pb.ErrorReason_INTERNAL, "write journal: %v", err)
	}
	return nil
}

func (m *Manager) swapOne(ctx context.Context, img ManagedImage, t SwapTarget) SwapResult {
	if m.managedGuest == nil {
		return SwapResult{Err: apierr.New(pb.ErrorReason_MANAGED_SWAP_UNSUPPORTED, "the agent has no managed drive support")}
	}
	timeout := m.swapTimeout
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	e, err := m.beginSwap(ctx, t)
	if err != nil {
		return SwapResult{Err: err}
	}
	defer m.endSwap(e)
	m.mu.Lock()
	target := GuestTarget{VsockUDS: e.proc.Info().VsockUDS, Generation: e.vm.Generation}
	proc := e.proc
	m.mu.Unlock()
	dr, ok := proc.(DriveReplacer)
	if !ok {
		return SwapResult{Err: apierr.New(pb.ErrorReason_MANAGED_SWAP_UNSUPPORTED, "the VM process cannot change drives")}
	}

	// The guest is the truth for which slot is mounted: a swap that an agent
	// restart cut short may have finished in the guest.
	gs, err := m.managedGuest.Status(ctx, target, t.Key)
	if err != nil {
		return SwapResult{Err: err}
	}
	active := gs.Active
	res := SwapResult{Active: active}
	if active != pb.ManagedSlot_MANAGED_SLOT_UNSPECIFIED && gs.Slots[active].UUID == img.UUID {
		// Already active. Fix the record if a cut-short swap left it behind.
		err := m.setManaged(e, func(s *ManagedState) {
			s.Active = active
			s.setImage(active, img.ID)
			s.PendingSlot, s.PendingImage = 0, ""
		})
		res.Err = err
		return res
	}
	idle := OtherSlot(active)
	if !gs.Slots[idle].Present {
		res.Err = apierr.New(pb.ErrorReason_MANAGED_SWAP_UNSUPPORTED, "the guest has no device for managed slot %s", idle)
		return res
	}
	// A busy idle slot that already holds this image is a swap that stopped
	// after its guest mount: the guest Mount finishes it, with no drive
	// change. Another busy slot still holds the drive of an older swap.
	resume := gs.Slots[idle].InUse && gs.Slots[idle].UUID == img.UUID
	if gs.Slots[idle].InUse && !resume {
		res.Err = apierr.New(pb.ErrorReason_MANAGED_SLOT_BUSY,
			"slot %s still holds the drive before the last swap: a guest process has a file open on it", idle)
		return res
	}
	// Record the swap before the drive changes, so a restarted agent knows
	// the slot content is not the recorded one.
	if err := m.setManaged(e, func(s *ManagedState) {
		s.Active = active
		s.PendingSlot, s.PendingImage = idle, img.ID
	}); err != nil {
		res.Err = err
		return res
	}
	if !resume {
		driveID, file := SlotDrive(idle)
		if err := dr.ReplaceDrive(ctx, driveID, file, img.Path); err != nil {
			res.Err = apierr.New(pb.ErrorReason_VMM_FAILED, "put image %s behind slot %s: %v", img.ID, idle, err)
			return res
		}
	}
	if err := m.setManaged(e, func(s *ManagedState) { s.setImage(idle, img.ID) }); err != nil {
		res.Err = err
		return res
	}
	mr, err := m.managedGuest.Mount(ctx, target, t.Key, idle, img.Size, img.UUID)
	if err != nil {
		res.Err = err
		return res
	}
	res.Active, res.Changed, res.PreviousInUse = mr.Active, mr.Changed, mr.PreviousInUse
	if mr.Active != idle {
		res.Err = apierr.New(pb.ErrorReason_MANAGED_MOUNT_FAILED, "the guest reports slot %s active after mounting %s", mr.Active, idle)
		return res
	}
	res.Err = m.setManaged(e, func(s *ManagedState) {
		s.Active = idle
		s.PendingSlot, s.PendingImage = 0, ""
	})
	return res
}

// ManagedImagesInUse returns the image IDs behind a slot of any VM, also of
// a swap in progress.
func (m *Manager) ManagedImagesInUse() map[string]bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := map[string]bool{}
	for _, e := range m.vms {
		for _, id := range []string{e.vm.Managed.A, e.vm.Managed.B, e.vm.Managed.PendingImage} {
			if id != "" {
				out[id] = true
			}
		}
	}
	return out
}
