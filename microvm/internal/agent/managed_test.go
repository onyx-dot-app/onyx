package agent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

const (
	slotA = pb.ManagedSlot_MANAGED_SLOT_A
	slotB = pb.ManagedSlot_MANAGED_SLOT_B
)

// fakeGuest models the guest side of every VM: which slot is mounted, the
// UUID behind each slot, and open files on detached mounts. ops records the
// host and guest steps in order.
type fakeGuest struct {
	mu sync.Mutex
	// vms by vsock path (fakeProc has none, so all VMs share key "").
	active map[string]pb.ManagedSlot
	uuids  map[string]map[pb.ManagedSlot]string
	busy   map[string]map[pb.ManagedSlot]bool
	// pathUUID maps an image path to its UUID (what the drive holds).
	pathUUID map[string]string
	ops      []string
	key      string
	// keepReaders: the old drive stays busy after a swap.
	keepReaders bool
	// mountGate, if set, blocks Mount until closed.
	mountGate chan struct{}
	// onReplace runs inside ReplaceDrive.
	onReplace func()
	failMount error
}

func newFakeGuest() *fakeGuest {
	return &fakeGuest{
		active: map[string]pb.ManagedSlot{}, uuids: map[string]map[pb.ManagedSlot]string{},
		busy: map[string]map[pb.ManagedSlot]bool{}, pathUUID: map[string]string{}, key: "the-key",
	}
}

func (g *fakeGuest) vm(id string) {
	if _, ok := g.uuids[id]; !ok {
		g.active[id] = slotA
		g.uuids[id] = map[pb.ManagedSlot]string{slotA: "placeholder-a", slotB: ""}
		g.busy[id] = map[pb.ManagedSlot]bool{slotA: true}
	}
}

func (g *fakeGuest) Status(_ context.Context, t GuestTarget, key string) (GuestManaged, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if key != g.key {
		return GuestManaged{}, apierr.New(pb.ErrorReason_GUEST_KEY_REJECTED, "wrong key")
	}
	id := t.VsockUDS
	g.vm(id)
	g.ops = append(g.ops, "status")
	out := GuestManaged{Active: g.active[id], Slots: map[pb.ManagedSlot]GuestSlot{}}
	for _, s := range []pb.ManagedSlot{slotA, slotB} {
		out.Slots[s] = GuestSlot{Present: true, InUse: g.busy[id][s], UUID: g.uuids[id][s]}
	}
	return out, nil
}

func (g *fakeGuest) Mount(_ context.Context, t GuestTarget, key string, slot pb.ManagedSlot, _ uint64, uuid string) (GuestMount, error) {
	if g.mountGate != nil {
		<-g.mountGate
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	id := t.VsockUDS
	g.ops = append(g.ops, fmt.Sprintf("mount %s", slotNames[slot]))
	if g.failMount != nil {
		return GuestMount{}, g.failMount
	}
	if g.uuids[id][slot] != uuid {
		return GuestMount{}, apierr.New(pb.ErrorReason_MANAGED_MOUNT_FAILED, "uuid %s, want %s", g.uuids[id][slot], uuid)
	}
	prev := g.active[id]
	g.active[id] = slot
	g.busy[id][slot] = true
	g.busy[id][prev] = g.keepReaders
	return GuestMount{Active: slot, Changed: true, PreviousInUse: g.keepReaders}, nil
}

// guestProc is a fakeProc that can change its drives.
type guestProc struct {
	*fakeProc
	id string
	g  *fakeGuest
}

func (p *guestProc) Info() ProcInfo {
	i := p.fakeProc.Info()
	i.VsockUDS = p.id
	return i
}

func (p *guestProc) ReplaceDrive(_ context.Context, driveID, file, src string) error {
	if p.g.onReplace != nil {
		p.g.onReplace()
	}
	p.g.mu.Lock()
	defer p.g.mu.Unlock()
	p.g.vm(p.id)
	p.g.ops = append(p.g.ops, "replace "+driveID+" /"+file)
	slot := slotA
	if driveID == template.ManagedBDriveID {
		slot = slotB
	}
	if p.g.busy[p.id][slot] {
		return errors.New("replaced a drive the guest uses")
	}
	p.g.uuids[p.id][slot] = p.g.pathUUID[src]
	return nil
}

type swapFixture struct {
	*fixture
	g   *fakeGuest
	jd  string
	vms map[string]VM
}

func newSwapFixture(t *testing.T) *swapFixture {
	t.Helper()
	f := newFixture(t, 16)
	g := newFakeGuest()
	n := 0
	f.l.wrap = func(p *fakeProc) Process {
		n++
		return &guestProc{fakeProc: p, id: fmt.Sprintf("vm-%d", n), g: g}
	}
	jd := t.TempDir()
	f.m.UseJournal(&journal.Journal{Dir: jd})
	f.m.UseManagedGuest(g, 5*time.Second)
	sf := &swapFixture{fixture: f, g: g, jd: jd, vms: map[string]VM{}}
	for _, id := range []string{sb1, sb2} {
		vm, _, err := f.m.Create(context.Background(), req(id, 1))
		if err != nil {
			t.Fatal(err)
		}
		sf.vms[id] = vm
	}
	return sf
}

func (sf *swapFixture) image(name string) ManagedImage {
	img := ManagedImage{ID: strings.Repeat(name[:1], 64), Path: "/data/managed/" + name + ".ext4", Size: 16 << 20, UUID: "uuid-" + name}
	sf.g.pathUUID[img.Path] = img.UUID
	return img
}

func (sf *swapFixture) target(id string) SwapTarget {
	vm := sf.vms[id]
	return SwapTarget{SandboxID: id, Attempt: vm.Attempt, Generation: vm.Generation, Key: "the-key"}
}

func (sf *swapFixture) record(t *testing.T, id string) journal.Record {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(sf.jd, id+".json"))
	if err != nil {
		t.Fatal(err)
	}
	var r journal.Record
	if err := json.Unmarshal(raw, &r); err != nil {
		t.Fatal(err)
	}
	return r
}

func TestSwapManagedAlternatesSlots(t *testing.T) {
	sf := newSwapFixture(t)
	ctx := context.Background()
	if vm := sf.vms[sb1]; vm.Managed.Slots != 2 || vm.Managed.Active != slotA {
		t.Fatalf("new VM managed state %+v", vm.Managed)
	}
	if r := sf.record(t, sb1); r.Managed == nil || r.Managed.Slots != 2 || r.Managed.Active != "a" {
		t.Fatalf("journal after Create: %+v", r.Managed)
	}
	img1, img2 := sf.image("one"), sf.image("two")

	// Slot A has the placeholder; the first swap goes to slot B.
	res := sf.m.SwapManaged(ctx, img1, []SwapTarget{sf.target(sb1)})
	if len(res) != 1 || res[0].Err != nil || res[0].Active != slotB || !res[0].Changed {
		t.Fatalf("swap 1: %+v", res)
	}
	if got := strings.Join(sf.g.ops, ","); got != "status,replace managed_b /managed-b.ext4,mount b" {
		t.Fatalf("ops %s", got)
	}
	r := sf.record(t, sb1)
	if r.Managed.Active != "b" || r.Managed.B != img1.ID || r.Managed.A != "" || r.Managed.Pending != nil || r.State != journal.Running {
		t.Fatalf("journal after swap 1: %+v", r.Managed)
	}

	// The next swap goes back to slot A.
	sf.g.ops = nil
	res = sf.m.SwapManaged(ctx, img2, []SwapTarget{sf.target(sb1)})
	if res[0].Err != nil || res[0].Active != slotA {
		t.Fatalf("swap 2: %+v", res)
	}
	if got := strings.Join(sf.g.ops, ","); got != "status,replace managed /managed.ext4,mount a" {
		t.Fatalf("ops %s", got)
	}
	if r := sf.record(t, sb1); r.Managed.Active != "a" || r.Managed.A != img2.ID || r.Managed.B != img1.ID {
		t.Fatalf("journal after swap 2: %+v", r.Managed)
	}
	vm := sf.m.List()[0]
	if vm.Managed.Active != slotA || vm.Managed.A != img2.ID {
		t.Fatalf("List: %+v", vm.Managed)
	}
	if in := sf.m.ManagedImagesInUse(); !in[img1.ID] || !in[img2.ID] || len(in) != 2 {
		t.Fatalf("in use %v", in)
	}

	// The active image again: nothing changes.
	sf.g.ops = nil
	res = sf.m.SwapManaged(ctx, img2, []SwapTarget{sf.target(sb1)})
	if res[0].Err != nil || res[0].Changed || res[0].Active != slotA || strings.Join(sf.g.ops, ",") != "status" {
		t.Fatalf("repeat: %+v ops %v", res, sf.g.ops)
	}
}

// The journal names the pending swap before the drive changes, so a
// restarted agent knows the idle slot content is not the recorded one.
func TestSwapManagedJournalsBeforeTheDriveChanges(t *testing.T) {
	sf := newSwapFixture(t)
	img := sf.image("one")
	var during journal.Record
	sf.g.onReplace = func() { during = sf.record(t, sb1) }
	res := sf.m.SwapManaged(context.Background(), img, []SwapTarget{sf.target(sb1)})
	if res[0].Err != nil {
		t.Fatal(res[0].Err)
	}
	if p := during.Managed.Pending; p == nil || p.Slot != "b" || p.Image != img.ID || during.Managed.Active != "a" {
		t.Fatalf("record during the drive change: %+v", during.Managed)
	}
	if in := sf.m.ManagedImagesInUse(); !in[img.ID] {
		t.Fatal("image not in use")
	}
}

// A swap that the guest finished but the agent did not record (agent
// restart) is fixed from the guest's state.
func TestSwapManagedReconcilesFromTheGuest(t *testing.T) {
	sf := newSwapFixture(t)
	img := sf.image("one")
	sf.g.vm("vm-1")
	sf.g.active["vm-1"], sf.g.uuids["vm-1"][slotB], sf.g.busy["vm-1"][slotB] = slotB, img.UUID, true
	res := sf.m.SwapManaged(context.Background(), img, []SwapTarget{sf.target(sb1)})
	if res[0].Err != nil || res[0].Changed || res[0].Active != slotB {
		t.Fatalf("%+v", res)
	}
	if r := sf.record(t, sb1); r.Managed.Active != "b" || r.Managed.B != img.ID || r.Managed.Pending != nil {
		t.Fatalf("journal %+v", r.Managed)
	}
}

// A swap whose guest mount stopped before the old drive was detached left
// slot B busy with the new image, beneath slot A. A repeat skips the drive
// change and lets the guest finish the mount.
func TestSwapManagedResumesAnInterruptedMount(t *testing.T) {
	sf := newSwapFixture(t)
	img := sf.image("one")
	sf.g.vm("vm-1")
	sf.g.uuids["vm-1"][slotB], sf.g.busy["vm-1"][slotB] = img.UUID, true
	res := sf.m.SwapManaged(context.Background(), img, []SwapTarget{sf.target(sb1)})
	if res[0].Err != nil || res[0].Active != slotB || !res[0].Changed {
		t.Fatalf("%+v", res)
	}
	if got := strings.Join(sf.g.ops, ","); got != "status,mount b" {
		t.Fatalf("ops %s, want no drive change", got)
	}
	if r := sf.record(t, sb1); r.Managed.Active != "b" || r.Managed.B != img.ID || r.Managed.Pending != nil {
		t.Fatalf("journal %+v", r.Managed)
	}
}

func TestSwapManagedRefusals(t *testing.T) {
	sf := newSwapFixture(t)
	ctx := context.Background()
	img1, img2, img3 := sf.image("one"), sf.image("two"), sf.image("three")

	// A reader holds the old drive: the swap reports it, and the next swap
	// into that slot is refused without touching the drive.
	sf.g.keepReaders = true
	res := sf.m.SwapManaged(ctx, img1, []SwapTarget{sf.target(sb1)})
	if res[0].Err != nil || !res[0].PreviousInUse {
		t.Fatalf("%+v", res)
	}
	sf.g.ops = nil
	res = sf.m.SwapManaged(ctx, img2, []SwapTarget{sf.target(sb1)})
	wantReason(t, res[0].Err, pb.ErrorReason_MANAGED_SLOT_BUSY)
	if strings.Join(sf.g.ops, ",") != "status" {
		t.Fatalf("busy slot touched: %v", sf.g.ops)
	}
	// The reader closed its file.
	sf.g.busy["vm-1"][slotA] = false
	sf.g.keepReaders = false
	if res = sf.m.SwapManaged(ctx, img2, []SwapTarget{sf.target(sb1)}); res[0].Err != nil {
		t.Fatal(res[0].Err)
	}

	// One bad target does not stop the others; results keep the order.
	stale := sf.target(sb2)
	stale.Generation++
	res = sf.m.SwapManaged(ctx, img3, []SwapTarget{stale, sf.target(sb1),
		{SandboxID: "33333333-3333-4333-8333-333333333333", Attempt: 1, Generation: 1, Key: "the-key"}, {SandboxID: "bad"}})
	wantReason(t, res[0].Err, pb.ErrorReason_INSTANCE_MISMATCH)
	if res[1].Err != nil || res[1].SandboxID != sb1 {
		t.Fatalf("%+v", res[1])
	}
	wantReason(t, res[2].Err, pb.ErrorReason_SANDBOX_NOT_FOUND)
	wantReason(t, res[3].Err, pb.ErrorReason_INVALID_ARGUMENT)

	// A wrong key fails before any change.
	sf.g.ops = nil
	bad := sf.target(sb2)
	bad.Key = "other"
	res = sf.m.SwapManaged(ctx, img3, []SwapTarget{bad})
	wantReason(t, res[0].Err, pb.ErrorReason_GUEST_KEY_REJECTED)
	if len(sf.g.ops) != 0 {
		t.Fatalf("ops %v", sf.g.ops)
	}

	// A failed mount keeps the old drive active in the record.
	sf.g.failMount = apierr.New(pb.ErrorReason_MANAGED_MOUNT_FAILED, "EINVAL")
	res = sf.m.SwapManaged(ctx, img1, []SwapTarget{sf.target(sb2)})
	wantReason(t, res[0].Err, pb.ErrorReason_MANAGED_MOUNT_FAILED)
	if r := sf.record(t, sb2); r.Managed.Active != "a" || r.Managed.B != img1.ID || r.Managed.Pending == nil {
		t.Fatalf("journal after a failed mount: %+v", r.Managed)
	}
}

func TestSwapManagedNeedsSlotB(t *testing.T) {
	f := newFixture(t, 4)
	dir := t.TempDir()
	if _, err := template.WriteFakeLayout(dir, "old", template.Key{VCPUs: 2, MemMiB: 4096, ScratchGiB: 1, FirecrackerVersion: "v1.17.0"}, 2); err != nil {
		t.Fatal(err)
	}
	f.m.templates = &template.Store{Dir: dir}
	f.m.UseManagedGuest(newFakeGuest(), time.Second)
	r := req(sb1, 1)
	r.Template = "old"
	vm, _, err := f.m.Create(context.Background(), r)
	if err != nil {
		t.Fatalf("a layout 2 template must still restore: %v", err)
	}
	if vm.Managed.Slots != 1 {
		t.Fatalf("slots %d", vm.Managed.Slots)
	}
	res := f.m.SwapManaged(context.Background(), ManagedImage{ID: strings.Repeat("a", 64)},
		[]SwapTarget{{SandboxID: sb1, Attempt: vm.Attempt, Generation: vm.Generation, Key: "k"}})
	wantReason(t, res[0].Err, pb.ErrorReason_MANAGED_SWAP_UNSUPPORTED)
}

// Stop waits for a running swap, so the swap's journal write never lands
// after the tombstone.
func TestStopWaitsForSwap(t *testing.T) {
	sf := newSwapFixture(t)
	sf.g.mountGate = make(chan struct{})
	img := sf.image("one")
	swapped := make(chan []SwapResult)
	go func() { swapped <- sf.m.SwapManaged(context.Background(), img, []SwapTarget{sf.target(sb1)}) }()
	// Wait until the swap reached Mount (the drive is replaced).
	for {
		sf.g.mu.Lock()
		n := len(sf.g.ops)
		sf.g.mu.Unlock()
		if n == 2 {
			break
		}
		time.Sleep(time.Millisecond)
	}
	stopped := make(chan error)
	vm := sf.vms[sb1]
	go func() {
		_, err := sf.m.Stop(context.Background(), sb1, vm.Attempt, vm.Generation)
		stopped <- err
	}()
	select {
	case err := <-stopped:
		t.Fatalf("Stop returned during the swap: %v", err)
	case <-time.After(50 * time.Millisecond):
	}
	close(sf.g.mountGate)
	if res := <-swapped; res[0].Err != nil {
		t.Fatal(res[0].Err)
	}
	if err := <-stopped; err != nil {
		t.Fatal(err)
	}
	if r := sf.record(t, sb1); r.State != journal.Stopped {
		t.Fatalf("record %s, want stopped", r.State)
	}
}

func TestManagedRecordRoundTrip(t *testing.T) {
	if s := managedFromRecord(nil); s.Slots != 1 || s.Active != slotA {
		t.Fatalf("old record: %+v", s)
	}
	in := ManagedState{Slots: 2, Active: slotB, A: "x", B: "y", PendingSlot: slotA, PendingImage: "z"}
	if out := managedFromRecord(in.record()); out != in {
		t.Fatalf("round trip %+v", out)
	}
	if OtherSlot(slotA) != slotB || OtherSlot(slotB) != slotA || OtherSlot(pb.ManagedSlot_MANAGED_SLOT_UNSPECIFIED) != slotB {
		t.Fatal("OtherSlot")
	}
	if d, f := SlotDrive(slotB); d != "managed_b" || f != "managed-b.ext4" {
		t.Fatal(d, f)
	}
	if d, f := SlotDrive(slotA); d != "managed" || f != "managed.ext4" {
		t.Fatal(d, f)
	}
}
