package agent

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc/codes"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/nodewatch"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

const sb3 = "33333333-3333-4333-8333-333333333333"

// errorInfo returns the ErrorInfo metadata that a client gets for err.
func errorInfo(t *testing.T, err error) (codes.Code, map[string]string) {
	t.Helper()
	st := apierr.Status(err)
	for _, d := range st.Details() {
		if info, ok := d.(*errdetails.ErrorInfo); ok {
			return st.Code(), info.GetMetadata()
		}
	}
	t.Fatalf("no ErrorInfo in %v", st)
	return 0, nil
}

// The memory check uses measured MemAvailable and the real numbers go to
// the client.
func TestMemoryAdmissionNumbers(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	// Reserve 2048 + VM 4096: one MiB short.
	f.stats.availMiB = 4096 + 2048 - 1
	_, _, err := f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_MEMORY)
	code, md := errorInfo(t, err)
	want := map[string]string{
		"mem_total_mib": "65536", "mem_available_mib": "6143", "mem_needed_mib": "6144", "vm_mem_mib": "4096",
		"mem_starting_mib": "0", "mem_reserve_mib": "2048",
	}
	if code != codes.ResourceExhausted || !mapsEqual(md, want) {
		t.Fatalf("code %v metadata %v", code, md)
	}
	if !strings.Contains(err.Error(), "6143 MiB available") || !strings.Contains(err.Error(), "2048 MiB reserve") {
		t.Errorf("message %q", err)
	}
	if f.l.count() != 0 {
		t.Fatal("a refused VM was launched")
	}
	// Exactly enough.
	f.stats.availMiB = 4096 + 2048
	if _, _, err := f.m.Create(ctx, req(sb1, 1)); err != nil {
		t.Fatal(err)
	}
	// A running VM is in MemAvailable already (as much as it uses), so the
	// next VM sees the same reading and is admitted: admission is on
	// measured memory, not on the sum of guest sizes.
	if _, _, err := f.m.Create(ctx, req(sb2, 1)); err != nil {
		t.Fatalf("second VM on measured memory: %v", err)
	}
	ni, err := f.m.NodeInfo()
	if err != nil || ni.MemReserveMiB != 2048 || ni.MemStartingMiB != 0 || ni.VMCount != 2 {
		t.Fatalf("node info %+v %v", ni, err)
	}
}

// VMs that are starting have not used their memory yet, so the check
// counts their guest size. Two concurrent Creates cannot both take the same
// free memory.
func TestMemoryAdmissionCountsStartingVMs(t *testing.T) {
	f := newFixture(t, 10)
	f.l.gate = make(chan struct{})
	ctx := context.Background()
	// Room for one VM plus the reserve, not for two.
	f.stats.availMiB = 2*4096 + 2048 - 1
	done := make(chan error, 1)
	go func() {
		_, _, err := f.m.Create(ctx, req(sb1, 1))
		done <- err
	}()
	waitStarting(t, f.m, sb1)

	_, _, err := f.m.Create(ctx, req(sb2, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_MEMORY)
	if _, md := errorInfo(t, err); md["mem_starting_mib"] != "4096" || md["mem_needed_mib"] != "10240" {
		t.Fatalf("metadata %v", md)
	}
	ni, err := f.m.NodeInfo()
	if err != nil || ni.MemStartingMiB != 4096 {
		t.Fatalf("node info %+v %v", ni, err)
	}
	// One more MiB and both fit.
	f.stats.availMiB++
	go func() {
		_, _, err := f.m.Create(ctx, req(sb2, 1))
		done <- err
	}()
	waitStarting(t, f.m, sb2)
	close(f.l.gate)
	for range 2 {
		if err := <-done; err != nil {
			t.Fatal(err)
		}
	}
	// Both run: nothing is starting.
	if ni, _ := f.m.NodeInfo(); ni.MemStartingMiB != 0 {
		t.Fatalf("starting %d after start", ni.MemStartingMiB)
	}
}

// A template build VM is admitted like a Create and counts as starting
// until it is done.
func TestMemoryAdmissionCountsBuildVM(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	f.stats.availMiB = 2*4096 + 2048 - 1
	_, done, err := f.m.BuildSlot("tpl-abc", 4096)
	if err != nil {
		t.Fatal(err)
	}
	_, _, err = f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_MEMORY)
	if _, md := errorInfo(t, err); md["mem_starting_mib"] != "4096" {
		t.Fatalf("metadata %v", md)
	}
	if _, _, err := f.m.BuildSlot("tpl-def", 4096); err == nil {
		t.Fatal("a second build fit in the memory of one")
	}
	done(false)
	if _, _, err := f.m.Create(ctx, req(sb1, 1)); err != nil {
		t.Fatalf("create after the build: %v", err)
	}
}

// The memory reading happens under the lock: a Create that reads memory
// while another Create holds it sees that VM as starting.
func TestMemoryReadUnderLock(t *testing.T) {
	f := newFixture(t, 10)
	f.stats.availMiB = 2*4096 + 2048 - 1
	ctx := context.Background()
	reads := 0
	f.stats.onMem = func() { reads++ }
	if _, _, err := f.m.Create(ctx, req(sb1, 1)); err != nil {
		t.Fatal(err)
	}
	if reads != 1 {
		t.Fatalf("%d memory reads per Create, want 1", reads)
	}
	// A repeat Create of the running VM does not read memory.
	if _, created, err := f.m.Create(ctx, req(sb1, 1)); err != nil || created || reads != 1 {
		t.Fatalf("repeat: created %v err %v reads %d", created, err, reads)
	}
}

// waitStarting waits until the VM is in the table as starting (its launch
// blocks on the gate).
func waitStarting(t *testing.T, m *Manager, id string) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		for _, vm := range m.List() {
			if vm.SandboxID == id && vm.State == pb.VMState_VM_STATE_STARTING {
				return
			}
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("VM %s is not starting", id)
}

func mapsEqual(a, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if b[k] != v {
			return false
		}
	}
	return true
}

type fakeNode struct {
	node nodewatch.Node
	err  error
}

func (f *fakeNode) Node(context.Context) (nodewatch.Node, error) { return f.node, f.err }

var cordon = nodewatch.Taint{Key: "node.kubernetes.io/unschedulable", Effect: "NoSchedule"}

// Drain state transitions with a fake node watcher.
func TestDrainTransitions(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	clock := time.Date(2026, 11, 9, 12, 0, 0, 0, time.UTC)
	f.m.now = func() time.Time { return clock }
	node := &fakeNode{}
	w := &nodewatch.Watcher{Source: node, Keys: nodewatch.DefaultTaintKeys, Interval: time.Second, Apply: f.m.SetNodeDrain}
	state := func(want pb.DrainState) DrainStatus {
		t.Helper()
		ni, err := f.m.NodeInfo()
		if err != nil {
			t.Fatal(err)
		}
		if ni.Drain.State != want {
			t.Fatalf("drain %+v, want %s", ni.Drain, want)
		}
		return ni.Drain
	}

	w.Once(ctx)
	if s := state(pb.DrainState_DRAIN_STATE_ACTIVE); !s.Since.IsZero() || s.Manual || len(s.Taints) != 0 {
		t.Fatalf("active: %+v", s)
	}
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}

	// kubectl drain: the cordon taint. The node refuses new VMs and keeps
	// the running one.
	node.node = nodewatch.Node{Taints: []nodewatch.Taint{cordon, {Key: "workload", Value: "sandbox", Effect: "NoSchedule"}}}
	w.Once(ctx)
	s := state(pb.DrainState_DRAIN_STATE_DRAINING)
	if !slices.Equal(s.Taints, []string{"node.kubernetes.io/unschedulable=:NoSchedule"}) || !s.Since.Equal(clock) || s.Manual {
		t.Fatalf("draining: %+v", s)
	}
	_, _, err = f.m.Create(ctx, req(sb2, 1))
	wantReason(t, err, pb.ErrorReason_NODE_DRAINING)
	if code, md := errorInfo(t, err); code != codes.FailedPrecondition || md["taints"] != "node.kubernetes.io/unschedulable=:NoSchedule" || md["manual"] != "false" {
		t.Fatalf("refusal %v %v", code, md)
	}
	// A repeat Create of the running VM still returns it.
	if got, created, err := f.m.Create(ctx, req(sb1, 1)); err != nil || created || got.Generation != vm.Generation {
		t.Fatalf("repeat create while draining: %v %v %v", got, created, err)
	}
	if f.l.count() != 1 {
		t.Fatalf("launches %d", f.l.count())
	}

	// The api_server saves and stops the VM: drained.
	clock = clock.Add(time.Minute)
	if _, err := f.m.Stop(ctx, sb1, 1, vm.Generation); err != nil {
		t.Fatal(err)
	}
	s = state(pb.DrainState_DRAIN_STATE_DRAINED)
	if !s.Since.Equal(clock.Add(-time.Minute)) {
		t.Fatalf("since moved: %+v", s)
	}

	// A failed node read keeps the last taints.
	node.err = errors.New("HTTP 403")
	w.Once(ctx)
	if s := state(pb.DrainState_DRAIN_STATE_DRAINED); s.WatchError == "" || len(s.Taints) != 1 {
		t.Fatalf("read error: %+v", s)
	}

	// Uncordon: active again, Create works.
	node.err, node.node = nil, nodewatch.Node{}
	w.Once(ctx)
	if s := state(pb.DrainState_DRAIN_STATE_ACTIVE); s.WatchError != "" || !s.Since.IsZero() {
		t.Fatalf("after uncordon: %+v", s)
	}
	if _, _, err := f.m.Create(ctx, req(sb2, 1)); err != nil {
		t.Fatal(err)
	}
}

// The manual flag drains alone, survives an agent restart, and clearing it
// does not end a drain that a taint causes.
func TestManualDrain(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "drain.json")
	if err := f.m.UseDrainFile(path); err != nil {
		t.Fatal(err)
	}
	s, err := f.m.SetDrain(true)
	if err != nil || s.State != pb.DrainState_DRAIN_STATE_DRAINED || !s.Manual || s.Since.IsZero() {
		t.Fatalf("set: %+v %v", s, err)
	}
	_, _, err = f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_NODE_DRAINING)
	if !strings.Contains(err.Error(), "manual drain flag") {
		t.Errorf("message %q", err)
	}

	// A new agent process reads the flag.
	f2 := newFixture(t, 10)
	if err := f2.m.UseDrainFile(path); err != nil {
		t.Fatal(err)
	}
	if d := f2.m.Drain(); !d.Manual || d.State != pb.DrainState_DRAIN_STATE_DRAINED || !d.Since.Equal(s.Since) {
		t.Fatalf("after restart: %+v (since %v)", d, s.Since)
	}
	_, _, err = f2.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_NODE_DRAINING)

	// Taint and manual flag: clearing the flag keeps the drain.
	f2.m.SetNodeDrain([]string{"node.kubernetes.io/unschedulable=:NoSchedule"}, nil)
	if d, err := f2.m.SetDrain(false); err != nil || d.State != pb.DrainState_DRAIN_STATE_DRAINED || d.Manual {
		t.Fatalf("clear with taint: %+v %v", d, err)
	}
	f2.m.SetNodeDrain(nil, nil)
	if d := f2.m.Drain(); d.State != pb.DrainState_DRAIN_STATE_ACTIVE {
		t.Fatalf("no taint, no flag: %+v", d)
	}
	if _, _, err := f2.m.Create(ctx, req(sb3, 1)); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil || !strings.Contains(string(raw), `"manual":false`) {
		t.Fatalf("drain file %s %v", raw, err)
	}

	// A flag that cannot be saved is not applied.
	f3 := newFixture(t, 10)
	if err := f3.m.UseDrainFile(filepath.Join(t.TempDir(), "file", "drain.json")); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(filepath.Dir(filepath.Dir(f3.m.drain.path)), "file"), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := f3.m.SetDrain(true); err == nil || f3.m.Drain().Manual {
		t.Fatalf("unsaved flag applied: %v", err)
	}
}

// A Firecracker process that the agent keeps in doubt holds the drain
// until a scan finds it gone. So does a scan that never worked.
func TestDrainWaitsForDoubtfulProcesses(t *testing.T) {
	f := newFixture(t, 10)
	if _, err := f.m.SetDrain(true); err != nil {
		t.Fatal(err)
	}
	table := &fakeTable{cands: []Candidate{{ID: sb1, PID: 900, UID: 1000005}}}
	f.m.mu.Lock()
	f.m.adopter = table
	f.m.doubt[sb1] = &doubt{reason: "a failed start may have left its VM running"}
	f.m.mu.Unlock()
	if d := f.m.Drain(); d.State != pb.DrainState_DRAIN_STATE_DRAINING {
		t.Fatalf("doubt with a live process: %+v", d)
	}
	if n, err := f.m.NodeInfo(); err != nil || n.Drain.State != pb.DrainState_DRAIN_STATE_DRAINING {
		t.Fatalf("node info: %+v %v", n.Drain, err)
	}
	// The scan fails: the doubt stays and so does the drain.
	table.set(nil, errors.New("read /proc: permission denied"))
	if d := f.m.Drain(); d.State != pb.DrainState_DRAIN_STATE_DRAINING {
		t.Fatalf("failed scan: %+v", d)
	}
	// The process is gone: the doubt clears and the drain ends.
	table.set(nil, nil)
	if d := f.m.Drain(); d.State != pb.DrainState_DRAIN_STATE_DRAINED {
		t.Fatalf("doubt cleared: %+v", d)
	}
	// After a restart whose scan failed, the processes are unknown.
	f.m.mu.Lock()
	f.m.needScan = true
	f.m.mu.Unlock()
	table.set(nil, errors.New("read /proc: permission denied"))
	if d := f.m.Drain(); d.State != pb.DrainState_DRAIN_STATE_DRAINING {
		t.Fatalf("unknown processes: %+v", d)
	}
	table.set(nil, nil)
	if d := f.m.Drain(); d.State != pb.DrainState_DRAIN_STATE_DRAINED {
		t.Fatalf("scan works again: %+v", d)
	}
}

// A drain that starts while a Create is in admission stops that Create.
func TestDrainDuringAdmission(t *testing.T) {
	f := newFixture(t, 10)
	f.stats.onDisk = func() { f.m.SetNodeDrain([]string{"node.kubernetes.io/unschedulable=:NoSchedule"}, nil) }
	_, _, err := f.m.Create(context.Background(), req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_NODE_DRAINING)
	if f.l.count() != 0 || len(f.m.List()) != 0 {
		t.Fatalf("launches %d vms %d", f.l.count(), len(f.m.List()))
	}
}

// A draining node refuses a template build VM and keeps its UIDs.
func TestDrainRefusesBuildVM(t *testing.T) {
	f := newFixture(t, 1)
	if _, err := f.m.SetDrain(true); err != nil {
		t.Fatal(err)
	}
	_, _, err := f.m.BuildSlot("tpl-abc", 1024)
	wantReason(t, err, pb.ErrorReason_NODE_DRAINING)
	if d := f.m.Drain(); d.State != pb.DrainState_DRAIN_STATE_DRAINED {
		t.Fatalf("refused build holds the drain: %+v", d)
	}
	f.m.SetNodeDrain([]string{"node.kubernetes.io/unschedulable=:NoSchedule"}, nil)
	if _, err := f.m.SetDrain(false); err != nil {
		t.Fatal(err)
	}
	_, _, err = f.m.BuildSlot("tpl-abc", 1024)
	wantReason(t, err, pb.ErrorReason_NODE_DRAINING)
	f.m.SetNodeDrain(nil, nil)
	// The one UID of the pool was not taken by the refusals.
	_, done, err := f.m.BuildSlot("tpl-abc", 1024)
	if err != nil {
		t.Fatalf("build after the drain: %v", err)
	}
	done(false)
}

// A build VM that started before the drain holds it in DRAINING until the
// build is done.
func TestDrainWaitsForBuildVM(t *testing.T) {
	f := newFixture(t, 10)
	_, done, err := f.m.BuildSlot("tpl-abc", 1024)
	if err != nil {
		t.Fatal(err)
	}
	if d, err := f.m.SetDrain(true); err != nil || d.State != pb.DrainState_DRAIN_STATE_DRAINING {
		t.Fatalf("drain with a build VM: %+v %v", d, err)
	}
	if n, err := f.m.NodeInfo(); err != nil || n.Drain.State != pb.DrainState_DRAIN_STATE_DRAINING {
		t.Fatalf("node info: %+v %v", n.Drain, err)
	}
	_, _, err = f.m.BuildSlot("tpl-def", 1024)
	wantReason(t, err, pb.ErrorReason_NODE_DRAINING)
	done(false)
	if d := f.m.Drain(); d.State != pb.DrainState_DRAIN_STATE_DRAINED {
		t.Fatalf("build done: %+v", d)
	}
}

func TestCreateReportsAdmission(t *testing.T) {
	f := newFixture(t, 10)
	create := func(r CreateRequest) (bool, error) {
		ctx, admitted := WithAdmission(context.Background())
		_, _, err := f.m.Create(ctx, r)
		return admitted(), err
	}

	if ok, err := create(req(sb1, 1)); err != nil || !ok {
		t.Fatalf("created: admitted %v, err %v", ok, err)
	}
	if ok, err := create(req(sb1, 1)); err != nil || !ok {
		t.Fatalf("existing: admitted %v, err %v", ok, err)
	}

	// VMM_FAILED from an old attempt's cleanup comes before admission.
	vm := f.m.List()[0]
	f.l.procs[sb1].failKills.Store(1)
	_, err := f.m.Stop(context.Background(), sb1, 1, vm.Generation)
	wantReason(t, err, pb.ErrorReason_VMM_FAILED)
	ok, err := create(req(sb1, 2))
	wantReason(t, err, pb.ErrorReason_VMM_FAILED)
	if ok {
		t.Fatal("cleanup failure counted as admitted")
	}

	f.stats.availMiB = 1024
	ok, err = create(req(sb2, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_MEMORY)
	if ok {
		t.Fatal("capacity refusal counted as admitted")
	}

	// A launch failure comes after admission.
	f.stats.availMiB = 32 << 10
	f.l.fail = errors.New("boom")
	ok, err = create(req(sb2, 1))
	wantReason(t, err, pb.ErrorReason_VMM_FAILED)
	if !ok {
		t.Fatal("launch failure not counted as admitted")
	}
}
