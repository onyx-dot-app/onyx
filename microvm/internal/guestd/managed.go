package guestd

import (
	"context"
	"regexp"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// DevState is what the guest sees of one block device.
type DevState struct {
	Present bool
	// Rdev is the device number. The mount point's st_dev equals it when the
	// device is mounted there.
	Rdev uint64
	Size uint64
	// UUID is the ext4 UUID, empty if the device has no ext4 superblock.
	UUID string
	// InUse: the device is claimed (mounted, also by a detached mount that
	// still has open files).
	InUse bool
}

// ManagedOps are the guest system calls of a managed drive swap. The real
// ones are in sysops; tests use fakes.
type ManagedOps interface {
	// Probe reads the state of dev. A missing device is Present false.
	Probe(dev string) (DevState, error)
	// MountedDev returns the st_dev of the top mount on mountPoint, and
	// false if mountPoint is not a mount point.
	MountedDev(mountPoint string) (uint64, bool, error)
	// WaitSize waits until dev has size bytes.
	WaitSize(ctx context.Context, dev string, size uint64) error
	// Flush drops the guest's cached blocks of dev.
	Flush(dev string) error
	// Mount mounts dev (ext4, ro,noload,nodev,nosuid,noexec, private) on
	// mountPoint. With beneath, the new mount goes beneath the current top
	// mount (MOVE_MOUNT_BENEATH); else it goes on the empty mount point.
	Mount(dev, mountPoint string, beneath bool) error
	// DetachTop lazily unmounts the top mount on mountPoint (MNT_DETACH).
	DetachTop(mountPoint string) error
	// MountedOn reports whether device rdev is mounted on mountPoint, at
	// any place in its mount stack.
	MountedOn(mountPoint string, rdev uint64) (bool, error)
}

// ManagedConfig names the managed mount point and the slot devices.
type ManagedConfig struct {
	MountPoint string
	// Devices maps each slot to its guest block device.
	Devices map[pb.ManagedSlot]string
	// SizeWait bounds how long MountManaged waits for the new device size.
	SizeWait time.Duration
	Ops      ManagedOps
}

var uuidRE = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

func (s *Server) managed() (*ManagedConfig, error) {
	mc := s.cfg.Managed
	if mc == nil || mc.Ops == nil || mc.MountPoint == "" {
		return nil, status.Error(codes.Unimplemented, "this daemon has no managed drive slots")
	}
	return mc, nil
}

// slotStates probes every slot and returns them with the active slot.
func (mc *ManagedConfig) slotStates() (pb.ManagedSlot, []*pb.ManagedSlotState, map[pb.ManagedSlot]DevState, error) {
	top, isMount, err := mc.Ops.MountedDev(mc.MountPoint)
	if err != nil {
		return 0, nil, nil, err
	}
	active := pb.ManagedSlot_MANAGED_SLOT_UNSPECIFIED
	var out []*pb.ManagedSlotState
	raw := map[pb.ManagedSlot]DevState{}
	for _, slot := range []pb.ManagedSlot{pb.ManagedSlot_MANAGED_SLOT_A, pb.ManagedSlot_MANAGED_SLOT_B} {
		dev, ok := mc.Devices[slot]
		if !ok {
			continue
		}
		st, err := mc.Ops.Probe(dev)
		if err != nil {
			return 0, nil, nil, err
		}
		raw[slot] = st
		mounted := isMount && st.Present && st.Rdev == top
		if mounted {
			active = slot
		}
		out = append(out, &pb.ManagedSlotState{
			Slot: slot, Device: dev, Present: st.Present, SizeBytes: st.Size, FsUuid: st.UUID,
			Mounted: mounted, InUse: st.InUse,
		})
	}
	return active, out, raw, nil
}

// ManagedStatus implements pb.SandboxdServer.
func (s *Server) ManagedStatus(context.Context, *pb.ManagedStatusRequest) (*pb.ManagedStatusResponse, error) {
	mc, err := s.managed()
	if err != nil {
		return nil, err
	}
	s.managedMu.Lock()
	defer s.managedMu.Unlock()
	active, slots, _, err := mc.slotStates()
	if err != nil {
		return nil, apiError(pb.ErrorReason_INTERNAL, "managed status: %v", err)
	}
	return &pb.ManagedStatusResponse{MountPoint: mc.MountPoint, Active: active, Slots: slots}, nil
}

// MountManaged implements pb.SandboxdServer. Steps, in order: check the
// slot is idle, wait for its new size, drop cached blocks, check the ext4
// UUID, mount it beneath the current mount, detach the old top mount. A
// swap that stopped after its mount (a daemon restart, a failed detach)
// left the slot mounted beneath the old one; a repeat detaches the old top.
func (s *Server) MountManaged(ctx context.Context, r *pb.MountManagedRequest) (*pb.MountManagedResponse, error) {
	mc, err := s.managed()
	if err != nil {
		return nil, err
	}
	dev, ok := mc.Devices[r.GetSlot()]
	if !ok {
		return nil, apiError(pb.ErrorReason_INVALID_ARGUMENT, "slot %s has no device", r.GetSlot())
	}
	if !uuidRE.MatchString(r.GetFsUuid()) {
		return nil, apiError(pb.ErrorReason_INVALID_ARGUMENT, "fs_uuid %q is not a lowercase UUID", r.GetFsUuid())
	}
	if r.GetSizeBytes() == 0 || r.GetSizeBytes()%512 != 0 {
		return nil, apiError(pb.ErrorReason_INVALID_ARGUMENT, "size_bytes %d is not a positive multiple of 512", r.GetSizeBytes())
	}
	s.managedMu.Lock()
	defer s.managedMu.Unlock()

	active, _, states, err := mc.slotStates()
	if err != nil {
		return nil, apiError(pb.ErrorReason_INTERNAL, "managed status: %v", err)
	}
	st := states[r.GetSlot()]
	if !st.Present {
		return nil, apiError(pb.ErrorReason_MANAGED_DEVICE_MISMATCH, "slot %s device %s is missing", r.GetSlot(), dev)
	}
	if active == r.GetSlot() {
		// Idempotent repeat. The host never changes the drive of the active
		// slot, so a different UUID is a host error.
		if st.UUID != r.GetFsUuid() {
			return nil, apiError(pb.ErrorReason_MANAGED_DEVICE_MISMATCH,
				"slot %s is mounted with UUID %q, the request has %q", r.GetSlot(), st.UUID, r.GetFsUuid())
		}
		return &pb.MountManagedResponse{Active: active, Previous: active}, nil
	}
	t0 := time.Now()
	if st.InUse {
		beneath, err := mc.Ops.MountedOn(mc.MountPoint, st.Rdev)
		if err != nil {
			return nil, apiError(pb.ErrorReason_INTERNAL, "managed mounts: %v", err)
		}
		if !beneath {
			return nil, apiError(pb.ErrorReason_MANAGED_SLOT_BUSY,
				"slot %s device %s is in use (a detached mount still has open files)", r.GetSlot(), dev)
		}
		if st.UUID != r.GetFsUuid() {
			return nil, apiError(pb.ErrorReason_MANAGED_DEVICE_MISMATCH,
				"slot %s is mounted beneath with UUID %q, the request has %q", r.GetSlot(), st.UUID, r.GetFsUuid())
		}
		if err := mc.Ops.DetachTop(mc.MountPoint); err != nil {
			return nil, apiError(pb.ErrorReason_MANAGED_MOUNT_FAILED, "detach the old mount on %s: %v", mc.MountPoint, err)
		}
		s.cfg.Log.Warn("finished a managed swap that stopped after its mount", "slot", r.GetSlot(), "device", dev)
		return s.mountedResponse(mc, r.GetSlot(), dev, active, 0, t0)
	}
	wait := mc.SizeWait
	if wait <= 0 {
		wait = 5 * time.Second
	}
	wctx, cancel := context.WithTimeout(ctx, wait)
	err = mc.Ops.WaitSize(wctx, dev, r.GetSizeBytes())
	cancel()
	waitMS := uint64(time.Since(t0).Milliseconds())
	if err != nil {
		if ctx.Err() != nil {
			return nil, execError(ctx.Err())
		}
		return nil, apiError(pb.ErrorReason_MANAGED_DEVICE_MISMATCH, "slot %s device %s: %v", r.GetSlot(), dev, err)
	}
	if err := mc.Ops.Flush(dev); err != nil {
		return nil, apiError(pb.ErrorReason_MANAGED_MOUNT_FAILED, "flush %s: %v", dev, err)
	}
	st, err = mc.Ops.Probe(dev)
	if err != nil {
		return nil, apiError(pb.ErrorReason_INTERNAL, "probe %s: %v", dev, err)
	}
	if st.UUID != r.GetFsUuid() {
		return nil, apiError(pb.ErrorReason_MANAGED_DEVICE_MISMATCH,
			"slot %s device %s has ext4 UUID %q, the request has %q", r.GetSlot(), dev, st.UUID, r.GetFsUuid())
	}
	_, isMount, err := mc.Ops.MountedDev(mc.MountPoint)
	if err != nil {
		return nil, apiError(pb.ErrorReason_INTERNAL, "%v", err)
	}
	if err := mc.Ops.Mount(dev, mc.MountPoint, isMount); err != nil {
		return nil, apiError(pb.ErrorReason_MANAGED_MOUNT_FAILED, "mount %s on %s: %v", dev, mc.MountPoint, err)
	}
	if isMount {
		if err := mc.Ops.DetachTop(mc.MountPoint); err != nil {
			// The new drive is beneath the old one. Leave both: the old
			// drive stays visible, and the slot shows as in use.
			return nil, apiError(pb.ErrorReason_MANAGED_MOUNT_FAILED, "detach the old mount on %s: %v", mc.MountPoint, err)
		}
	}
	return s.mountedResponse(mc, r.GetSlot(), dev, active, waitMS, t0)
}

// mountedResponse checks that slot is now the top mount and reports the swap.
func (s *Server) mountedResponse(mc *ManagedConfig, slot pb.ManagedSlot, dev string, previous pb.ManagedSlot,
	waitMS uint64, t0 time.Time) (*pb.MountManagedResponse, error) {
	now, _, states, err := mc.slotStates()
	if err != nil {
		return nil, apiError(pb.ErrorReason_INTERNAL, "managed status: %v", err)
	}
	if now != slot {
		return nil, apiError(pb.ErrorReason_MANAGED_MOUNT_FAILED, "after the mount, slot %s is on %s, not %s", now, mc.MountPoint, slot)
	}
	resp := &pb.MountManagedResponse{Active: now, Changed: true, Previous: previous, WaitMs: waitMS}
	if prev, ok := states[previous]; ok {
		resp.PreviousInUse = prev.InUse
	}
	s.cfg.Log.Info("managed drive mounted", "slot", now, "device", dev, "previous", previous,
		"previous_in_use", resp.PreviousInUse, "wait_ms", waitMS, "ms", time.Since(t0).Milliseconds())
	return resp, nil
}
