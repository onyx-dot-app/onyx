// Package guestlog ships the serial console and the Firecracker log of each
// VM off the node: it writes their lines to the agent's stdout as JSON, with
// the sandbox ID, generation and tenant, so the cluster log pipeline collects
// them.
//
// Firecracker writes both files itself and keeps running when the agent
// restarts, so the shipper tails the files rather than a pipe. One goroutine
// serves all VMs. Each VM has a byte budget (token bucket) and the node has
// one more; bytes over a budget are skipped and counted, so a noisy guest
// cannot flood the node's log pipeline.
//
// MaxFileBytes caps each file on the data disk. Firecracker writes the
// console to its stdout, a file the agent opens with O_APPEND, so the shipper
// empties console.log in place once it has read past the cap (copytruncate):
// Firecracker's next write lands at the new end. Firecracker v1.17 opens
// fc.log without O_APPEND (vmm/src/utils open_file_nonblock: read, write,
// O_NONBLOCK), so after a truncate it would write at its old offset and
// leave a hole. For fc.log the shipper punches a hole over the bytes it has
// read instead (Linux): the size stays, the disk blocks are freed.
//
// From E2B's orchestrator (e2b-dev/infra, Apache-2.0,
// packages/orchestrator/internal/sandbox/fc/process.go and
// packages/shared/pkg/logger/sandbox): one structured line per Firecracker
// output line, with the sandbox and team (here tenant) as fields.
package guestlog

import (
	"bytes"
	"context"
	"errors"
	"io"
	"log/slog"
	"os"
	"sync"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/jailer"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

// Streams.
const (
	Console     = "console"
	Firecracker = "firecracker"
)

// Defaults of a Shipper.
const (
	DefaultInterval = time.Second
	DefaultVMRate   = 16 << 10
	DefaultVMBurst  = 256 << 10
	DefaultNodeRate = 1 << 20
	DefaultMaxLine  = 4 << 10
	// DefaultMaxFileBytes is the default cap of each log file on disk.
	DefaultMaxFileBytes = 16 << 20
)

// Shipper tails the log files of the VMs in a Manager.
type Shipper struct {
	Layout jailer.Layout
	// VMs returns the VM table (agent.Manager.List).
	VMs func() []agent.VM
	// Out gets one line per guest log line (kind=guest_log).
	Out *slog.Logger
	// Interval between two reads. 0 means DefaultInterval.
	Interval time.Duration
	// VMRate and VMBurst are the byte budget of one VM (both files). 0 means
	// the default.
	VMRate, VMBurst int
	// NodeRate is the byte budget of the node; its burst is 4 seconds. 0
	// means DefaultNodeRate.
	NodeRate int
	// MaxLine truncates longer lines. 0 means DefaultMaxLine.
	MaxLine int
	// Count, if set, gets the shipped and dropped bytes of each read.
	Count func(stream string, shipped, dropped int)
	// MaxFileBytes caps each log file on disk (see the package doc). 0 means
	// no cap.
	MaxFileBytes int64
	// ShipOff skips the lines and only enforces MaxFileBytes.
	ShipOff bool

	now func() time.Time

	mu   sync.Mutex
	tail map[string]*vmTail
	node bucket
	// started: Start ran. Before it, every VM is adopted.
	started bool
}

type vmTail struct {
	vm     agent.VM
	budget bucket
	files  []*fileTail
}

type fileTail struct {
	stream  string
	path    string
	off     int64
	partial []byte
	// skipLine drops bytes up to the next newline, after a skip or a
	// truncated line.
	skipLine bool
	// appendOnly: the writer uses O_APPEND, so the file may be truncated.
	// Otherwise the shipper punches holes; punched is the end of the last one.
	appendOnly bool
	punched    int64
	// capErr: the last cap failed and was logged.
	capErr bool
}

type bucket struct {
	tokens, rate, burst float64
	last                time.Time
}

func (b *bucket) refill(now time.Time) {
	if !b.last.IsZero() {
		b.tokens = min(b.burst, b.tokens+b.rate*now.Sub(b.last).Seconds())
	}
	b.last = now
}

// Start reads the VMs that already run (VMs adopted after an agent restart)
// from the end of their files, then ships new lines every Interval until ctx
// ends. Call it before the API serves, so a new VM is read from its start.
func (s *Shipper) Start(ctx context.Context) {
	s.init()
	s.mu.Lock()
	s.syncLocked(true)
	s.started = true
	s.mu.Unlock()
	go func() {
		t := time.NewTicker(s.Interval)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				s.Tick()
			}
		}
	}()
}

func (s *Shipper) init() {
	if s.now == nil {
		s.now = time.Now
	}
	if s.Interval <= 0 {
		s.Interval = DefaultInterval
	}
	if s.VMRate <= 0 {
		s.VMRate = DefaultVMRate
	}
	if s.VMBurst <= 0 {
		s.VMBurst = DefaultVMBurst
	}
	if s.NodeRate <= 0 {
		s.NodeRate = DefaultNodeRate
	}
	if s.MaxLine <= 0 {
		s.MaxLine = DefaultMaxLine
	}
	if s.tail == nil {
		s.tail = map[string]*vmTail{}
		r := float64(s.NodeRate)
		s.node = bucket{tokens: 4 * r, rate: r, burst: 4 * r}
	}
}

// Tick syncs the VM table and ships the new lines of every VM.
func (s *Shipper) Tick() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.init()
	s.syncLocked(false)
	now := s.now()
	s.node.refill(now)
	for _, t := range s.tail {
		s.pumpLocked(t, now, false)
	}
}

// Release ships the last lines of a VM that stops or exits. Register it with
// agent.Manager.OnRelease: it runs before the VM's files are removed. The
// tail stays until the VM leaves the table, so a Tick in between does not
// read the files again from the start.
func (s *Shipper) Release(vm agent.VM) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.init()
	t := s.tail[vm.SandboxID]
	if t != nil && t.vm.Generation > vm.Generation {
		// The files belong to a newer VM.
		return
	}
	if t == nil || t.vm.Generation < vm.Generation {
		// The VM ended before a Tick saw it: read its files from the start,
		// unless it was adopted and exits during recovery, before Start.
		t = s.newTail(vm, !s.started)
		s.tail[vm.SandboxID] = t
	}
	now := s.now()
	s.node.refill(now)
	s.pumpLocked(t, now, true)
}

// syncLocked adds the VMs that are new and drops the ones that are gone.
// An exited VM keeps its tail until it leaves the table, so Release can
// still ship its last lines; an exited VM gets no new tail.
// adopted: start at the end of the files (the lines were shipped before).
func (s *Shipper) syncLocked(adopted bool) {
	seen := map[string]bool{}
	for _, vm := range s.VMs() {
		t := s.tail[vm.SandboxID]
		if t != nil && t.vm.Generation == vm.Generation {
			seen[vm.SandboxID] = true
			t.vm = vm
			continue
		}
		if vm.State == pb.VMState_VM_STATE_EXITED {
			continue
		}
		seen[vm.SandboxID] = true
		s.tail[vm.SandboxID] = s.newTail(vm, adopted)
	}
	for id := range s.tail {
		if !seen[id] {
			delete(s.tail, id)
		}
	}
}

func (s *Shipper) newTail(vm agent.VM, adopted bool) *vmTail {
	r := float64(s.VMRate)
	t := &vmTail{vm: vm, budget: bucket{tokens: float64(s.VMBurst), rate: r, burst: float64(s.VMBurst), last: s.now()}}
	for _, f := range []*fileTail{
		{stream: Console, path: s.Layout.ConsoleLog(vm.SandboxID), appendOnly: true},
		{stream: Firecracker, path: s.Layout.HostPath(vm.SandboxID, jailer.LogFile)},
	} {
		if adopted {
			f.off, f.skipLine = atEnd(f.path)
		}
		t.files = append(t.files, f)
	}
	return t
}

// pumpLocked ships the new bytes of one VM within its budget and the node's.
// final: also ship an unterminated last line.
func (s *Shipper) pumpLocked(t *vmTail, now time.Time, final bool) {
	t.budget.refill(now)
	for _, f := range t.files {
		shipped, dropped := s.readFile(t, f, final)
		if dropped > 0 {
			s.Out.LogAttrs(context.Background(), slog.LevelWarn, "guest log rate limit",
				append(s.vmAttrs(t, f.stream), slog.Int("dropped_bytes", dropped))...)
		}
		if s.Count != nil && (shipped > 0 || dropped > 0) {
			s.Count(f.stream, shipped, dropped)
		}
	}
}

func (s *Shipper) readFile(t *vmTail, f *fileTail, final bool) (shipped, dropped int) {
	fh, err := os.OpenFile(f.path, os.O_RDWR, 0)
	if err != nil {
		// Not there yet, or removed with the VM.
		return 0, 0
	}
	defer func() { _ = fh.Close() }()
	st, err := fh.Stat()
	if err != nil {
		return 0, 0
	}
	size := st.Size()
	if size < f.off {
		// Truncated or replaced: start over.
		f.off, f.partial, f.skipLine, f.punched = 0, nil, false, 0
	}
	if s.ShipOff {
		f.off, f.partial, f.skipLine = size, nil, !endsLine(fh, size)
		s.capFile(t, fh, f)
		return 0, 0
	}
	defer func() { dropped += s.capFile(t, fh, f) }()
	avail := size - f.off
	budget := int64(min(t.budget.tokens, s.node.tokens))
	n := min(avail, max(budget, 0))
	if n > 0 {
		buf := make([]byte, n)
		got, err := fh.ReadAt(buf, f.off)
		if err != nil && !errors.Is(err, io.EOF) {
			return 0, 0
		}
		n = int64(got)
		f.off += n
		t.budget.tokens -= float64(n)
		s.node.tokens -= float64(n)
		s.lines(t, f, buf[:n])
	}
	if rest := size - f.off; rest > 0 && n < avail {
		// Over budget: skip to the current end of the file.
		f.off, f.partial, f.skipLine = size, nil, !endsLine(fh, size)
		dropped = int(rest)
	}
	if final && len(f.partial) > 0 && !f.skipLine {
		s.emit(t, f.stream, f.partial, false)
		f.partial = nil
	}
	return int(n), dropped
}

// capFile frees the bytes of f that the shipper has read once they pass
// MaxFileBytes. It returns the bytes lost when it had to empty a file that
// had unread bytes. A failure is logged once until the cap works again.
func (s *Shipper) capFile(t *vmTail, fh *os.File, f *fileTail) int {
	limit := s.MaxFileBytes
	if limit <= 0 {
		return 0
	}
	if !f.appendOnly {
		if f.off-f.punched >= limit {
			if err := punchHole(fh, f.off); err != nil {
				s.capFailed(t, f, err)
				return 0
			}
			f.punched, f.capErr = f.off, false
		}
		return 0
	}
	if f.off < limit {
		return 0
	}
	st, err := fh.Stat()
	if err != nil {
		s.capFailed(t, f, err)
		return 0
	}
	// Bytes written since the read would be lost: wait for the next read,
	// unless the file keeps growing past twice the cap.
	lost := st.Size() - f.off
	if lost > 0 && st.Size() < 2*limit {
		return 0
	}
	if err := fh.Truncate(0); err != nil {
		s.capFailed(t, f, err)
		return 0
	}
	f.off, f.punched, f.capErr = 0, 0, false
	if lost > 0 {
		f.partial, f.skipLine = nil, false
		return int(lost)
	}
	return 0
}

func (s *Shipper) capFailed(t *vmTail, f *fileTail, err error) {
	if f.capErr {
		return
	}
	f.capErr = true
	s.Out.LogAttrs(context.Background(), slog.LevelError, "guest log cap failed",
		append(s.vmAttrs(t, f.stream), slog.String("path", f.path), slog.String("err", err.Error()))...)
}

// atEnd returns the size of a file and whether its last line is unfinished.
func atEnd(path string) (int64, bool) {
	fh, err := os.Open(path)
	if err != nil {
		return 0, false
	}
	defer func() { _ = fh.Close() }()
	st, err := fh.Stat()
	if err != nil {
		return 0, false
	}
	return st.Size(), !endsLine(fh, st.Size())
}

// endsLine reports whether the byte before off is a newline (or off is 0).
func endsLine(r io.ReaderAt, off int64) bool {
	if off == 0 {
		return true
	}
	b := make([]byte, 1)
	if _, err := r.ReadAt(b, off-1); err != nil {
		return false
	}
	return b[0] == '\n'
}

// lines emits the complete lines in data, after the partial line of the
// last read.
func (s *Shipper) lines(t *vmTail, f *fileTail, data []byte) {
	if f.skipLine {
		i := bytes.IndexByte(data, '\n')
		if i < 0 {
			return
		}
		data, f.skipLine = data[i+1:], false
	}
	if len(f.partial) > 0 {
		data = append(f.partial, data...)
		f.partial = nil
	}
	for {
		i := bytes.IndexByte(data, '\n')
		if i < 0 {
			break
		}
		s.emitLine(t, f.stream, data[:i])
		data = data[i+1:]
	}
	if len(data) > s.MaxLine {
		s.emit(t, f.stream, data[:s.MaxLine], true)
		f.skipLine = true
		return
	}
	if len(data) > 0 {
		f.partial = bytes.Clone(data)
	}
}

func (s *Shipper) emitLine(t *vmTail, stream string, line []byte) {
	line = bytes.TrimRight(line, "\r")
	if len(line) == 0 {
		return
	}
	if len(line) > s.MaxLine {
		s.emit(t, stream, line[:s.MaxLine], true)
		return
	}
	s.emit(t, stream, line, false)
}

func (s *Shipper) emit(t *vmTail, stream string, line []byte, truncated bool) {
	attrs := append(s.vmAttrs(t, stream), slog.String("line", string(line)))
	if truncated {
		attrs = append(attrs, slog.Bool("truncated", true))
	}
	s.Out.LogAttrs(context.Background(), slog.LevelInfo, "guest log", attrs...)
}

func (s *Shipper) vmAttrs(t *vmTail, stream string) []slog.Attr {
	return []slog.Attr{
		slog.String("kind", "guest_log"),
		slog.String("stream", stream),
		slog.String("sandbox_id", t.vm.SandboxID),
		slog.Uint64("generation", t.vm.Generation),
		slog.String("tenant_id", t.vm.TenantID),
	}
}
