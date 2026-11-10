package guestd

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// fakeDisk is one guest block device.
type fakeDisk struct {
	rdev uint64
	// size is what the guest sees; hostSize is the size it gets after the
	// config change (WaitSize applies it).
	size, hostSize uint64
	uuid           string
	// refs counts mounts (also detached ones with open files).
	refs int
}

// fakeKernel models the mount stack on one mount point.
type fakeKernel struct {
	mu    sync.Mutex
	disks map[string]*fakeDisk
	// stack is the mount stack on the mount point, bottom first.
	stack []string
	// openOnTop: the top mount has open files, so its detach keeps a ref.
	openOnTop  bool
	ops        []string
	failMount  error
	failDetach error
	noResize   bool
}

func (k *fakeKernel) op(format string, args ...any) {
	k.ops = append(k.ops, fmt.Sprintf(format, args...))
}

func (k *fakeKernel) Probe(dev string) (DevState, error) {
	k.mu.Lock()
	defer k.mu.Unlock()
	d := k.disks[dev]
	if d == nil {
		return DevState{}, nil
	}
	return DevState{Present: true, Rdev: d.rdev, Size: d.size, UUID: d.uuid, InUse: d.refs > 0}, nil
}

func (k *fakeKernel) MountedDev(string) (uint64, bool, error) {
	k.mu.Lock()
	defer k.mu.Unlock()
	if len(k.stack) == 0 {
		return 0, false, nil
	}
	return k.disks[k.stack[len(k.stack)-1]].rdev, true, nil
}

func (k *fakeKernel) WaitSize(ctx context.Context, dev string, size uint64) error {
	k.mu.Lock()
	defer k.mu.Unlock()
	k.op("wait %s %d", dev, size)
	d := k.disks[dev]
	if !k.noResize {
		d.size = d.hostSize
	}
	if d.size != size {
		<-ctx.Done()
		return ctx.Err()
	}
	return nil
}

func (k *fakeKernel) Flush(dev string) error {
	k.mu.Lock()
	defer k.mu.Unlock()
	k.op("flush %s", dev)
	return nil
}

func (k *fakeKernel) Mount(dev, _ string, beneath bool) error {
	k.mu.Lock()
	defer k.mu.Unlock()
	k.op("mount %s beneath=%v", dev, beneath)
	if k.failMount != nil {
		return k.failMount
	}
	k.disks[dev].refs++
	if beneath {
		top := k.stack[len(k.stack)-1]
		k.stack = append(k.stack[:len(k.stack)-1], dev, top)
	} else {
		k.stack = append(k.stack, dev)
	}
	return nil
}

func (k *fakeKernel) MountedOn(_ string, rdev uint64) (bool, error) {
	k.mu.Lock()
	defer k.mu.Unlock()
	for _, dev := range k.stack {
		if k.disks[dev].rdev == rdev {
			return true, nil
		}
	}
	return false, nil
}

func (k *fakeKernel) DetachTop(string) error {
	k.mu.Lock()
	defer k.mu.Unlock()
	top := k.stack[len(k.stack)-1]
	k.op("detach %s", top)
	if k.failDetach != nil {
		return k.failDetach
	}
	k.stack = k.stack[:len(k.stack)-1]
	if !k.openOnTop {
		k.disks[top].refs--
	}
	return nil
}

const (
	uuidA = "aaaaaaaa-0000-4000-8000-000000000001"
	uuidB = "bbbbbbbb-0000-4000-8000-000000000002"
)

// newManagedKernel has slot A mounted (attach) and slot B idle with a new
// image behind it, whose size the guest has not seen yet.
func newManagedKernel() *fakeKernel {
	return &fakeKernel{
		disks: map[string]*fakeDisk{
			"/dev/vdc": {rdev: 0xfc02, size: 8 << 20, hostSize: 8 << 20, uuid: uuidA, refs: 1},
			"/dev/vdf": {rdev: 0xfc05, size: 1 << 20, hostSize: 16 << 20, uuid: uuidB},
		},
		stack: []string{"/dev/vdc"},
	}
}

func managedHarness(t *testing.T, k *fakeKernel) pb.SandboxdClient {
	t.Helper()
	h := newHarness(t, execs.Config{}, Config{Managed: &ManagedConfig{
		MountPoint: "/workspace/managed", Ops: k, SizeWait: 200 * time.Millisecond,
		Devices: map[pb.ManagedSlot]string{pb.ManagedSlot_MANAGED_SLOT_A: "/dev/vdc", pb.ManagedSlot_MANAGED_SLOT_B: "/dev/vdf"},
	}})
	return h.initialized()
}

var slotB = &pb.MountManagedRequest{Slot: pb.ManagedSlot_MANAGED_SLOT_B, SizeBytes: 16 << 20, FsUuid: uuidB}

func TestMountManagedStepOrder(t *testing.T) {
	k := newManagedKernel()
	c := managedHarness(t, k)
	ctx := keyed(context.Background())

	st, err := c.ManagedStatus(ctx, &pb.ManagedStatusRequest{})
	if err != nil || st.GetActive() != pb.ManagedSlot_MANAGED_SLOT_A || len(st.GetSlots()) != 2 ||
		!st.GetSlots()[0].GetInUse() || st.GetSlots()[1].GetInUse() {
		t.Fatalf("status before: %v %v", st, err)
	}
	r, err := c.MountManaged(ctx, slotB)
	if err != nil {
		t.Fatal(err)
	}
	if r.GetActive() != pb.ManagedSlot_MANAGED_SLOT_B || !r.GetChanged() || r.GetPrevious() != pb.ManagedSlot_MANAGED_SLOT_A || r.GetPreviousInUse() {
		t.Fatalf("result %v", r)
	}
	// Size first (the config change), then drop cached blocks, then mount
	// beneath the old mount, then detach the old top mount.
	want := "wait /dev/vdf 16777216,flush /dev/vdf,mount /dev/vdf beneath=true,detach /dev/vdc"
	if got := strings.Join(k.ops, ","); got != want {
		t.Fatalf("ops %s\nwant %s", got, want)
	}
	if k.disks["/dev/vdc"].refs != 0 || len(k.stack) != 1 || k.stack[0] != "/dev/vdf" {
		t.Fatalf("kernel %+v %v", k.disks["/dev/vdc"], k.stack)
	}

	// A repeat is a no-op.
	k.ops = nil
	r, err = c.MountManaged(ctx, slotB)
	if err != nil || r.GetChanged() || r.GetActive() != pb.ManagedSlot_MANAGED_SLOT_B || len(k.ops) != 0 {
		t.Fatalf("repeat: %v %v ops %v", r, err, k.ops)
	}
	// The active slot with another UUID is a host error.
	bad := &pb.MountManagedRequest{Slot: pb.ManagedSlot_MANAGED_SLOT_B, SizeBytes: 16 << 20, FsUuid: uuidA}
	if _, err := c.MountManaged(ctx, bad); reason(err) != "MANAGED_DEVICE_MISMATCH" {
		t.Fatalf("active slot, other UUID: %v", err)
	}
}

// A reader on the old drive keeps it busy after the detach: the swap says
// so, and the next swap into that slot is refused until the file closes.
func TestMountManagedOldReaderKeepsSlotBusy(t *testing.T) {
	k := newManagedKernel()
	k.openOnTop = true
	c := managedHarness(t, k)
	ctx := keyed(context.Background())
	r, err := c.MountManaged(ctx, slotB)
	if err != nil || !r.GetPreviousInUse() {
		t.Fatalf("%v %v", r, err)
	}
	back := &pb.MountManagedRequest{Slot: pb.ManagedSlot_MANAGED_SLOT_A, SizeBytes: 8 << 20, FsUuid: uuidA}
	k.ops = nil
	if _, err := c.MountManaged(ctx, back); reason(err) != "MANAGED_SLOT_BUSY" {
		t.Fatalf("busy slot: %v", err)
	}
	if len(k.ops) != 0 {
		t.Fatalf("a busy slot must not be touched: %v", k.ops)
	}
	// The reader closed its file.
	k.disks["/dev/vdc"].refs = 0
	r, err = c.MountManaged(ctx, back)
	if err != nil || r.GetActive() != pb.ManagedSlot_MANAGED_SLOT_A {
		t.Fatalf("after close: %v %v", r, err)
	}
}

// A swap that stopped between the mount and the detach (a daemon restart or
// a failed detach) leaves slot B beneath slot A. A repeat finishes it.
func TestMountManagedFinishesAnInterruptedSwap(t *testing.T) {
	k := newManagedKernel()
	k.failDetach = errors.New("EBUSY")
	c := managedHarness(t, k)
	ctx := keyed(context.Background())
	if _, err := c.MountManaged(ctx, slotB); reason(err) != "MANAGED_MOUNT_FAILED" {
		t.Fatalf("failed detach: %v", err)
	}
	if len(k.stack) != 2 || k.stack[0] != "/dev/vdf" {
		t.Fatalf("stack %v, want vdf beneath vdc", k.stack)
	}
	// Another UUID for the slot beneath is refused, nothing is detached.
	k.failDetach = nil
	k.ops = nil
	bad := &pb.MountManagedRequest{Slot: pb.ManagedSlot_MANAGED_SLOT_B, SizeBytes: 16 << 20, FsUuid: "cccccccc-0000-4000-8000-000000000003"}
	if _, err := c.MountManaged(ctx, bad); reason(err) != "MANAGED_DEVICE_MISMATCH" || len(k.ops) != 0 {
		t.Fatalf("other UUID: %v ops %v", err, k.ops)
	}
	r, err := c.MountManaged(ctx, slotB)
	if err != nil || r.GetActive() != pb.ManagedSlot_MANAGED_SLOT_B || !r.GetChanged() || r.GetPrevious() != pb.ManagedSlot_MANAGED_SLOT_A {
		t.Fatalf("repeat: %v %v", r, err)
	}
	if got := strings.Join(k.ops, ","); got != "detach /dev/vdc" {
		t.Fatalf("ops %s, want only the detach", got)
	}
	if len(k.stack) != 1 || k.stack[0] != "/dev/vdf" || k.disks["/dev/vdc"].refs != 0 {
		t.Fatalf("kernel %v %+v", k.stack, k.disks["/dev/vdc"])
	}
}

func TestMountManagedRefusals(t *testing.T) {
	ctx := keyed(context.Background())
	t.Run("wrong uuid", func(t *testing.T) {
		k := newManagedKernel()
		k.disks["/dev/vdf"].uuid = "cccccccc-0000-4000-8000-000000000003"
		c := managedHarness(t, k)
		if _, err := c.MountManaged(ctx, slotB); reason(err) != "MANAGED_DEVICE_MISMATCH" {
			t.Fatal(err)
		}
		if strings.Contains(strings.Join(k.ops, ","), "mount") || k.stack[0] != "/dev/vdc" {
			t.Fatalf("mounted a wrong drive: %v", k.ops)
		}
	})
	t.Run("size never arrives", func(t *testing.T) {
		k := newManagedKernel()
		k.noResize = true
		c := managedHarness(t, k)
		if _, err := c.MountManaged(ctx, slotB); reason(err) != "MANAGED_DEVICE_MISMATCH" {
			t.Fatal(err)
		}
	})
	t.Run("mount fails", func(t *testing.T) {
		k := newManagedKernel()
		k.failMount = errors.New("EINVAL")
		c := managedHarness(t, k)
		if _, err := c.MountManaged(ctx, slotB); reason(err) != "MANAGED_MOUNT_FAILED" {
			t.Fatal(err)
		}
		if len(k.stack) != 1 || k.stack[0] != "/dev/vdc" {
			t.Fatalf("old drive must stay: %v", k.stack)
		}
	})
	t.Run("missing slot device", func(t *testing.T) {
		k := newManagedKernel()
		delete(k.disks, "/dev/vdf")
		c := managedHarness(t, k)
		if _, err := c.MountManaged(ctx, slotB); reason(err) != "MANAGED_DEVICE_MISMATCH" {
			t.Fatal(err)
		}
	})
	t.Run("bad request", func(t *testing.T) {
		c := managedHarness(t, newManagedKernel())
		for _, r := range []*pb.MountManagedRequest{
			{Slot: pb.ManagedSlot_MANAGED_SLOT_UNSPECIFIED, SizeBytes: 512, FsUuid: uuidB},
			{Slot: pb.ManagedSlot_MANAGED_SLOT_B, SizeBytes: 100, FsUuid: uuidB},
			{Slot: pb.ManagedSlot_MANAGED_SLOT_B, SizeBytes: 512, FsUuid: "B"},
		} {
			if _, err := c.MountManaged(ctx, r); reason(err) != "INVALID_ARGUMENT" {
				t.Errorf("%v: %v", r, err)
			}
		}
	})
	t.Run("needs the key", func(t *testing.T) {
		c := managedHarness(t, newManagedKernel())
		if _, err := c.MountManaged(context.Background(), slotB); reason(err) != "UNAUTHENTICATED" {
			t.Fatal(err)
		}
	})
}

// Without a managed mount (no attach yet), the drive goes on the empty mount
// point and nothing is detached.
func TestMountManagedOnEmptyMountPoint(t *testing.T) {
	k := newManagedKernel()
	k.stack = nil
	k.disks["/dev/vdc"].refs = 0
	c := managedHarness(t, k)
	r, err := c.MountManaged(keyed(context.Background()), slotB)
	if err != nil || r.GetPrevious() != pb.ManagedSlot_MANAGED_SLOT_UNSPECIFIED {
		t.Fatalf("%v %v", r, err)
	}
	if got := strings.Join(k.ops, ","); got != "wait /dev/vdf 16777216,flush /dev/vdf,mount /dev/vdf beneath=false" {
		t.Fatal(got)
	}
}
