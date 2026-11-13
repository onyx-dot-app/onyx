package agent

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// fakeTable is a fake process table and VM layout.
type fakeTable struct {
	mu      sync.Mutex
	adopt   map[string]error // per sandbox: nil (alive), ErrGone, ErrAPINotResponding, other
	cands   []Candidate
	scanErr error
	removed []Candidate
}

func (f *fakeTable) Adopt(_ context.Context, r journal.Record) (Process, error) {
	err, ok := f.adopt[r.SandboxID]
	if !ok {
		return nil, ErrGone
	}
	if err == nil || errors.Is(err, ErrAPINotResponding) {
		return &fakeProc{pid: r.PID, done: make(chan struct{})}, err
	}
	return nil, err
}

func (f *fakeTable) Scan() ([]Candidate, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]Candidate(nil), f.cands...), f.scanErr
}

func (f *fakeTable) set(cands []Candidate, scanErr error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.cands, f.scanErr = cands, scanErr
}

func (f *fakeTable) Remove(_ context.Context, c Candidate) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.removed = append(f.removed, c)
	return nil
}

func (f *fakeTable) removedIDs() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []string
	for _, c := range f.removed {
		out = append(out, c.ID)
	}
	sort.Strings(out)
	return out
}

const (
	idAlive   = "a0000000-0000-4000-8000-000000000001"
	idGone    = "a0000000-0000-4000-8000-000000000002"
	idNoAPI   = "a0000000-0000-4000-8000-000000000003"
	idDoubt   = "a0000000-0000-4000-8000-000000000004"
	idStart   = "a0000000-0000-4000-8000-000000000005"
	idStopped = "a0000000-0000-4000-8000-000000000006"
	idOldStop = "a0000000-0000-4000-8000-000000000007"
	idBadFile = "a0000000-0000-4000-8000-000000000008"
	idOrphan  = "a0000000-0000-4000-8000-000000000009"
	idLeft    = "a0000000-0000-4000-8000-00000000000a"
)

func running(id string, gen uint64, pid int, uid uint32) journal.Record {
	return journal.Record{SandboxID: id, Attempt: 1, Generation: gen, State: journal.Running, PID: pid, PIDStart: 1,
		UID: uid, Template: "tpl-1", VCPUs: 2, MemMiB: 4096, ScratchGiB: 4, StartedAt: time.Now()}
}

func TestRecoverRules(t *testing.T) {
	f := newFixture(t, 100)
	jdir := t.TempDir()
	j := &journal.Journal{Dir: jdir}
	f.m.UseJournal(j)
	now := time.Now()
	for _, r := range []journal.Record{
		running(idAlive, 100, 501, 1000010),
		running(idGone, 101, 502, 1000011),
		running(idNoAPI, 102, 503, 1000012),
		running(idDoubt, 103, 504, 1000013),
		{SandboxID: idStart, Attempt: 1, Generation: 104, State: journal.Starting, UID: 1000014},
		{SandboxID: idStopped, Attempt: 2, Generation: 105, State: journal.Stopped, StoppedAt: now.Add(-time.Minute)},
		{SandboxID: idOldStop, Attempt: 1, Generation: 99, State: journal.Stopped, StoppedAt: now.Add(-48 * time.Hour)},
	} {
		if err := j.Write(r); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(jdir, idBadFile+".json"), []byte("{garbage"), 0o600); err != nil {
		t.Fatal(err)
	}
	table := &fakeTable{
		adopt: map[string]error{idAlive: nil, idNoAPI: ErrAPINotResponding, idDoubt: errors.New("permission denied")},
		cands: []Candidate{
			{ID: idAlive, PID: 501}, {ID: idNoAPI, PID: 503}, {ID: idDoubt, PID: 504},
			{ID: idGone}, // chroot left by the gone VM
			{ID: idStart, PID: 505},
			{ID: idBadFile, PID: 506},
			{ID: idOrphan, PID: 507},
			{ID: idLeft},
		},
	}
	rep, err := f.m.Recover(context.Background(), table)
	if err != nil {
		t.Fatal(err)
	}
	want := RecoverReport{Adopted: 1, Unresponsive: 1, Exited: 1, Abandoned: 1, Unverified: 1, Unreadable: 1, Tombstones: 1, Orphans: 1, Leftovers: 2}
	if rep != want {
		t.Fatalf("report\n got %+v\nwant %+v", rep, want)
	}
	// Removed: the orphan, the abandoned start, the gone VM's chroot, the
	// leftover chroot. Never the doubtful, unreadable or adopted VMs.
	gotRemoved := table.removedIDs()
	wantRemoved := []string{idGone, idStart, idOrphan, idLeft}
	sort.Strings(wantRemoved)
	if len(gotRemoved) != len(wantRemoved) {
		t.Fatalf("removed %v, want %v", gotRemoved, wantRemoved)
	}
	for i := range wantRemoved {
		if gotRemoved[i] != wantRemoved[i] {
			t.Fatalf("removed %v, want %v", gotRemoved, wantRemoved)
		}
	}

	states := map[string]pb.VMState{}
	for _, vm := range f.m.List() {
		states[vm.SandboxID] = vm.State
	}
	if states[idAlive] != pb.VMState_VM_STATE_RUNNING || states[idNoAPI] != pb.VMState_VM_STATE_RUNNING ||
		states[idGone] != pb.VMState_VM_STATE_EXITED || len(states) != 3 {
		t.Fatalf("table after recover: %v", states)
	}
	if f.uids.InUse() != 4 {
		t.Fatalf("uids in use %d, want 4 (alive, no-api, gone, doubt)", f.uids.InUse())
	}

	recs, bad, err := j.Load()
	if err != nil || len(bad) != 1 {
		t.Fatalf("journal after recover: %v %v", bad, err)
	}
	left := map[string]journal.State{}
	for _, r := range recs {
		left[r.SandboxID] = r.State
	}
	if _, ok := left[idStart]; ok {
		t.Fatal("abandoned starting record was kept")
	}
	if _, ok := left[idOldStop]; ok {
		t.Fatal("expired tombstone was kept")
	}
	if left[idGone] != journal.Running || left[idDoubt] != journal.Running || left[idStopped] != journal.Stopped {
		t.Fatalf("journal after recover: %v", left)
	}

	ctx := context.Background()
	vm, created, err := f.m.Create(ctx, CreateRequest{SandboxID: idAlive, Attempt: 1, Template: "tpl-1", VCPUs: 2, MemMiB: 4096, ScratchGiB: 4, TenantID: "public"})
	if err != nil || created || vm.Generation != 100 || vm.PID != 501 {
		t.Fatalf("repeat create of adopted VM: %+v %v %v", vm, created, err)
	}
	if res, err := f.m.Stop(ctx, idStopped, 2, 105); err != nil || !res.AlreadyStopped {
		t.Fatalf("repeat stop from journal tombstone: %+v %v", res, err)
	}
	_, _, err = f.m.Create(ctx, CreateRequest{SandboxID: idStopped, Attempt: 2, Template: "tpl-1", VCPUs: 2, MemMiB: 4096, ScratchGiB: 4, TenantID: "public"})
	wantReason(t, err, pb.ErrorReason_STALE_ATTEMPT)
	nv, _, err := f.m.Create(ctx, CreateRequest{SandboxID: idOrphan, Attempt: 1, Template: "tpl-1", VCPUs: 2, MemMiB: 4096, ScratchGiB: 4, TenantID: "public"})
	if err != nil || nv.Generation <= 105 {
		t.Fatalf("new VM generation %d must be above the journal's (105): %v", nv.Generation, err)
	}
}

func TestRecoverScanErrorRemovesNothing(t *testing.T) {
	f := newFixture(t, 10)
	j := &journal.Journal{Dir: t.TempDir()}
	f.m.UseJournal(j)
	if err := j.Write(journal.Record{SandboxID: idStart, Attempt: 1, Generation: 1, State: journal.Starting}); err != nil {
		t.Fatal(err)
	}
	table := &fakeTable{scanErr: errors.New("no /proc"), cands: []Candidate{{ID: idOrphan, PID: 9}}}
	if _, err := f.m.Recover(context.Background(), table); err != nil {
		t.Fatal(err)
	}
	if len(table.removedIDs()) != 0 {
		t.Fatalf("removed %v after a scan error", table.removedIDs())
	}
	if recs, _, _ := j.Load(); len(recs) != 1 {
		t.Fatalf("starting record removed after a scan error: %v", recs)
	}
}

func TestJournalFollowsCreateAndStop(t *testing.T) {
	f := newFixture(t, 10)
	j := &journal.Journal{Dir: t.TempDir()}
	f.m.UseJournal(j)
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	recs, _, _ := j.Load()
	if len(recs) != 1 || recs[0].State != journal.Running || recs[0].PID != vm.PID || recs[0].Generation != vm.Generation || recs[0].PIDStart == 0 {
		t.Fatalf("after create: %+v", recs)
	}
	if _, err := f.m.Stop(ctx, sb1, 1, vm.Generation); err != nil {
		t.Fatal(err)
	}
	recs, _, _ = j.Load()
	if len(recs) != 1 || recs[0].State != journal.Stopped || recs[0].Generation != vm.Generation {
		t.Fatalf("after stop: %+v", recs)
	}
	f.l.fail = errors.New("boom")
	_, _, err = f.m.Create(ctx, req(sb1, 2))
	wantReason(t, err, pb.ErrorReason_VMM_FAILED)
	recs, _, _ = j.Load()
	if len(recs) != 1 || recs[0].State != journal.Stopped {
		t.Fatalf("after failed create the tombstone must stay: %+v", recs)
	}
}

func TestDoubtfulSandboxesAreBlockedUntilTheProcessExits(t *testing.T) {
	f := newFixture(t, 100)
	jdir := t.TempDir()
	j := &journal.Journal{Dir: jdir}
	f.m.UseJournal(j)
	ctx := context.Background()
	if err := j.Write(running(idDoubt, 103, 504, 1000013)); err != nil {
		t.Fatal(err)
	}
	if err := j.Write(running(idGone, 101, 502, 1000011)); err != nil {
		t.Fatal(err)
	}
	garbage := []byte("{garbage")
	if err := os.WriteFile(j.Path(idBadFile), garbage, 0o600); err != nil {
		t.Fatal(err)
	}
	table := &fakeTable{
		adopt: map[string]error{idDoubt: errors.New("permission denied")},
		cands: []Candidate{{ID: idDoubt, PID: 504, UID: 1000013}, {ID: idBadFile, PID: 506, UID: 1000020}},
	}
	if _, err := f.m.Recover(ctx, table); err != nil {
		t.Fatal(err)
	}
	// B2: the UID of the VM with the unreadable record is reserved.
	if f.uids.Reserve(1000020) || f.uids.Reserve(1000013) {
		t.Fatal("a kept VM's UID is free")
	}
	_, _, err := f.m.Create(ctx, CreateRequest{SandboxID: idBadFile, Attempt: 1, Template: "tpl-1", VCPUs: 2, MemMiB: 4096, ScratchGiB: 4, TenantID: "public"})
	wantReason(t, err, pb.ErrorReason_SANDBOX_IN_DOUBT)
	_, err = f.m.Stop(ctx, idDoubt, 1, 103)
	wantReason(t, err, pb.ErrorReason_SANDBOX_IN_DOUBT)
	if raw, _ := os.ReadFile(j.Path(idBadFile)); string(raw) != string(garbage) {
		t.Fatalf("doubtful record changed: %q", raw)
	}
	if f.l.count() != 0 || len(table.removedIDs()) != 0 {
		t.Fatalf("launches %d, removed %v", f.l.count(), table.removedIDs())
	}
	// A journaled VM that was gone at start-up has no process handle.
	if res, err := f.m.Stop(ctx, idGone, 1, 101); err != nil || !res.AlreadyStopped {
		t.Fatalf("stop of a gone VM: %+v %v", res, err)
	}

	// The VM with the unreadable record exits: its doubt clears.
	table.set([]Candidate{{ID: idDoubt, PID: 504, UID: 1000013}, {ID: idBadFile}}, nil)
	if _, _, err := f.m.Create(ctx, CreateRequest{SandboxID: idBadFile, Attempt: 1, Template: "tpl-1", VCPUs: 2, MemMiB: 4096, ScratchGiB: 4, TenantID: "public"}); err != nil {
		t.Fatal(err)
	}
	if got := table.removedIDs(); len(got) != 1 || got[0] != idBadFile {
		t.Fatalf("removed %v, want the leftover chroot of %s", got, idBadFile)
	}
	if !f.uids.Reserve(1000020) {
		t.Fatal("the UID of the exited VM is still held")
	}
	_, err = f.m.Stop(ctx, idDoubt, 1, 103)
	wantReason(t, err, pb.ErrorReason_SANDBOX_IN_DOUBT)
}

func TestRecoverScanErrorBlocksCreateUntilAScanWorks(t *testing.T) {
	f := newFixture(t, 10)
	f.m.UseJournal(&journal.Journal{Dir: t.TempDir()})
	ctx := context.Background()
	table := &fakeTable{scanErr: errors.New("no /proc")}
	if _, err := f.m.Recover(ctx, table); err != nil {
		t.Fatal(err)
	}
	_, _, err := f.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	// A Firecracker with no record shows up: it is in doubt, its UID held.
	table.set([]Candidate{{ID: idOrphan, PID: 9, UID: 1000003}}, nil)
	if _, _, err := f.m.Create(ctx, req(sb1, 1)); err != nil {
		t.Fatal(err)
	}
	if f.uids.Reserve(1000003) {
		t.Fatal("the untracked VM's UID is free")
	}
	_, _, err = f.m.Create(ctx, CreateRequest{SandboxID: idOrphan, Attempt: 1, Template: "tpl-1", VCPUs: 2, MemMiB: 4096, ScratchGiB: 4, TenantID: "public"})
	wantReason(t, err, pb.ErrorReason_SANDBOX_IN_DOUBT)
}

// A template build waits for a working scan, as Create does: an
// unverified Firecracker may hold any UID.
func TestRecoverScanErrorBlocksBuildSlot(t *testing.T) {
	f := newFixture(t, 10)
	f.m.UseJournal(&journal.Journal{Dir: t.TempDir()})
	table := &fakeTable{scanErr: errors.New("no /proc")}
	if _, err := f.m.Recover(context.Background(), table); err != nil {
		t.Fatal(err)
	}
	_, _, err := f.m.BuildSlot("tpl-0123456789ab", 1024)
	wantReason(t, err, pb.ErrorReason_CAPACITY_VM_SLOTS)
	table.set([]Candidate{{ID: idOrphan, PID: 9, UID: 1000003}}, nil)
	uid, done, err := f.m.BuildSlot("tpl-0123456789ab", 1024)
	if err != nil {
		t.Fatal(err)
	}
	defer done(false)
	if uid == 1000003 {
		t.Fatal("the build VM got the untracked VM's UID")
	}
}

func TestCrashDuringAStartKeepsTheStoppedAttempt(t *testing.T) {
	f := newFixture(t, 10)
	jdir := t.TempDir()
	f.m.UseJournal(&journal.Journal{Dir: jdir})
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.m.Stop(ctx, sb1, 1, vm.Generation); err != nil {
		t.Fatal(err)
	}
	// Attempt 2 hangs in its launch; the agent "crashes" then.
	f.l.gate = make(chan struct{})
	done := make(chan struct{})
	go func() {
		defer close(done)
		_, _, _ = f.m.Create(ctx, req(sb1, 2))
	}()
	defer func() {
		close(f.l.gate)
		<-done
	}()
	// Read the record directly: Load would remove the temporary file of a
	// write in progress.
	path := (&journal.Journal{Dir: jdir}).Path(sb1)
	deadline := time.Now().Add(2 * time.Second)
	for {
		var r journal.Record
		raw, _ := os.ReadFile(path)
		if json.Unmarshal(raw, &r) == nil && r.State == journal.Starting {
			if p := r.Prev; p == nil || p.Attempt != 1 || p.Generation != vm.Generation {
				t.Fatalf("starting record does not keep the stopped attempt: %+v", r)
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("no starting record: %s", raw)
		}
		time.Sleep(time.Millisecond)
	}

	g := newFixture(t, 10)
	g.m.UseJournal(&journal.Journal{Dir: jdir})
	rep, err := g.m.Recover(ctx, &fakeTable{})
	if err != nil || rep.Abandoned != 1 || rep.Tombstones != 1 {
		t.Fatalf("recover: %+v %v", rep, err)
	}
	_, _, err = g.m.Create(ctx, req(sb1, 1))
	wantReason(t, err, pb.ErrorReason_STALE_ATTEMPT)
	if res, err := g.m.Stop(ctx, sb1, 1, vm.Generation); err != nil || !res.AlreadyStopped {
		t.Fatalf("repeat stop after the crash: %+v %v", res, err)
	}
}

func TestStopReportsAFailedTombstoneWrite(t *testing.T) {
	f := newFixture(t, 10)
	jdir := filepath.Join(t.TempDir(), "journal")
	if err := os.Mkdir(jdir, 0o700); err != nil {
		t.Fatal(err)
	}
	j := &journal.Journal{Dir: jdir}
	f.m.UseJournal(j)
	ctx := context.Background()
	vm, _, err := f.m.Create(ctx, req(sb1, 1))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(jdir, jdir+".away"); err != nil {
		t.Fatal(err)
	}
	_, err = f.m.Stop(ctx, sb1, 1, vm.Generation)
	wantReason(t, err, pb.ErrorReason_INTERNAL)
	if l := f.m.List(); len(l) != 1 || l[0].State != pb.VMState_VM_STATE_EXITED {
		t.Fatalf("after the failed write: %+v", l)
	}
	if err := os.Rename(jdir+".away", jdir); err != nil {
		t.Fatal(err)
	}
	if res, err := f.m.Stop(ctx, sb1, 1, vm.Generation); err != nil || !res.AlreadyStopped {
		t.Fatalf("retried stop: %+v %v", res, err)
	}
	recs, _, _ := j.Load()
	if len(recs) != 1 || recs[0].State != journal.Stopped || f.uids.InUse() != 0 {
		t.Fatalf("journal %+v, uids %d", recs, f.uids.InUse())
	}
}

// A running template build VM is not an untracked Firecracker.
func TestRescanSkipsTemplateBuildVM(t *testing.T) {
	f := newFixture(t, 10)
	f.m.UseJournal(&journal.Journal{Dir: t.TempDir()})
	table := &fakeTable{}
	if _, err := f.m.Recover(context.Background(), table); err != nil {
		t.Fatal(err)
	}
	uid, done, err := f.m.BuildSlot("tpl-0123456789ab", 1024)
	if err != nil {
		t.Fatal(err)
	}
	table.set([]Candidate{{ID: "tpl-0123456789ab", PID: 900, UID: uid}}, nil)
	if err := f.m.rescan(context.Background()); err != nil {
		t.Fatal(err)
	}
	f.m.mu.Lock()
	inDoubt := f.m.doubt["tpl-0123456789ab"] != nil
	f.m.mu.Unlock()
	if inDoubt {
		t.Fatal("the template build VM was put in doubt")
	}
	done(false)
	// After the build, the same process would be untracked.
	if err := f.m.rescan(context.Background()); err != nil {
		t.Fatal(err)
	}
	f.m.mu.Lock()
	inDoubt = f.m.doubt["tpl-0123456789ab"] != nil
	f.m.mu.Unlock()
	if !inDoubt {
		t.Fatal("a left-over build VM was not put in doubt")
	}
}
