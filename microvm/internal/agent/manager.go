// Package agent holds the VM table of one node and the Create, Stop, List and
// NodeInfo rules.
package agent

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"regexp"
	"sort"
	"sync"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	"github.com/onyx-dot-app/onyx/microvm/internal/journal"
	"github.com/onyx-dot-app/onyx/microvm/internal/scratch"
	"github.com/onyx-dot-app/onyx/microvm/internal/template"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

var sandboxIDRE = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// LaunchSpec is one VM to start.
type LaunchSpec struct {
	// ID is the jailer ID and the chroot directory name.
	ID           string
	UID          uint32
	Template     *template.Template
	ScratchBytes int64
}

// ProcInfo identifies a Firecracker process and its files.
type ProcInfo struct {
	PID int
	// PIDStart is the process start time (/proc/<pid>/stat), to detect PID reuse.
	PIDStart uint64
	Chroot   string
	APISock  string
	VsockUDS string
}

// Process is a running Firecracker process.
type Process interface {
	Info() ProcInfo
	// Done is closed when the process has exited.
	Done() <-chan struct{}
	// Kill stops the process, waits for it to exit and removes the VM's
	// scope and files. It is safe to call more than once and after the
	// process has exited.
	Kill(ctx context.Context) error
}

// ErrVMLeft marks a failed launch whose Firecracker process may still run,
// because its cleanup failed. Create then keeps the jailer UID reserved.
var ErrVMLeft = errors.New("the VM process may still run")

// Launcher starts VMs. The real one is fcvm.Launcher.
type Launcher interface {
	Launch(ctx context.Context, spec LaunchSpec) (Process, error)
}

// HostStats reads node capacity.
type HostStats interface {
	MemInfo() (totalMiB, availableMiB uint64, err error)
	DiskFreeBytes() (uint64, error)
}

// Versions are the static versions of the node, for NodeInfo and the
// template key check.
type Versions struct {
	Firecracker string
	HostKernel  string
	CPUModel    string
	Agent       string
	// GuestKernel is the release of the node's guest kernel (vmlinux).
	GuestKernel       string
	GuestKernelSHA256 string
	// EgressCAFingerprint is the deployment's egress CA. Empty: not checked.
	EgressCAFingerprint string
}

// NodeKey is the part of a template key that this node decides.
func (v Versions) NodeKey() template.NodeKey {
	return template.NodeKey{
		FirecrackerVersion: v.Firecracker, CPUModel: v.CPUModel, HostKernel: v.HostKernel,
		GuestKernelSHA256: v.GuestKernelSHA256, CAFingerprint: v.EgressCAFingerprint,
	}
}

// Config holds the node limits.
type Config struct {
	// MinFreeMemMiB is the memory reserve: Create needs MemAvailable >=
	// (guest memory of the starting VMs) + mem_mib + MinFreeMemMiB.
	MinFreeMemMiB uint64
	// MinFreeDiskBytes: Create needs this much free space on the data disk.
	MinFreeDiskBytes uint64
	MaxScratchGiB    uint32
	// StartTimeout bounds one VM start (jailer, restore).
	StartTimeout time.Duration
	// StopTimeout bounds one VM stop.
	StopTimeout time.Duration
	// TombstoneTTL is how long Stop remembers a stopped instance, to make a
	// repeat Stop succeed and to reject stale attempts.
	TombstoneTTL time.Duration
}

// VM is the public view of one VM.
type VM struct {
	SandboxID  string
	Attempt    uint64
	Generation uint64
	Template   string
	VCPUs      uint32
	MemMiB     uint32
	ScratchGiB uint32
	State      pb.VMState
	PID        int
	UID        uint32
	StartedAt  time.Time
	TenantID   string
	Managed    ManagedState
}

// Egress connects the VMs to the egress relay. The real one is
// relay.AgentEgress.
type Egress interface {
	// Attach starts relaying the egress of a running VM.
	Attach(vm VM, info ProcInfo) error
	// Detach stops the VM's relay listener and closes its connections.
	Detach(sandboxID string)
	// CloseAll closes the VM's relay connections and returns the count.
	CloseAll(sandboxID string) int
}

var tenantIDRE = regexp.MustCompile(`^[A-Za-z0-9_-]{1,63}$`)

type entry struct {
	vm   VM
	proc Process
	// busy is closed when the current Create, Stop or exit cleanup ends.
	// It is nil when no operation runs.
	busy chan struct{}
	// swap is closed when the current managed drive swap ends. Create and
	// Stop wait for it; the VM stays usable during a swap.
	swap chan struct{}
	// createErr is set when Create failed; the entry is then removed.
	createErr error
	// cleanupErr is set when the cleanup of an exited VM failed. Stop
	// retries it.
	cleanupErr error
}

type tombstone struct {
	attempt    uint64
	generation uint64
	at         time.Time
}

// Manager owns the VMs of the node.
type Manager struct {
	cfg       Config
	templates *template.Store
	launcher  Launcher
	stats     HostStats
	uids      *jailer.UIDPool
	versions  Versions
	log       *slog.Logger
	now       func() time.Time
	journal   *journal.Journal
	egress    Egress
	// releases run when a VM stops or exits, after the egress detach and
	// before the VM's vsock socket and jailer UID are freed.
	releases []func(VM)
	// adopter rescans the processes for the doubt rules (doubt.go).
	adopter Adopter
	scanMu  sync.Mutex

	mu      sync.Mutex
	vms     map[string]*entry
	tombs   map[string]tombstone
	lastGen uint64
	// doubt holds the sandboxes whose Firecracker the agent keeps running
	// but could not verify. needScan: the UIDs of such processes are not
	// known, so Create waits for a scan that works.
	doubt    map[string]*doubt
	needScan bool
	// building maps the jailer IDs of template build VMs (BuildSlot) to
	// their guest memory in MiB.
	building map[string]uint32

	managedGuest ManagedGuest
	swapTimeout  time.Duration

	// drain is the drain state (drain.go), under mu.
	drain drainState
}

// NewManager returns a Manager with an empty VM table.
func NewManager(cfg Config, templates *template.Store, launcher Launcher, stats HostStats,
	uids *jailer.UIDPool, versions Versions, log *slog.Logger) *Manager {
	return &Manager{
		cfg: cfg, templates: templates, launcher: launcher, stats: stats, uids: uids,
		versions: versions, log: log, now: time.Now,
		vms: map[string]*entry{}, tombs: map[string]tombstone{}, doubt: map[string]*doubt{},
		building: map[string]uint32{},
	}
}

// UseJournal makes the Manager keep a durable record of each VM. Call it
// before Recover and before the API serves.
func (m *Manager) UseJournal(j *journal.Journal) { m.journal = j }

// UseEgress makes the Manager attach each running VM to the egress relay.
// Call it before Recover and before the API serves.
func (m *Manager) UseEgress(e Egress) { m.egress = e }

// OnRelease adds f to the functions that run for a VM that stops, exits or
// fails to start. Call it before Recover and before the API serves.
func (m *Manager) OnRelease(f func(VM)) { m.releases = append(m.releases, f) }

// release removes everything that names the VM: first its relay identity
// and relay connections, then the OnRelease users (the daemon pass-through).
// Callers kill the process (which frees the vsock socket) and free the UID
// only after release returns, so a reused UID or socket path never carries
// the old identity (ENG-4606).
func (m *Manager) release(vm VM) {
	if m.egress != nil {
		m.egress.Detach(vm.SandboxID)
	}
	for _, f := range m.releases {
		f(vm)
	}
	m.log.Info("released VM identity", "sandbox_id", vm.SandboxID, "generation", vm.Generation)
}

func (t tombstone) record() *journal.Tombstone {
	return &journal.Tombstone{Attempt: t.attempt, Generation: t.generation, StoppedAt: t.at}
}

func (m *Manager) record(e *entry, state journal.State, info ProcInfo) journal.Record {
	return journal.Record{
		SandboxID: e.vm.SandboxID, Attempt: e.vm.Attempt, Generation: e.vm.Generation, State: state,
		PID: info.PID, PIDStart: info.PIDStart, UID: e.vm.UID,
		Chroot: info.Chroot, APISock: info.APISock, VsockUDS: info.VsockUDS,
		Template: e.vm.Template, VCPUs: e.vm.VCPUs, MemMiB: e.vm.MemMiB, ScratchGiB: e.vm.ScratchGiB,
		StartedAt: e.vm.StartedAt, TenantID: e.vm.TenantID, Managed: e.vm.Managed.record(),
	}
}

func (m *Manager) writeRecord(r journal.Record) error {
	if m.journal == nil {
		return nil
	}
	return m.journal.Write(r)
}

func (m *Manager) removeRecord(id string) {
	if m.journal == nil {
		return
	}
	if err := m.journal.Remove(id); err != nil {
		m.log.Error("remove journal record", "sandbox_id", id, "err", err)
	}
}

// CreateRequest is the input of Create.
type CreateRequest struct {
	SandboxID  string
	Attempt    uint64
	Template   string
	VCPUs      uint32
	MemMiB     uint32
	ScratchGiB uint32
	TenantID   string
}

// nextGeneration returns a node-unique, increasing generation. It starts from
// the wall clock so that it also increases across agent restarts.
func (m *Manager) nextGeneration() uint64 {
	g := uint64(m.now().UnixNano())
	if g <= m.lastGen {
		g = m.lastGen + 1
	}
	m.lastGen = g
	return g
}

// Create starts a VM, or returns the VM that already has (sandbox_id, attempt).
func (m *Manager) Create(ctx context.Context, req CreateRequest) (VM, bool, error) {
	if !sandboxIDRE.MatchString(req.SandboxID) {
		return VM{}, false, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "sandbox_id %q is not a lowercase UUID", req.SandboxID)
	}
	if req.Attempt == 0 {
		return VM{}, false, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "attempt must be 1 or more")
	}
	if !tenantIDRE.MatchString(req.TenantID) {
		return VM{}, false, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "tenant_id %q must match [A-Za-z0-9_-]{1,63}", req.TenantID)
	}
	if err := m.checkDoubt(ctx, req.SandboxID, true); err != nil {
		return VM{}, false, err
	}

	for {
		m.mu.Lock()
		e := m.vms[req.SandboxID]
		if e != nil && e.busy == nil && e.swap != nil {
			swap := e.swap
			m.mu.Unlock()
			if err := waitFor(ctx, swap); err != nil {
				return VM{}, false, err
			}
			continue
		}
		if e != nil && e.busy != nil {
			busy := e.busy
			m.mu.Unlock()
			if err := waitFor(ctx, busy); err != nil {
				return VM{}, false, err
			}
			if e.createErr != nil && e.vm.Attempt == req.Attempt {
				return VM{}, false, e.createErr
			}
			continue
		}
		if e != nil {
			if e.vm.Attempt == req.Attempt {
				vm := e.vm
				m.mu.Unlock()
				return vm, false, nil
			}
			if e.vm.State != pb.VMState_VM_STATE_EXITED || req.Attempt < e.vm.Attempt {
				vm := e.vm
				m.mu.Unlock()
				return VM{}, false, apierr.New(pb.ErrorReason_ATTEMPT_CONFLICT,
					"sandbox %s has attempt %d (generation %d, %s) on this node", vm.SandboxID, vm.Attempt, vm.Generation, vm.State)
			}
			if e.cleanupErr != nil {
				vm := e.vm
				m.mu.Unlock()
				return VM{}, false, apierr.New(pb.ErrorReason_VMM_FAILED,
					"cleanup of exited attempt %d failed (%v); Stop it to retry", vm.Attempt, e.cleanupErr)
			}
			// A newer attempt replaces an exited VM. Its files are already removed.
			if err := m.removeLocked(e); err != nil {
				m.mu.Unlock()
				return VM{}, false, err
			}
		}
		if err := m.staleLocked(req); err != nil {
			m.mu.Unlock()
			return VM{}, false, err
		}
		// Refuse early, before the template hash check. The check under
		// the lock below is the one that counts.
		if err := m.drainErrLocked(); err != nil {
			m.mu.Unlock()
			return VM{}, false, err
		}
		m.mu.Unlock()
		break
	}

	// The pin keeps template GC away until the VM is in the table.
	unpin := m.templates.Pin(req.Template)
	defer unpin()
	tpl, err := m.admit(req)
	if err != nil {
		return VM{}, false, err
	}

	m.mu.Lock()
	if other := m.vms[req.SandboxID]; other != nil {
		// Another Create won the race while this one checked admission.
		m.mu.Unlock()
		return m.Create(ctx, req)
	}
	// A Create and Stop of the same sandbox may have run during admission.
	if err := m.staleLocked(req); err != nil {
		m.mu.Unlock()
		return VM{}, false, err
	}
	// Drain and memory are checked under the lock, so two Creates never
	// count the same free memory.
	if err := m.drainErrLocked(); err != nil {
		m.mu.Unlock()
		return VM{}, false, err
	}
	if err := m.admitMemoryLocked(req.MemMiB); err != nil {
		m.mu.Unlock()
		return VM{}, false, err
	}
	uid, ok := m.uids.Get()
	if !ok {
		m.mu.Unlock()
		return VM{}, false, apierr.New(pb.ErrorReason_CAPACITY_VM_SLOTS, "no free jailer UID on this node")
	}
	e := &entry{
		vm: VM{
			SandboxID: req.SandboxID, Attempt: req.Attempt, Generation: m.nextGeneration(),
			Template: tpl.Version, VCPUs: req.VCPUs, MemMiB: req.MemMiB, ScratchGiB: req.ScratchGiB,
			State: pb.VMState_VM_STATE_STARTING, UID: uid, StartedAt: m.now(), TenantID: req.TenantID,
			Managed: ManagedState{Slots: tpl.ManagedSlots(), Active: pb.ManagedSlot_MANAGED_SLOT_A},
		},
		busy: make(chan struct{}),
	}
	m.vms[req.SandboxID] = e
	starting := m.record(e, journal.Starting, ProcInfo{})
	if t, ok := m.tombs[req.SandboxID]; ok {
		starting.Prev = t.record()
	}
	m.mu.Unlock()

	// The start must finish or clean up even if the caller goes away.
	startCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), m.cfg.StartTimeout)
	defer cancel()
	t0 := m.now()
	var proc Process
	// A "starting" record tells a restarted agent that this VM was never
	// handed out, so it may clean it up.
	launchErr := m.writeRecord(starting)
	if launchErr == nil {
		proc, launchErr = m.launcher.Launch(startCtx, LaunchSpec{
			ID: req.SandboxID, UID: uid, Template: tpl, ScratchBytes: int64(req.ScratchGiB) * scratch.GiB,
		})
	}
	if launchErr == nil && m.egress != nil {
		if err := m.egress.Attach(e.vm, proc.Info()); err != nil {
			launchErr = fmt.Errorf("attach egress relay: %w", err)
		}
	}
	if launchErr == nil {
		launchErr = m.writeRecord(m.record(e, journal.Running, proc.Info()))
		if launchErr != nil {
			launchErr = fmt.Errorf("write journal: %w", launchErr)
		}
	}
	if launchErr != nil && proc != nil {
		m.release(e.vm)
		if killErr := proc.Kill(startCtx); killErr != nil {
			launchErr = fmt.Errorf("%w (kill: %v): %w", launchErr, killErr, ErrVMLeft)
		}
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	busy := e.busy
	e.busy = nil
	defer close(busy)
	if launchErr != nil {
		e.createErr = launchErr
		if apierr.ReasonOf(launchErr) == pb.ErrorReason_INTERNAL {
			e.createErr = apierr.New(pb.ErrorReason_VMM_FAILED, "start VM: %v", launchErr)
		}
		delete(m.vms, req.SandboxID)
		if errors.Is(launchErr, ErrVMLeft) {
			// Never give a second VM the UID of a process that may still run.
			m.log.Error("VM may still run after a failed create; the sandbox is in doubt",
				"sandbox_id", req.SandboxID, "uid", uid)
			m.doubt[req.SandboxID] = &doubt{reason: "a failed start may have left its VM running", uids: []uint32{uid}}
			// Not VMM_FAILED: callers must not start this attempt on another node.
			e.createErr = apierr.New(pb.ErrorReason_SANDBOX_IN_DOUBT, "start VM: %v", launchErr)
		} else {
			m.uids.Put(uid)
		}
		// Put the stopped attempt back over the starting record.
		if t, ok := m.tombs[req.SandboxID]; ok {
			if err := m.writeTombstone(req.SandboxID, t); err != nil {
				m.log.Error("write journal tombstone", "sandbox_id", req.SandboxID, "err", err)
			}
		} else {
			m.removeRecord(req.SandboxID)
		}
		m.log.Error("create failed", "sandbox_id", req.SandboxID, "attempt", req.Attempt, "err", launchErr)
		return VM{}, false, e.createErr
	}
	e.proc = proc
	e.vm.PID = proc.Info().PID
	e.vm.State = pb.VMState_VM_STATE_RUNNING
	go m.watch(req.SandboxID, e)
	m.log.Info("created", "sandbox_id", req.SandboxID, "attempt", req.Attempt, "generation", e.vm.Generation,
		"pid", e.vm.PID, "uid", uid, "ms", m.now().Sub(t0).Milliseconds())
	return e.vm, true, nil
}

// staleLocked rejects an attempt that is not newer than the stopped one.
func (m *Manager) staleLocked(req CreateRequest) error {
	m.pruneTombstonesLocked()
	if t, ok := m.tombs[req.SandboxID]; ok && req.Attempt <= t.attempt {
		return apierr.New(pb.ErrorReason_STALE_ATTEMPT,
			"attempt %d is not newer than stopped attempt %d", req.Attempt, t.attempt)
	}
	return nil
}

// admit checks the template, the shape, the scratch size and the node
// capacity. Firecracker checks nothing about a snapshot on load, so the
// template key must fit this node and its files must match their hashes.
func (m *Manager) admit(req CreateRequest) (*template.Template, error) {
	tpl, err := m.templates.Get(req.Template)
	if err != nil {
		return nil, err
	}
	if err := tpl.CheckNode(m.versions.NodeKey()); err != nil {
		return nil, err
	}
	if err := m.templates.Verify(tpl); err != nil {
		m.log.Error("template failed its hash check", "template", tpl.Version, "err", err)
		return nil, err
	}
	if req.VCPUs != tpl.VCPUs || req.MemMiB != tpl.MemMiB {
		return nil, apierr.New(pb.ErrorReason_TEMPLATE_SHAPE_MISMATCH,
			"template %q is %d vCPU / %d MiB, the request is %d vCPU / %d MiB", tpl.Version, tpl.VCPUs, tpl.MemMiB, req.VCPUs, req.MemMiB)
	}
	if err := scratch.CheckSize(req.ScratchGiB, tpl.ScratchGiB, m.cfg.MaxScratchGiB); err != nil {
		return nil, err
	}
	free, err := m.stats.DiskFreeBytes()
	if err != nil {
		return nil, apierr.New(pb.ErrorReason_CAPACITY_DISK, "read disk space: %v", err)
	}
	if free < m.cfg.MinFreeDiskBytes {
		return nil, apierr.New(pb.ErrorReason_CAPACITY_DISK,
			"data disk has %d MiB free, the node keeps %d MiB free", free>>20, m.cfg.MinFreeDiskBytes>>20)
	}
	return tpl, nil
}

// admitMemoryLocked admits a VM of memMiB on measured memory: the node's
// MemAvailable must hold the guest memory of the VMs that are starting
// (their pages are not in use yet), the full guest memory of the new VM and
// the reserve. The balloon's free page reporting (layout 4) returns the
// memory that guests free, so MemAvailable is the real use, not the sum of
// guest sizes.
func (m *Manager) admitMemoryLocked(memMiB uint32) error {
	total, avail, err := m.stats.MemInfo()
	if err != nil {
		// An unreadable statistic is a refusal: no VM started, another node may accept.
		return apierr.New(pb.ErrorReason_CAPACITY_MEMORY, "read memory info: %v", err)
	}
	starting := m.startingMiBLocked()
	need := starting + uint64(memMiB) + m.cfg.MinFreeMemMiB
	if avail >= need {
		return nil
	}
	e := apierr.New(pb.ErrorReason_CAPACITY_MEMORY,
		"node has %d MiB available of %d MiB; it needs %d MiB: %d MiB for the VM, %d MiB for %d starting VMs and a %d MiB reserve",
		avail, total, need, memMiB, starting, m.startingCountLocked(), m.cfg.MinFreeMemMiB)
	e.Metadata = map[string]string{
		"mem_total_mib":     fmt.Sprint(total),
		"mem_available_mib": fmt.Sprint(avail),
		"mem_needed_mib":    fmt.Sprint(need),
		"vm_mem_mib":        fmt.Sprint(memMiB),
		"mem_starting_mib":  fmt.Sprint(starting),
		"mem_reserve_mib":   fmt.Sprint(m.cfg.MinFreeMemMiB),
	}
	m.log.Warn("create refused: memory", "mem_available_mib", avail, "mem_needed_mib", need,
		"mem_starting_mib", starting, "mem_reserve_mib", m.cfg.MinFreeMemMiB)
	return e
}

// startingMiBLocked is the guest memory of the VMs that are starting and of
// the template build VMs.
func (m *Manager) startingMiBLocked() uint64 {
	var n uint64
	for _, mib := range m.building {
		n += uint64(mib)
	}
	for _, e := range m.vms {
		if e.vm.State == pb.VMState_VM_STATE_STARTING {
			n += uint64(e.vm.MemMiB)
		}
	}
	return n
}

func (m *Manager) startingCountLocked() int {
	n := len(m.building)
	for _, e := range m.vms {
		if e.vm.State == pb.VMState_VM_STATE_STARTING {
			n++
		}
	}
	return n
}

// StopResult is the output of Stop.
type StopResult struct {
	AlreadyStopped bool
}

// Stop stops the VM if sandbox_id, attempt and generation all match it.
func (m *Manager) Stop(ctx context.Context, sandboxID string, attempt, generation uint64) (StopResult, error) {
	if err := m.checkDoubt(ctx, sandboxID, false); err != nil {
		return StopResult{}, err
	}
	var e *entry
	for {
		m.mu.Lock()
		e = m.vms[sandboxID]
		if e == nil {
			t, ok := m.tombs[sandboxID]
			m.mu.Unlock()
			if ok && t.attempt == attempt && t.generation == generation {
				return StopResult{AlreadyStopped: true}, nil
			}
			if ok {
				return StopResult{}, apierr.New(pb.ErrorReason_INSTANCE_MISMATCH,
					"sandbox %s: last stopped instance is attempt %d generation %d", sandboxID, t.attempt, t.generation)
			}
			return StopResult{}, apierr.New(pb.ErrorReason_SANDBOX_NOT_FOUND, "sandbox %s has no VM on this node", sandboxID)
		}
		if e.busy != nil || e.swap != nil {
			wait := e.busy
			if wait == nil {
				wait = e.swap
			}
			m.mu.Unlock()
			if err := waitFor(ctx, wait); err != nil {
				return StopResult{}, err
			}
			continue
		}
		if e.vm.Attempt != attempt || e.vm.Generation != generation {
			vm := e.vm
			m.mu.Unlock()
			return StopResult{}, apierr.New(pb.ErrorReason_INSTANCE_MISMATCH,
				"sandbox %s runs attempt %d generation %d, the request names attempt %d generation %d",
				sandboxID, vm.Attempt, vm.Generation, attempt, generation)
		}
		e.busy = make(chan struct{})
		m.mu.Unlock()
		break
	}

	// Kill also runs for an exited VM: it retries a cleanup that failed, and
	// does nothing after one that worked.
	stopCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), m.cfg.StopTimeout)
	defer cancel()
	m.release(e.vm)
	var killErr error
	if e.proc != nil { // nil: a journaled VM that was gone at start-up
		killErr = e.proc.Kill(stopCtx)
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	busy := e.busy
	e.busy = nil
	defer close(busy)
	exited := e.vm.State == pb.VMState_VM_STATE_EXITED
	if killErr != nil {
		select {
		case <-e.proc.Done():
			// The process is gone; only the cleanup failed. A retried Stop
			// retries it.
			e.vm.State = pb.VMState_VM_STATE_EXITED
			e.cleanupErr = killErr
		default:
		}
		m.log.Error("stop failed", "sandbox_id", sandboxID, "err", killErr)
		return StopResult{}, apierr.New(pb.ErrorReason_VMM_FAILED, "stop VM: %v", killErr)
	}
	if err := m.removeLocked(e); err != nil {
		// The process is gone. A retried Stop saves the tombstone.
		e.vm.State = pb.VMState_VM_STATE_EXITED
		m.log.Error("stop: save the stopped state", "sandbox_id", sandboxID, "err", err)
		return StopResult{}, err
	}
	m.log.Info("stopped", "sandbox_id", sandboxID, "attempt", attempt, "generation", generation)
	return StopResult{AlreadyStopped: exited}, nil
}

// DialTarget returns the vsock UDS of a running VM, for Dial. A generation
// other than 0 must match the running VM.
func (m *Manager) DialTarget(sandboxID string, generation uint64) (string, error) {
	t, err := m.GuestTarget(sandboxID)
	if err != nil {
		return "", err
	}
	if generation != 0 && generation != t.Generation {
		return "", apierr.New(pb.ErrorReason_INSTANCE_MISMATCH,
			"sandbox %s runs generation %d, not %d", sandboxID, t.Generation, generation)
	}
	return t.VsockUDS, nil
}

// GuestTarget is the vsock socket of one running VM instance.
type GuestTarget struct {
	VsockUDS   string
	Generation uint64
}

// GuestTarget returns the vsock socket and generation of a running VM. A VM
// that is starting, stopping or exited fails with VM_NOT_RUNNING.
func (m *Manager) GuestTarget(sandboxID string) (GuestTarget, error) {
	if !sandboxIDRE.MatchString(sandboxID) {
		return GuestTarget{}, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "sandbox_id %q is not a lowercase UUID", sandboxID)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	e := m.vms[sandboxID]
	if e == nil {
		if m.doubt[sandboxID] != nil {
			return GuestTarget{}, apierr.New(pb.ErrorReason_SANDBOX_IN_DOUBT,
				"sandbox %s has a Firecracker process that the agent could not verify", sandboxID)
		}
		return GuestTarget{}, apierr.New(pb.ErrorReason_SANDBOX_NOT_FOUND, "sandbox %s has no VM on this node", sandboxID)
	}
	// busy: a Create, Stop or exit cleanup runs, so the VM is not usable.
	if e.proc == nil || e.busy != nil || e.vm.State != pb.VMState_VM_STATE_RUNNING {
		state := e.vm.State.String()
		if e.busy != nil && e.vm.State == pb.VMState_VM_STATE_RUNNING {
			state = "stopping"
		}
		return GuestTarget{}, apierr.New(pb.ErrorReason_VM_NOT_RUNNING, "sandbox %s VM is %s", sandboxID, state)
	}
	return GuestTarget{VsockUDS: e.proc.Info().VsockUDS, Generation: e.vm.Generation}, nil
}

// CloseConnections closes the egress relay connections of a running VM. It
// has the preconditions of Stop.
func (m *Manager) CloseConnections(sandboxID string, attempt, generation uint64) (int, error) {
	m.mu.Lock()
	e := m.vms[sandboxID]
	if e == nil {
		m.mu.Unlock()
		return 0, apierr.New(pb.ErrorReason_SANDBOX_NOT_FOUND, "sandbox %s has no VM on this node", sandboxID)
	}
	if e.vm.Attempt != attempt || e.vm.Generation != generation {
		vm := e.vm
		m.mu.Unlock()
		return 0, apierr.New(pb.ErrorReason_INSTANCE_MISMATCH,
			"sandbox %s runs attempt %d generation %d, the request names attempt %d generation %d",
			sandboxID, vm.Attempt, vm.Generation, attempt, generation)
	}
	running := e.vm.State == pb.VMState_VM_STATE_RUNNING
	m.mu.Unlock()
	if !running || m.egress == nil {
		return 0, nil
	}
	n := m.egress.CloseAll(sandboxID)
	m.log.Info("closed relay connections", "sandbox_id", sandboxID, "count", n)
	return n, nil
}

// removeLocked drops a stopped entry and keeps a tombstone, also in the
// journal. If the journal write fails, the entry stays.
func (m *Manager) removeLocked(e *entry) error {
	t := tombstone{attempt: e.vm.Attempt, generation: e.vm.Generation, at: m.now()}
	if err := m.writeTombstone(e.vm.SandboxID, t); err != nil {
		return apierr.New(pb.ErrorReason_INTERNAL, "save the stopped state of sandbox %s: %v", e.vm.SandboxID, err)
	}
	delete(m.vms, e.vm.SandboxID)
	m.uids.Put(e.vm.UID)
	m.tombs[e.vm.SandboxID] = t
	return nil
}

func (m *Manager) writeTombstone(id string, t tombstone) error {
	return m.writeRecord(journal.Record{
		SandboxID: id, Attempt: t.attempt, Generation: t.generation, State: journal.Stopped, StoppedAt: t.at,
	})
}

func (m *Manager) pruneTombstonesLocked() {
	cut := m.now().Add(-m.cfg.TombstoneTTL)
	for id, t := range m.tombs {
		if t.at.Before(cut) {
			delete(m.tombs, id)
			if m.vms[id] == nil {
				m.removeRecord(id)
			}
		}
	}
}

// watch handles a Firecracker process that exits without Stop.
func (m *Manager) watch(sandboxID string, e *entry) {
	<-e.proc.Done()
	m.mu.Lock()
	if m.vms[sandboxID] != e || e.busy != nil || e.vm.State != pb.VMState_VM_STATE_RUNNING {
		// Stop is running or has removed the entry.
		m.mu.Unlock()
		return
	}
	e.vm.State = pb.VMState_VM_STATE_EXITED
	e.busy = make(chan struct{})
	m.mu.Unlock()
	m.log.Warn("VM exited without Stop", "sandbox_id", sandboxID, "attempt", e.vm.Attempt, "generation", e.vm.Generation)

	ctx, cancel := context.WithTimeout(context.Background(), m.cfg.StopTimeout)
	defer cancel()
	m.release(e.vm)
	killErr := e.proc.Kill(ctx)

	m.mu.Lock()
	defer m.mu.Unlock()
	busy := e.busy
	e.busy = nil
	close(busy)
	if killErr != nil {
		e.cleanupErr = killErr
		m.log.Error("cleanup of exited VM failed", "sandbox_id", sandboxID, "err", killErr)
	}
	// The UID stays reserved until the entry is removed.
}

// List returns every VM, sorted by sandbox ID.
func (m *Manager) List() []VM {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]VM, 0, len(m.vms))
	for _, e := range m.vms {
		out = append(out, e.vm)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].SandboxID < out[j].SandboxID })
	return out
}

// Versions returns the node versions.
func (m *Manager) Versions() Versions { return m.versions }

// TemplatesInUse returns the templates of every VM in the table, also
// starting and exited ones. Template GC keeps them.
func (m *Manager) TemplatesInUse() map[string]bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := map[string]bool{}
	for _, e := range m.vms {
		out[e.vm.Template] = true
	}
	return out
}

// BuildSlot gives a template build VM with jailer ID id and memMiB of guest
// memory a jailer UID. It refuses the build on a draining node and admits
// it on memory as Create does, and the build counts as a starting VM until
// done. The process scan does not count the VM as untracked while it runs. Call done when the VM is gone; done(true) puts the VM in doubt
// with its UID, for a VM that may still run, and a later scan frees the UID
// once it is gone.
func (m *Manager) BuildSlot(id string, memMiB uint32) (uint32, func(left bool), error) {
	if err := m.checkDoubt(context.Background(), id, true); err != nil {
		return 0, nil, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.building[id]; ok || m.vms[id] != nil || m.doubt[id] != nil {
		return 0, nil, apierr.New(pb.ErrorReason_INTERNAL, "build VM %s already runs", id)
	}
	if err := m.drainErrLocked(); err != nil {
		return 0, nil, err
	}
	if err := m.admitMemoryLocked(memMiB); err != nil {
		return 0, nil, err
	}
	uid, ok := m.uids.Get()
	if !ok {
		return 0, nil, apierr.New(pb.ErrorReason_CAPACITY_VM_SLOTS, "no free jailer UID for the template build")
	}
	m.building[id] = memMiB
	done := func(left bool) {
		m.mu.Lock()
		defer m.mu.Unlock()
		delete(m.building, id)
		if left {
			m.log.Error("template build VM may still run; it is in doubt with its UID", "id", id, "uid", uid)
			m.doubt[id] = &doubt{reason: "a template build VM may still run", uids: []uint32{uid}}
			return
		}
		m.uids.Put(uid)
	}
	return uid, done, nil
}

// NodeInfo is the output of NodeInfo.
type NodeInfo struct {
	MemTotalMiB     uint64
	MemAvailableMiB uint64
	DiskFreeMiB     uint64
	VMCount         int
	Templates       []*template.Template
	Versions        Versions
	// MemReserveMiB is the memory reserve; MemStartingMiB is the guest
	// memory of the starting VMs (see admitMemoryLocked).
	MemReserveMiB  uint64
	MemStartingMiB uint64
	Drain          DrainStatus
}

// NodeInfo returns the node capacity, versions and templates.
func (m *Manager) NodeInfo() (NodeInfo, error) {
	total, avail, err := m.stats.MemInfo()
	if err != nil {
		return NodeInfo{}, err
	}
	free, err := m.stats.DiskFreeBytes()
	if err != nil {
		return NodeInfo{}, err
	}
	tpls, err := m.templates.List()
	if err != nil {
		return NodeInfo{}, err
	}
	m.rescanForDrain()
	m.mu.Lock()
	n := m.liveVMsLocked()
	starting := m.startingMiBLocked()
	drain := m.drainStatusLocked()
	m.mu.Unlock()
	return NodeInfo{
		MemTotalMiB: total, MemAvailableMiB: avail, DiskFreeMiB: free >> 20,
		VMCount: n, Templates: tpls, Versions: m.versions,
		MemReserveMiB: m.cfg.MinFreeMemMiB, MemStartingMiB: starting, Drain: drain,
	}, nil
}

func waitFor(ctx context.Context, ch <-chan struct{}) error {
	select {
	case <-ch:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}
