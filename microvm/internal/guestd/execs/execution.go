package execs

import (
	"errors"
	"maps"
	"os"
	"os/exec"
	"slices"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

// Completion is how an execution ended.
type Completion int

const (
	Exited Completion = iota + 1
	Signaled
	Canceled
	DeadlineExceeded
)

func (c Completion) String() string {
	switch c {
	case Exited:
		return "EXITED"
	case Signaled:
		return "SIGNALED"
	case Canceled:
		return "CANCELED"
	case DeadlineExceeded:
		return "DEADLINE_EXCEEDED"
	default:
		return "UNSPECIFIED"
	}
}

// Stream selects stdout or stderr.
type Stream int

const (
	Stdout Stream = 0
	Stderr Stream = 1
)

// Result is the typed end of an execution.
type Result struct {
	Completion Completion
	ExitCode   int // -1 unless Exited
	Signal     int
	FinishedAt time.Time
	Bytes      [2]int64 // stdout, stderr totals
}

// Info is a copy of an execution record.
type Info struct {
	ID         string
	Argv       []string
	Labels     map[string]string
	PID        int
	StartedAt  time.Time
	DeadlineAt time.Time
	Bytes      [2]int64
	Ended      bool
	Result     Result
}

var (
	ErrStdinNotOpen = errors.New("stdin is not open")
	ErrEnded        = errors.New("execution ended")
)

const stdinWriteTimeout = 30 * time.Second

// kill reasons
const (
	killNone int32 = iota
	killCancel
	killDeadline
	// The main process exited before any kill: later kills change nothing.
	killExited
)

// Execution is one command and its record.
type Execution struct {
	ID         string
	Argv       []string
	Labels     map[string]string
	PID        int
	StartedAt  time.Time
	DeadlineAt time.Time

	ready bool // guarded by Manager.mu: started, visible to Get
	// evicting is guarded by Manager.mu: a Start drops this ended record once
	// its own command has started.
	evicting bool
	cmd      *exec.Cmd
	group    Group
	reason   atomic.Int32
	// softSignals has bit 1<<sig set for each SIGINT or SIGTERM that Signal
	// sent.
	softSignals atomic.Uint32
	// lastUsed is the UnixNano of the start or of the last Get.
	lastUsed atomic.Int64
	done     chan struct{}
	// acct reports changes of the output memory to the Manager.
	acct func(delta int64)

	stdinMu sync.Mutex
	stdin   *os.File

	mu      sync.Mutex
	out     [2]ring
	ended   bool
	result  Result
	endedAt time.Time
	changed chan struct{}
}

// Done is closed when the execution has ended and its output is final.
func (e *Execution) Done() <-chan struct{} { return e.done }

// Changed returns a channel that is closed at the next output or at the end.
func (e *Execution) Changed() <-chan struct{} {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.changed
}

func (e *Execution) notifyLocked() {
	close(e.changed)
	e.changed = make(chan struct{})
}

func (e *Execution) appendOut(s Stream, p []byte) {
	e.mu.Lock()
	before := e.out[s].size()
	e.out[s].append(p)
	delta := int64(e.out[s].size() - before)
	e.notifyLocked()
	e.mu.Unlock()
	if delta != 0 && e.acct != nil {
		e.acct(delta)
	}
}

// trimOut keeps at most n bytes of each stream. It returns the bytes freed.
func (e *Execution) trimOut(n int) int64 {
	e.mu.Lock()
	defer e.mu.Unlock()
	var freed int
	for i := range e.out {
		before := e.out[i].size()
		e.out[i].keep(n)
		freed += before - e.out[i].size()
	}
	return int64(freed)
}

func (e *Execution) outSize() int64 {
	e.mu.Lock()
	defer e.mu.Unlock()
	return int64(e.out[Stdout].size() + e.out[Stderr].size())
}

// Read returns up to n bytes of stream s from off. gapTo > 0 means the
// bytes [off, gapTo) were dropped and data starts at gapTo.
func (e *Execution) Read(s Stream, off int64, n int) (data []byte, gapTo, next int64) {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.out[s].read(off, n)
}

// Ended reports the result if the execution has ended.
func (e *Execution) Ended() (Result, bool) {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.result, e.ended
}

// Info returns a copy of the record.
func (e *Execution) Info() Info {
	e.mu.Lock()
	defer e.mu.Unlock()
	return Info{
		ID: e.ID, Argv: slices.Clone(e.Argv), Labels: maps.Clone(e.Labels), PID: e.PID,
		StartedAt: e.StartedAt, DeadlineAt: e.DeadlineAt,
		Bytes: [2]int64{e.out[Stdout].total(), e.out[Stderr].total()},
		Ended: e.ended, Result: e.result,
	}
}

// WriteStdin writes data to stdin and closes stdin if closeStdin is set.
// A full pipe blocks the call, not the output readers.
func (e *Execution) WriteStdin(data []byte, closeStdin bool) (int, error) {
	if _, ended := e.Ended(); ended {
		return 0, ErrEnded
	}
	e.stdinMu.Lock()
	defer e.stdinMu.Unlock()
	if e.stdin == nil {
		return 0, ErrStdinNotOpen
	}
	_ = e.stdin.SetWriteDeadline(time.Now().Add(stdinWriteTimeout))
	n, err := e.stdin.Write(data)
	if err != nil {
		return n, err
	}
	if closeStdin {
		err = e.stdin.Close()
		e.stdin = nil
	}
	return n, err
}

func (e *Execution) touch() { e.lastUsed.Store(time.Now().UnixNano()) }

// signal sends sig to the process group of the main process. It does
// nothing after the main process exited.
func (e *Execution) signal(sig syscall.Signal) error {
	if e.reason.Load() == killExited {
		return nil
	}
	e.softSignals.Or(1 << uint(sig))
	return e.group.Signal(sig)
}

// kill stops every process of the execution. The first reason wins. It does
// nothing after the main process exited.
func (e *Execution) kill(reason int32) error {
	if !e.reason.CompareAndSwap(killNone, reason) && e.reason.Load() == killExited {
		return nil
	}
	return e.group.Kill()
}
