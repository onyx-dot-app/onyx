package agent

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

type fakeProc struct {
	pid    int
	done   chan struct{}
	once   sync.Once
	killed atomic.Int32
	// failKills makes the next Kill calls fail after the process exits.
	failKills atomic.Int32
}

func (p *fakeProc) Info() ProcInfo        { return ProcInfo{PID: p.pid, PIDStart: uint64(p.pid) * 10} }
func (p *fakeProc) Done() <-chan struct{} { return p.done }
func (p *fakeProc) exit()                 { p.once.Do(func() { close(p.done) }) }
func (p *fakeProc) Kill(context.Context) error {
	p.killed.Add(1)
	p.exit()
	if p.failKills.Add(-1) >= 0 {
		return errors.New("remove chroot: device busy")
	}
	return nil
}

type fakeLauncher struct {
	mu       sync.Mutex
	launches int
	procs    map[string]*fakeProc
	specs    []LaunchSpec
	fail     error
	gate     chan struct{}
	// wrap, if set, wraps each new process (managed drive tests).
	wrap func(*fakeProc) Process
}

func (f *fakeLauncher) Launch(ctx context.Context, s LaunchSpec) (Process, error) {
	if f.gate != nil {
		select {
		case <-f.gate:
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.launches++
	f.specs = append(f.specs, s)
	if f.fail != nil {
		return nil, f.fail
	}
	p := &fakeProc{pid: 1000 + f.launches, done: make(chan struct{})}
	if f.procs == nil {
		f.procs = map[string]*fakeProc{}
	}
	f.procs[s.ID] = p
	if f.wrap != nil {
		return f.wrap(p), nil
	}
	return p, nil
}

func (f *fakeLauncher) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.launches
}

type fakeStats struct {
	availMiB uint64
	freeDisk uint64
	memErr   error
	diskErr  error
	// onDisk runs once, inside the next admission check (the disk check
	// runs before the Manager takes its lock).
	onDisk func()
	// onMem runs inside each memory read (under the Manager lock).
	onMem func()
}

func (s *fakeStats) MemInfo() (uint64, uint64, error) {
	if s.onMem != nil {
		s.onMem()
	}
	return 64 << 10, s.availMiB, s.memErr
}
func (s *fakeStats) DiskFreeBytes() (uint64, error) {
	if h := s.onDisk; h != nil {
		s.onDisk = nil
		h()
	}
	return s.freeDisk, s.diskErr
}

const (
	sb1 = "11111111-1111-4111-8111-111111111111"
	sb2 = "22222222-2222-4222-8222-222222222222"
)

type fixture struct {
	m     *Manager
	l     *fakeLauncher
	stats *fakeStats
	uids  *jailer.UIDPool
}

func newFixture(t *testing.T, uidCount uint32) *fixture {
	t.Helper()
	dir := t.TempDir()
	if _, err := template.WriteFake(dir, "tpl-1", template.Key{
		VCPUs: 2, MemMiB: 4096, ScratchGiB: 1, GuestKernel: "6.18.25", FirecrackerVersion: "v1.17.0",
	}); err != nil {
		t.Fatal(err)
	}
	uids, err := jailer.NewUIDPool(1000000, uidCount)
	if err != nil {
		t.Fatal(err)
	}
	l := &fakeLauncher{}
	stats := &fakeStats{availMiB: 32 << 10, freeDisk: 100 << 30}
	m := NewManager(Config{
		MinFreeMemMiB: 2048, MinFreeDiskBytes: 10 << 30, MaxScratchGiB: 64,
		StartTimeout: 5 * time.Second, StopTimeout: 5 * time.Second, TombstoneTTL: time.Hour,
	}, &template.Store{Dir: dir}, l, stats, uids, Versions{Firecracker: "v1.17.0"},
		slog.New(slog.NewTextHandler(io.Discard, nil)))
	return &fixture{m: m, l: l, stats: stats, uids: uids}
}

func req(id string, attempt uint64) CreateRequest {
	return CreateRequest{SandboxID: id, Attempt: attempt, Template: "tpl-1", VCPUs: 2, MemMiB: 4096, ScratchGiB: 4, TenantID: "public"}
}

func wantReason(t *testing.T, err error, want pb.ErrorReason) {
	t.Helper()
	if err == nil {
		t.Fatalf("got no error, want %s", want)
	}
	if got := apierr.ReasonOf(err); got != want {
		t.Fatalf("reason %s, want %s (%v)", got, want, err)
	}
}

func TestCreateIsIdempotentOnAttempt(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	vm, created, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil || !created {
		t.Fatalf("create: %v %v", created, err)
	}
	if vm.Generation == 0 || vm.State != pb.VMState_VM_STATE_RUNNING || vm.PID == 0 {
		t.Fatalf("bad VM %+v", vm)
	}
	if got := f.l.specs[0].ScratchBytes; got != 4<<30 {
		t.Fatalf("scratch bytes %d", got)
	}
	again, created, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil || created || again.Generation != vm.Generation || again.PID != vm.PID {
		t.Fatalf("repeat create: %+v created=%v err=%v", again, created, err)
	}
	if f.l.count() != 1 {
		t.Fatalf("launches %d, want 1", f.l.count())
	}
}

func TestConcurrentCreatesLaunchOnce(t *testing.T) {
	f := newFixture(t, 10)
	f.l.gate = make(chan struct{})
	var wg sync.WaitGroup
	gens := make([]uint64, 8)
	errs := make([]error, 8)
	for i := range gens {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			vm, _, err := f.m.Create(context.Background(), req(sb1, 1))
			gens[i], errs[i] = vm.Generation, err
		}(i)
	}
	time.Sleep(20 * time.Millisecond)
	close(f.l.gate)
	wg.Wait()
	for i := range gens {
		if errs[i] != nil || gens[i] != gens[0] {
			t.Fatalf("create %d: gen %d err %v (want gen %d)", i, gens[i], errs[i], gens[0])
		}
	}
	if f.l.count() != 1 {
		t.Fatalf("launches %d, want 1", f.l.count())
	}
}

func TestNewAttemptWhileRunningConflicts(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	if _, _, err := f.m.Create(ctx, req(sb1, 1)); err != nil {
		t.Fatal(err)
	}
	_, _, err := f.m.Create(ctx, req(sb1, 2))
	wantReason(t, err, pb.ErrorReason_ATTEMPT_CONFLICT)
	_, _, err = f.m.Create(ctx, req(sb1, 0))
	wantReason(t, err, pb.ErrorReason_INVALID_ARGUMENT)
}

func TestStopPreconditions(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	_, err = f.m.Stop(ctx, sb1, 1, vm.Generation+1)
	wantReason(t, err, pb.ErrorReason_INSTANCE_MISMATCH)
	_, err = f.m.Stop(ctx, sb1, 2, vm.Generation)
	wantReason(t, err, pb.ErrorReason_INSTANCE_MISMATCH)
	_, err = f.m.Stop(ctx, sb2, 1, 1)
	wantReason(t, err, pb.ErrorReason_SANDBOX_NOT_FOUND)
	if f.l.procs[sb1].killed.Load() != 0 {
		t.Fatal("a rejected Stop killed the VM")
	}

	res, err := f.m.Stop(ctx, sb1, 1, vm.Generation)
	if err != nil || res.AlreadyStopped {
		t.Fatalf("stop: %+v %v", res, err)
	}
	if f.l.procs[sb1].killed.Load() != 1 || f.uids.InUse() != 0 {
		t.Fatalf("kill count %d, uids in use %d", f.l.procs[sb1].killed.Load(), f.uids.InUse())
	}
	res, err = f.m.Stop(ctx, sb1, 1, vm.Generation)
	if err != nil || !res.AlreadyStopped {
		t.Fatalf("repeat stop: %+v %v", res, err)
	}
	_, err = f.m.Stop(ctx, sb1, 1, vm.Generation+5)
	wantReason(t, err, pb.ErrorReason_INSTANCE_MISMATCH)

	_, _, err = f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_STALE_ATTEMPT)
	next, created, err := f.m.Create(ctx, req(sb1, 2))
	if err != nil || !created || next.Generation <= vm.Generation {
		t.Fatalf("create attempt 2: %+v %v %v", next, created, err)
	}
}

func TestAdmissionErrors(t *testing.T) {
	f := newFixture(t, 1)
	ctx := context.Background()
	cases := []struct {
		name string
		mod  func(*CreateRequest)
		want pb.ErrorReason
	}{
		{"bad sandbox id", func(r *CreateRequest) { r.SandboxID = "../etc" }, pb.ErrorReason_INVALID_ARGUMENT},
		{"uppercase sandbox id", func(r *CreateRequest) { r.SandboxID = "AAAAAAAA-1111-4111-8111-111111111111" }, pb.ErrorReason_INVALID_ARGUMENT},
		{"bad template name", func(r *CreateRequest) { r.Template = "../x" }, pb.ErrorReason_INVALID_ARGUMENT},
		{"missing template", func(r *CreateRequest) { r.Template = "nope" }, pb.ErrorReason_TEMPLATE_MISSING},
		{"vcpus", func(r *CreateRequest) { r.VCPUs = 4 }, pb.ErrorReason_TEMPLATE_SHAPE_MISMATCH},
		{"memory", func(r *CreateRequest) { r.MemMiB = 8192 }, pb.ErrorReason_TEMPLATE_SHAPE_MISMATCH},
		{"scratch too small", func(r *CreateRequest) { r.ScratchGiB = 0 }, pb.ErrorReason_SCRATCH_TOO_SMALL},
		{"scratch too large", func(r *CreateRequest) { r.ScratchGiB = 65 }, pb.ErrorReason_SCRATCH_TOO_LARGE},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r := req(sb1, 1)
			c.mod(&r)
			_, _, err := f.m.Create(ctx, r)
			wantReason(t, err, c.want)
		})
	}

	f.stats.availMiB = 4096 + 2047
	_, _, err := f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_MEMORY)
	f.stats.availMiB = 32 << 10

	f.stats.freeDisk = 9 << 30
	_, _, err = f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_DISK)
	f.stats.freeDisk = 100 << 30

	if _, _, err := f.m.Create(ctx, req(sb1, 1)); err != nil {
		t.Fatal(err)
	}
	_, _, err = f.m.Create(ctx, req(sb2, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	if f.l.count() != 1 {
		t.Fatalf("launches %d, want 1", f.l.count())
	}
}

func TestTemplateFirecrackerVersion(t *testing.T) {
	f := newFixture(t, 10)
	f.m.versions.Firecracker = "v1.18.0"
	_, _, err := f.m.Create(context.Background(), req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_TEMPLATE_INCOMPATIBLE)
}

// Firecracker checks nothing on a snapshot load, so Create refuses a template
// whose key does not fit the node, or whose files changed, before it launches.
func TestTemplateCheckedBeforeEveryRestore(t *testing.T) {
	ctx := context.Background()
	for name, change := range map[string]func(f *fixture){
		"cpu model":    func(f *fixture) { f.m.versions.CPUModel = "Other CPU" },
		"host kernel":  func(f *fixture) { f.m.versions.HostKernel = "6.19.0" },
		"guest kernel": func(f *fixture) { f.m.versions.GuestKernelSHA256 = strings.Repeat("a", 64) },
		"egress CA":    func(f *fixture) { f.m.versions.EgressCAFingerprint = strings.Repeat("b", 64) },
		"tampered mem": func(f *fixture) {
			p := filepath.Join(f.m.templates.Dir, "tpl-1", template.MemFile)
			if err := os.WriteFile(p, []byte("not the snapshot"), 0o644); err != nil {
				t.Fatal(err)
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			f := newFixture(t, 10)
			// A first Create caches the verified file state.
			if _, _, err := f.m.Create(ctx, req(sb1, 1)); err != nil {
				t.Fatal(err)
			}
			change(f)
			_, _, err := f.m.Create(ctx, req(sb2, 1))
			wantReason(t, err, pb.ErrorReason_TEMPLATE_INCOMPATIBLE)
			if f.l.count() != 1 {
				t.Fatalf("launches %d, want 1 (the refused Create must not launch)", f.l.count())
			}
		})
	}
}

func TestBuildSlotChecksMemory(t *testing.T) {
	f := newFixture(t, 10)
	f.m.cfg.MinFreeMemMiB = 512
	f.stats.availMiB = 4096 + 511
	_, _, err := f.m.BuildSlot("tpl-abc", 4096)
	wantReason(t, err, pb.ErrorReason_CAPACITY_MEMORY)
	f.stats.availMiB = 4096 + 512
	_, done, err := f.m.BuildSlot("tpl-abc", 4096)
	if err != nil {
		t.Fatal(err)
	}
	done(false)
}

func TestTemplatesInUseAndBuildSlot(t *testing.T) {
	f := newFixture(t, 2)
	ctx := context.Background()
	if _, _, err := f.m.Create(ctx, req(sb1, 1)); err != nil {
		t.Fatal(err)
	}
	if in := f.m.TemplatesInUse(); !in["tpl-1"] || len(in) != 1 {
		t.Fatalf("in use %v", in)
	}
	uid, done, err := f.m.BuildSlot("tpl-abc", 1024)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := f.m.BuildSlot("tpl-abc", 1024); err == nil {
		t.Fatal("second build slot for the same id")
	}
	// The pool has 2 UIDs: one VM and one build.
	_, _, err = f.m.Create(ctx, req(sb2, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	done(false)
	if !f.uids.Reserve(uid) {
		t.Fatalf("build UID %d was not freed", uid)
	}
	f.uids.Put(uid)
	_, done2, err := f.m.BuildSlot("tpl-def", 1024)
	if err != nil {
		t.Fatal(err)
	}
	done2(true) // the build VM may still run: its UID stays reserved
	_, _, err = f.m.Create(ctx, req(sb2, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	// The build VM is in doubt until a scan finds no process for it.
	table := &fakeTable{cands: []Candidate{{ID: "tpl-def", PID: 700, UID: uid}}}
	f.m.adopter = table
	_, _, err = f.m.BuildSlot("tpl-def", 1024)
	wantReason(t, err, pb.ErrorReason_SANDBOX_IN_DOUBT)
	table.set(nil, nil)
	_, done3, err := f.m.BuildSlot("tpl-def", 1024)
	if err != nil {
		t.Fatalf("build slot after the doubt cleared: %v", err)
	}
	done3(false)
	if got := table.removedIDs(); len(got) != 1 || got[0] != "tpl-def" {
		t.Fatalf("removed %v, want the build VM chroot", got)
	}
	if _, _, err := f.m.Create(ctx, req(sb2, 1)); err != nil {
		t.Fatalf("create after the build UID was freed: %v", err)
	}
}

func TestCreatePinsItsTemplateAgainstGC(t *testing.T) {
	f := newFixture(t, 2)
	var removed []string
	var gcErr error
	// GC runs while Create is in admission, before its VM is in the table.
	f.stats.onDisk = func() {
		removed, gcErr = f.m.templates.GC(0, f.m.TemplatesInUse)
	}
	if _, _, err := f.m.Create(context.Background(), req(sb1, 1)); err != nil {
		t.Fatal(err)
	}
	if gcErr != nil || len(removed) != 0 {
		t.Fatalf("GC during admission removed %v %v", removed, gcErr)
	}
	// After Create the VM is in the table, so GC still keeps the template.
	removed, gcErr = f.m.templates.GC(0, f.m.TemplatesInUse)
	if gcErr != nil || len(removed) != 0 {
		t.Fatalf("GC after create removed %v %v", removed, gcErr)
	}
}

func TestLaunchFailureReleasesSlot(t *testing.T) {
	f := newFixture(t, 1)
	ctx := context.Background()
	f.l.fail = errors.New("jailer exited 1")
	_, _, err := f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_VMM_FAILED)
	if f.uids.InUse() != 0 || len(f.m.List()) != 0 {
		t.Fatalf("failed create left state: uids %d vms %d", f.uids.InUse(), len(f.m.List()))
	}
	f.l.fail = nil
	if _, created, err := f.m.Create(ctx, req(sb1, 1)); err != nil || !created {
		t.Fatalf("retry: %v %v", created, err)
	}
}

func TestLaunchThatLeftAVMKeepsItsUID(t *testing.T) {
	f := newFixture(t, 2)
	f.l.fail = fmt.Errorf("pidfd_open: too many open files (cleanup: scope busy): %w", ErrVMLeft)
	_, _, err := f.m.Create(context.Background(), req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_SANDBOX_IN_DOUBT)
	if f.uids.InUse() != 1 || len(f.m.List()) != 0 {
		t.Fatalf("uids in use %d (want 1), vms %d", f.uids.InUse(), len(f.m.List()))
	}
}

func TestUnreadableNodeStatsRefuseCreate(t *testing.T) {
	f := newFixture(t, 2)
	ctx := context.Background()
	f.stats.memErr = errors.New("no /proc/meminfo")
	_, _, err := f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_MEMORY)
	f.stats.memErr = nil
	f.stats.diskErr = errors.New("statfs failed")
	_, _, err = f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_DISK)
	if f.l.count() != 0 || f.uids.InUse() != 0 {
		t.Fatalf("launches %d, uids %d", f.l.count(), f.uids.InUse())
	}
}

func TestCreateRechecksStoppedAttemptAfterAdmission(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	// While attempt 1 is in admission, attempt 2 starts and stops.
	f.stats.onDisk = func() {
		vm, _, err := f.m.Create(ctx, req(sb1, 2))
		if err != nil {
			t.Error(err)
			return
		}
		if _, err := f.m.Stop(ctx, sb1, 2, vm.Generation); err != nil {
			t.Error(err)
		}
	}
	_, _, err := f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_STALE_ATTEMPT)
	if f.l.count() != 1 || len(f.m.List()) != 0 {
		t.Fatalf("launches %d (want 1), vms %d", f.l.count(), len(f.m.List()))
	}
}

func TestStopRetriesFailedCleanup(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	p := f.l.procs[sb1]
	p.failKills.Store(1)
	_, err = f.m.Stop(ctx, sb1, 1, vm.Generation)
	wantReason(t, err, pb.ErrorReason_VMM_FAILED)
	// The process is gone but its files are not: EXITED, UID kept.
	if l := f.m.List(); len(l) != 1 || l[0].State != pb.VMState_VM_STATE_EXITED || f.uids.InUse() != 1 {
		t.Fatalf("after a failed stop: %+v, uids %d", l, f.uids.InUse())
	}
	_, _, err = f.m.Create(ctx, req(sb1, 2))
	wantReason(t, err, pb.ErrorReason_VMM_FAILED)
	res, err := f.m.Stop(ctx, sb1, 1, vm.Generation)
	if err != nil || !res.AlreadyStopped || len(f.m.List()) != 0 || f.uids.InUse() != 0 || p.killed.Load() != 2 {
		t.Fatalf("retry: %+v %v vms=%d uids=%d kills=%d", res, err, len(f.m.List()), f.uids.InUse(), p.killed.Load())
	}
}

func TestExitedVM(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	f.l.procs[sb1].exit()
	waitState(t, f.m, sb1, pb.VMState_VM_STATE_EXITED)

	again, created, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil || created || again.State != pb.VMState_VM_STATE_EXITED {
		t.Fatalf("same attempt after exit: %+v %v %v", again, created, err)
	}
	info, err := f.m.NodeInfo()
	if err != nil || info.VMCount != 0 || len(info.Templates) != 1 {
		t.Fatalf("node info: %+v %v", info, err)
	}
	next, created, err := f.m.Create(ctx, req(sb1, 2))
	if err != nil || !created || next.Generation <= vm.Generation {
		t.Fatalf("new attempt after exit: %+v %v %v", next, created, err)
	}
	if f.uids.InUse() != 1 {
		t.Fatalf("uids in use %d, want 1", f.uids.InUse())
	}
	// Stop of the exited instance now names a replaced VM.
	_, err = f.m.Stop(ctx, sb1, 1, vm.Generation)
	wantReason(t, err, pb.ErrorReason_INSTANCE_MISMATCH)
}

func TestStopOfExitedVM(t *testing.T) {
	f := newFixture(t, 10)
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	f.l.procs[sb1].exit()
	waitState(t, f.m, sb1, pb.VMState_VM_STATE_EXITED)
	res, err := f.m.Stop(ctx, sb1, 1, vm.Generation)
	if err != nil || !res.AlreadyStopped || len(f.m.List()) != 0 || f.uids.InUse() != 0 {
		t.Fatalf("stop exited: %+v %v vms=%d uids=%d", res, err, len(f.m.List()), f.uids.InUse())
	}
}

func TestGenerationIncreases(t *testing.T) {
	f := newFixture(t, 10)
	fixed := time.Unix(1000, 0)
	f.m.now = func() time.Time { return fixed }
	a := f.m.nextGeneration()
	b := f.m.nextGeneration()
	if b <= a {
		t.Fatalf("generation did not increase: %d then %d", a, b)
	}
}

func waitState(t *testing.T, m *Manager, id string, want pb.VMState) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		for _, vm := range m.List() {
			if vm.SandboxID == id && vm.State == want {
				// Let the exit cleanup finish.
				m.mu.Lock()
				e := m.vms[id]
				var busy chan struct{}
				if e != nil {
					busy = e.busy
				}
				m.mu.Unlock()
				if busy != nil {
					<-busy
				}
				return
			}
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("VM %s did not reach %s", id, want)
}
