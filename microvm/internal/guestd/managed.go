package guestd

import (
	"context"
	"fmt"
	"path/filepath"
	"regexp"
	"strings"
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

// ManagedMount is one named managed mount and its slot devices.
type ManagedMount struct {
	Name       string
	MountPoint string
	// Devices maps each slot to its guest block device.
	Devices map[pb.ManagedSlot]string
}

// DefaultManagedMount is the mount of a call with an empty mount name.
const DefaultManagedMount = "skills"

// DefaultManagedMounts match the image's attach script and the host agent's
// layout 5 drive order (rootfs vda, scratch vdb, skills A vdc, upload
// vdd/vde, skills B vdf, then two slots per added mount).
var DefaultManagedMounts = []ManagedMount{
	{Name: "skills", MountPoint: "/mnt/skills", Devices: slotDevs("/dev/vdc", "/dev/vdf")},
	{Name: "user-uploads", MountPoint: "/mnt/user-uploads", Devices: slotDevs("/dev/vdg", "/dev/vdh")},
	{Name: "spaces", MountPoint: "/mnt/spaces", Devices: slotDevs("/dev/vdi", "/dev/vdj")},
}

// FormatManagedMounts writes mounts in the ParseManagedMounts form.
func FormatManagedMounts(mounts []ManagedMount) string {
	parts := make([]string, 0, len(mounts))
	for _, m := range mounts {
		parts = append(parts, fmt.Sprintf("%s=%s:%s:%s", m.Name, m.MountPoint,
			m.Devices[pb.ManagedSlot_MANAGED_SLOT_A], m.Devices[pb.ManagedSlot_MANAGED_SLOT_B]))
	}
	return strings.Join(parts, ",")
}

var mountNameRE = regexp.MustCompile(`^[a-z][a-z0-9-]{0,31}$`)

// ParseManagedMounts reads "name=/mount/point:/dev/slotA:/dev/slotB,...".
// An empty string is no mounts.
func ParseManagedMounts(s string) ([]ManagedMount, error) {
	var out []ManagedMount
	seen := map[string]bool{}
	for _, item := range strings.Split(s, ",") {
		if item = strings.TrimSpace(item); item == "" {
			continue
		}
		name, rest, ok := strings.Cut(item, "=")
		parts := strings.Split(rest, ":")
		if !ok || !mountNameRE.MatchString(name) || len(parts) != 3 {
			return nil, fmt.Errorf("managed mount %q: want name=/mount/point:/dev/a:/dev/b", item)
		}
		for _, p := range parts {
			if !filepath.IsAbs(p) {
				return nil, fmt.Errorf("managed mount %q: %q is not absolute", item, p)
			}
		}
		for _, k := range []string{name, parts[0], parts[1], parts[2]} {
			if seen[k] {
				return nil, fmt.Errorf("managed mount %q: a name, mount point or device is used twice", item)
			}
			seen[k] = true
		}
		out = append(out, ManagedMount{Name: name, MountPoint: parts[0], Devices: slotDevs(parts[1], parts[2])})
	}
	return out, nil
}

func slotDevs(a, b string) map[pb.ManagedSlot]string {
	return map[pb.ManagedSlot]string{pb.ManagedSlot_MANAGED_SLOT_A: a, pb.ManagedSlot_MANAGED_SLOT_B: b}
}

// ManagedConfig names the managed mounts and their slot devices.
type ManagedConfig struct {
	Mounts []ManagedMount
	// SizeWait bounds how long MountManaged waits for the new device size.
	SizeWait time.Duration
	Ops      ManagedOps
}

var uuidRE = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// managed returns the mount of a call. An empty name is the default mount.
func (s *Server) managed(name string) (*ManagedConfig, *ManagedMount, error) {
	mc := s.cfg.Managed
	if mc == nil || mc.Ops == nil || len(mc.Mounts) == 0 {
		return nil, nil, status.Error(codes.Unimplemented, "this daemon has no managed drive slots")
	}
	if name == "" {
		name = DefaultManagedMount
	}
	for i := range mc.Mounts {
		if mc.Mounts[i].Name == name {
			return mc, &mc.Mounts[i], nil
		}
	}
	return nil, nil, apiError(pb.ErrorReason_INVALID_ARGUMENT, "unknown managed mount %q", name)
}

// slotStates probes every slot of mt and returns them with the active slot.
func (mc *ManagedConfig) slotStates(mt *ManagedMount) (pb.ManagedSlot, []*pb.ManagedSlotState, map[pb.ManagedSlot]DevState, error) {
	top, isMount, err := mc.Ops.MountedDev(mt.MountPoint)
	if err != nil {
		return 0, nil, nil, err
	}
	active := pb.ManagedSlot_MANAGED_SLOT_UNSPECIFIED
	var out []*pb.ManagedSlotState
	raw := map[pb.ManagedSlot]DevState{}
	for _, slot := range []pb.ManagedSlot{pb.ManagedSlot_MANAGED_SLOT_A, pb.ManagedSlot_MANAGED_SLOT_B} {
		dev, ok := mt.Devices[slot]
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
func (s *Server) ManagedStatus(_ context.Context, r *pb.ManagedStatusRequest) (*pb.ManagedStatusResponse, error) {
	mc, mt, err := s.managed(r.GetMount())
	if err != nil {
		return nil, err
	}
	s.managedMu.Lock()
	defer s.managedMu.Unlock()
	active, slots, _, err := mc.slotStates(mt)
	if err != nil {
		return nil, apiError(pb.ErrorReason_INTERNAL, "managed status: %v", err)
	}
	return &pb.ManagedStatusResponse{MountPoint: mt.MountPoint, Active: active, Slots: slots, Mount: mt.Name}, nil
}

// MountManaged implements pb.SandboxdServer. Steps, in order: check the
// slot is idle, wait for its new size, drop cached blocks, check the ext4
// UUID, mount it beneath the current mount, detach the old top mount. A
// swap that stopped after its mount (a daemon restart, a failed detach)
// left the slot mounted beneath the old one; a repeat detaches the old top.
func (s *Server) MountManaged(ctx context.Context, r *pb.MountManagedRequest) (*pb.MountManagedResponse, error) {
	mc, mt, err := s.managed(r.GetMount())
	if err != nil {
		return nil, err
	}
	dev, ok := mt.Devices[r.GetSlot()]
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

	active, _, states, err := mc.slotStates(mt)
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
		return &pb.MountManagedResponse{Active: active, Previous: active, Mount: mt.Name}, nil
	}
	t0 := time.Now()
	if st.InUse {
		beneath, err := mc.Ops.MountedOn(mt.MountPoint, st.Rdev)
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
		if err := mc.Ops.DetachTop(mt.MountPoint); err != nil {
			return nil, apiError(pb.ErrorReason_MANAGED_MOUNT_FAILED, "detach the old mount on %s: %v", mt.MountPoint, err)
		}
		s.cfg.Log.Warn("finished a managed swap that stopped after its mount", "mount", mt.Name, "slot", r.GetSlot(), "device", dev)
		return s.mountedResponse(mc, mt, r.GetSlot(), dev, active, 0, t0)
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
	_, isMount, err := mc.Ops.MountedDev(mt.MountPoint)
	if err != nil {
		return nil, apiError(pb.ErrorReason_INTERNAL, "%v", err)
	}
	if err := mc.Ops.Mount(dev, mt.MountPoint, isMount); err != nil {
		return nil, apiError(pb.ErrorReason_MANAGED_MOUNT_FAILED, "mount %s on %s: %v", dev, mt.MountPoint, err)
	}
	if isMount {
		if err := mc.Ops.DetachTop(mt.MountPoint); err != nil {
			// The new drive is beneath the old one. Leave both: the old
			// drive stays visible, and the slot shows as in use.
			return nil, apiError(pb.ErrorReason_MANAGED_MOUNT_FAILED, "detach the old mount on %s: %v", mt.MountPoint, err)
		}
	}
	return s.mountedResponse(mc, mt, r.GetSlot(), dev, active, waitMS, t0)
}

// mountedResponse checks that slot is now the top mount and reports the swap.
func (s *Server) mountedResponse(mc *ManagedConfig, mt *ManagedMount, slot pb.ManagedSlot, dev string, previous pb.ManagedSlot,
	waitMS uint64, t0 time.Time) (*pb.MountManagedResponse, error) {
	now, _, states, err := mc.slotStates(mt)
	if err != nil {
		return nil, apiError(pb.ErrorReason_INTERNAL, "managed status: %v", err)
	}
	if now != slot {
		return nil, apiError(pb.ErrorReason_MANAGED_MOUNT_FAILED, "after the mount, slot %s is on %s, not %s", now, mt.MountPoint, slot)
	}
	resp := &pb.MountManagedResponse{Active: now, Changed: true, Previous: previous, WaitMs: waitMS, Mount: mt.Name}
	if prev, ok := states[previous]; ok {
		resp.PreviousInUse = prev.InUse
	}
	s.cfg.Log.Info("managed drive mounted", "mount", mt.Name, "slot", now, "device", dev, "previous", previous,
		"previous_in_use", resp.PreviousInUse, "wait_ms", waitMS, "ms", time.Since(t0).Milliseconds())
	return resp, nil
}
