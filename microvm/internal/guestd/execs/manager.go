// Package execs runs the guest daemon's commands. Each command (an
// execution) runs in its own kill group with a deadline. Its record and the
// tail of its output stay in memory after the client goes away.
package execs

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

// Config holds the manager limits.
type Config struct {
	DefaultDeadline time.Duration // 30 min if zero
	MaxDeadline     time.Duration // 24 h if zero
	OutputBytes     int           // kept per stream; 4 MiB if zero
	// OutputBudget caps the output kept by all executions; 256 MiB if zero.
	// Over it, ended records lose their output (oldest first), then running
	// ones keep only their latest bytes.
	OutputBudget int64
	// MaxTracked caps the records, running and ended; 64 if zero. A Start
	// over it drops the least recently used ended record; with none, it
	// fails with ErrCapReached.
	MaxTracked int
	// MaxRunning caps the running executions; MaxTracked if zero.
	MaxRunning int
	EndedTTL   time.Duration // 1 h if zero
	Isolator   Isolator
	Log        *slog.Logger
}

// validate rejects a missing Isolator and negative limits. Zero means the
// default.
func (c *Config) validate() error {
	switch {
	case c.Isolator == nil:
		return errors.New("execs: Isolator is required")
	case c.DefaultDeadline < 0, c.MaxDeadline < 0, c.EndedTTL < 0:
		return errors.New("execs: durations must not be negative")
	case c.OutputBytes < 0, c.MaxRunning < 0, c.MaxTracked < 0, c.OutputBudget < 0:
		return errors.New("execs: limits must not be negative")
	}
	return nil
}

func (c *Config) defaults() {
	if c.DefaultDeadline == 0 {
		c.DefaultDeadline = 30 * time.Minute
	}
	if c.MaxDeadline == 0 {
		c.MaxDeadline = 24 * time.Hour
	}
	if c.OutputBytes == 0 {
		c.OutputBytes = 4 << 20
	}
	if c.OutputBudget == 0 {
		c.OutputBudget = 256 << 20
	}
	if c.MaxTracked == 0 {
		c.MaxTracked = 64
	}
	if c.MaxRunning == 0 || c.MaxRunning > c.MaxTracked {
		c.MaxRunning = c.MaxTracked
	}
	if c.EndedTTL == 0 {
		c.EndedTTL = time.Hour
	}
	if c.Log == nil {
		c.Log = slog.Default()
	}
}

// Spec is one command to start.
type Spec struct {
	Argv     []string
	Dir      string
	Env      []string // full environment
	Stdin    bool
	Deadline time.Duration // 0 means the default
	Labels   map[string]string
}

var (
	ErrNotFound    = errors.New("execution not found")
	ErrTooMany     = errors.New("too many running executions")
	ErrCapReached  = errors.New("execution cap reached: every tracked execution is running")
	ErrBadArgument = errors.New("invalid argument")
)

// StartError means the command could not start.
type StartError struct{ Err error }

func (e *StartError) Error() string { return "start: " + e.Err.Error() }
func (e *StartError) Unwrap() error { return e.Err }

// Manager owns every execution.
type Manager struct {
	cfg Config

	mu    sync.Mutex
	execs map[string]*Execution
	// evicting counts the ended records that a Start in progress drops when
	// its command has started.
	evicting int
	// used is the output memory of all records.
	used atomic.Int64

	stopGC chan struct{}
	gcOnce sync.Once
}

// NewManager returns a Manager. cfg.Isolator is required. A background
// loop drops expired ended records until Shutdown, also when no new
// command starts.
func NewManager(cfg Config) (*Manager, error) {
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	cfg.defaults()
	if cfg.DefaultDeadline > cfg.MaxDeadline {
		return nil, fmt.Errorf("execs: default deadline %s is above the max %s", cfg.DefaultDeadline, cfg.MaxDeadline)
	}
	m := &Manager{cfg: cfg, execs: map[string]*Execution{}, stopGC: make(chan struct{})}
	go m.gcLoop(min(cfg.EndedTTL/4, time.Minute))
	return m, nil
}

func (m *Manager) gcLoop(every time.Duration) {
	t := time.NewTicker(max(every, 10*time.Millisecond))
	defer t.Stop()
	for {
		select {
		case <-m.stopGC:
			return
		case now := <-t.C:
			m.mu.Lock()
			m.gcLocked(now)
			m.mu.Unlock()
		}
	}
}

const readChunk = 32 << 10

// afterExit is a test hook: it runs after the main process exited.
var afterExit func(*Execution)

// Start starts a command and returns its record.
func (m *Manager) Start(spec Spec) (*Execution, error) {
	if len(spec.Argv) == 0 || spec.Argv[0] == "" {
		return nil, fmt.Errorf("%w: argv is empty", ErrBadArgument)
	}
	deadline := spec.Deadline
	if deadline < 0 || deadline > m.cfg.MaxDeadline {
		return nil, fmt.Errorf("%w: deadline must be between 0 and %s", ErrBadArgument, m.cfg.MaxDeadline)
	}
	if deadline == 0 {
		deadline = m.cfg.DefaultDeadline
	}
	dir := spec.Dir
	if dir == "" {
		dir = "/"
	}

	m.mu.Lock()
	m.gcLocked(time.Now())
	if running := m.runningLocked(); running >= m.cfg.MaxRunning {
		m.mu.Unlock()
		if running >= m.cfg.MaxTracked {
			return nil, fmt.Errorf("%w (%d)", ErrCapReached, m.cfg.MaxTracked)
		}
		return nil, ErrTooMany
	}
	// Over the cap, pick the least recently used ended record. It is dropped
	// only after the new command starts.
	var victim *Execution
	if len(m.execs)-m.evicting >= m.cfg.MaxTracked {
		if victim = m.lruEndedLocked(); victim == nil {
			m.mu.Unlock()
			return nil, fmt.Errorf("%w (%d)", ErrCapReached, m.cfg.MaxTracked)
		}
		victim.evicting = true
		m.evicting++
	}
	id := newID()
	e := &Execution{
		ID: id, Argv: slices.Clone(spec.Argv), Labels: maps.Clone(spec.Labels),
		done: make(chan struct{}), changed: make(chan struct{}), acct: m.account,
	}
	e.touch()
	e.out[Stdout].max, e.out[Stderr].max = m.cfg.OutputBytes, m.cfg.OutputBytes
	// Reserve the slot while the process starts.
	m.execs[id] = e
	m.mu.Unlock()

	err := m.spawn(e, spec, dir, deadline)
	if victim != nil {
		m.mu.Lock()
		victim.evicting = false
		m.evicting--
		if err == nil && m.execs[victim.ID] == victim {
			m.cfg.Log.Info("execution cap: dropped the least recently used ended record", "execution_id", victim.ID)
			m.drop(victim)
		}
		m.mu.Unlock()
	}
	if err != nil {
		m.mu.Lock()
		delete(m.execs, id)
		m.mu.Unlock()
		return nil, err
	}
	m.mu.Lock()
	e.ready = true
	m.mu.Unlock()
	return e, nil
}

func (m *Manager) spawn(e *Execution, spec Spec, dir string, deadline time.Duration) error {
	g, err := m.cfg.Isolator.NewGroup(e.ID)
	if err != nil {
		return fmt.Errorf("kill group: %w", err)
	}
	path, err := lookPath(spec.Argv[0], dir, spec.Env)
	if err != nil {
		_ = g.Close()
		return &StartError{Err: err}
	}
	cmd := &exec.Cmd{Path: path, Args: spec.Argv, Dir: dir, Env: spec.Env}
	g.Prepare(cmd)

	var readers [2]*os.File
	var closers []io.Closer
	closeAll := func() {
		for _, c := range closers {
			_ = c.Close()
		}
	}
	for i := range readers {
		r, w, err := os.Pipe()
		if err != nil {
			closeAll()
			_ = g.Close()
			return err
		}
		readers[i] = r
		closers = append(closers, r, w)
		if i == 0 {
			cmd.Stdout = w
		} else {
			cmd.Stderr = w
		}
	}
	var stdinW *os.File
	if spec.Stdin {
		r, w, err := os.Pipe()
		if err != nil {
			closeAll()
			_ = g.Close()
			return err
		}
		cmd.Stdin, stdinW = r, w
		closers = append(closers, r, w)
	}
	if err := cmd.Start(); err != nil {
		closeAll()
		_ = g.Close()
		return &StartError{Err: err}
	}
	// The child holds its own copies of the pipe ends.
	_ = cmd.Stdout.(*os.File).Close()
	_ = cmd.Stderr.(*os.File).Close()
	if spec.Stdin {
		_ = cmd.Stdin.(*os.File).Close()
	}
	g.Started(cmd.Process.Pid)

	now := time.Now()
	e.cmd, e.group, e.stdin = cmd, g, stdinW
	e.PID, e.StartedAt, e.DeadlineAt = cmd.Process.Pid, now, now.Add(deadline)
	go m.wait(e, readers, deadline)
	return nil
}

// wait collects output, enforces the deadline and records the result.
func (m *Manager) wait(e *Execution, readers [2]*os.File, deadline time.Duration) {
	var rwg sync.WaitGroup
	for i, r := range readers {
		rwg.Go(func() {
			buf := make([]byte, readChunk)
			for {
				n, err := r.Read(buf)
				if n > 0 {
					e.appendOut(Stream(i), buf[:n])
				}
				if err != nil {
					return
				}
			}
		})
	}
	timer := time.AfterFunc(deadline, func() {
		if err := e.kill(killDeadline); err != nil {
			m.cfg.Log.Warn("kill at deadline", "execution_id", e.ID, "err", err)
		}
	})
	_ = e.cmd.Wait()
	// Fix the reason now: a Cancel after the exit must not turn it into
	// CANCELED.
	e.reason.CompareAndSwap(killNone, killExited)
	reason := e.reason.Load()
	if afterExit != nil {
		afterExit(e)
	}
	timer.Stop()
	// The command ends with its main process: kill what it left behind.
	if err := e.group.Kill(); err != nil {
		m.cfg.Log.Warn("kill leftover processes", "execution_id", e.ID, "err", err)
	}

	readDone := make(chan struct{})
	go func() { rwg.Wait(); close(readDone) }()
	select {
	case <-readDone:
	case <-time.After(2 * time.Second):
		// A process outside the group still holds the pipes.
		m.cfg.Log.Warn("output pipes still open after exit", "execution_id", e.ID)
	}
	for _, r := range readers {
		_ = r.Close()
	}
	<-readDone
	if err := e.group.Close(); err != nil {
		m.cfg.Log.Warn("remove kill group", "execution_id", e.ID, "err", err)
	}
	e.stdinMu.Lock()
	if e.stdin != nil {
		_ = e.stdin.Close()
		e.stdin = nil
	}
	e.stdinMu.Unlock()

	res := Result{ExitCode: -1, FinishedAt: time.Now()}
	if ws, ok := e.cmd.ProcessState.Sys().(syscall.WaitStatus); ok && ws.Signaled() {
		res.Signal = int(ws.Signal())
	}
	// A kill that came too late to stop a normal exit keeps the exit code.
	switch {
	case res.Signal != 0 && reason == killCancel:
		res.Completion = Canceled
	case res.Signal > 0 && res.Signal < 32 && reason == killExited && e.softSignals.Load()&(1<<uint(res.Signal)) != 0:
		res.Completion = Canceled
	case res.Signal != 0 && reason == killDeadline:
		res.Completion = DeadlineExceeded
	case res.Signal != 0:
		res.Completion = Signaled
	default:
		res.Completion, res.ExitCode = Exited, e.cmd.ProcessState.ExitCode()
	}
	e.mu.Lock()
	res.Bytes = [2]int64{e.out[Stdout].total(), e.out[Stderr].total()}
	e.result, e.ended, e.endedAt = res, true, res.FinishedAt
	e.notifyLocked()
	e.mu.Unlock()
	close(e.done)
	m.cfg.Log.Info("execution ended", "execution_id", e.ID, "completion", res.Completion.String(),
		"exit_code", res.ExitCode, "signal", res.Signal)
}

// Get returns the record of id and marks it used.
func (m *Manager) Get(id string) (*Execution, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	e, ok := m.execs[id]
	if !ok || !e.ready {
		return nil, ErrNotFound
	}
	e.touch()
	return e, nil
}

// List returns every record that has all the given labels, oldest first.
func (m *Manager) List(labels map[string]string) []*Execution {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []*Execution
	for _, e := range m.execs {
		if !e.ready {
			continue
		}
		ok := true
		for k, v := range labels {
			if e.Labels[k] != v {
				ok = false
				break
			}
		}
		if ok {
			out = append(out, e)
		}
	}
	slices.SortFunc(out, func(a, b *Execution) int { return a.StartedAt.Compare(b.StartedAt) })
	return out
}

// Running returns the number of running executions.
func (m *Manager) Running() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.runningLocked()
}

// Signal sends sig to the process group of the execution's main process and
// does not wait. It returns the result and true if the execution had
// already ended.
func (m *Manager) Signal(id string, sig syscall.Signal) (Result, bool, error) {
	e, err := m.Get(id)
	if err != nil {
		return Result{}, false, err
	}
	if r, ended := e.Ended(); ended {
		return r, true, nil
	}
	if err := e.signal(sig); err != nil {
		return Result{}, false, err
	}
	return Result{}, false, nil
}

// Cancel kills the execution and waits for its result. alreadyEnded is
// true if it had ended before the call.
func (m *Manager) Cancel(ctx context.Context, id string) (res Result, alreadyEnded bool, err error) {
	e, err := m.Get(id)
	if err != nil {
		return Result{}, false, err
	}
	if r, ended := e.Ended(); ended {
		return r, true, nil
	}
	if err := e.kill(killCancel); err != nil {
		m.cfg.Log.Warn("kill on cancel", "execution_id", e.ID, "err", err)
	}
	select {
	case <-e.done:
		r, _ := e.Ended()
		return r, false, nil
	case <-ctx.Done():
		return Result{}, false, ctx.Err()
	}
}

// Shutdown kills every running execution and stops the record cleanup.
func (m *Manager) Shutdown() {
	m.gcOnce.Do(func() { close(m.stopGC) })
	m.mu.Lock()
	var running []*Execution
	for _, e := range m.execs {
		if e.ready {
			if _, ended := e.Ended(); !ended {
				running = append(running, e)
			}
		}
	}
	m.mu.Unlock()
	for _, e := range running {
		if err := e.kill(killCancel); err != nil {
			m.cfg.Log.Warn("kill on shutdown", "execution_id", e.ID, "err", err)
		}
	}
	for _, e := range running {
		<-e.done
	}
}

func (m *Manager) runningLocked() int {
	n := 0
	for _, e := range m.execs {
		if _, ended := e.Ended(); !ended {
			n++
		}
	}
	return n
}

// gcLocked drops ended records older than EndedTTL.
func (m *Manager) gcLocked(now time.Time) {
	for _, e := range m.execs {
		e.mu.Lock()
		done, at := e.ended, e.endedAt
		e.mu.Unlock()
		if done && !e.evicting && now.Sub(at) > m.cfg.EndedTTL {
			m.drop(e)
		}
	}
}

// lruEndedLocked returns the least recently used ended record that no other
// Start drops, or nil.
func (m *Manager) lruEndedLocked() *Execution {
	var lru *Execution
	for _, e := range m.execs {
		if _, ended := e.Ended(); !ended || e.evicting {
			continue
		}
		if lru == nil || e.lastUsed.Load() < lru.lastUsed.Load() {
			lru = e
		}
	}
	return lru
}

// drop removes an ended record. Caller holds m.mu.
func (m *Manager) drop(e *Execution) {
	delete(m.execs, e.ID)
	m.used.Add(-e.outSize())
}

func (m *Manager) account(delta int64) {
	if m.used.Add(delta) > m.cfg.OutputBudget {
		m.enforceBudget()
	}
}

// enforceBudget frees output down to 3/4 of the budget: first all output of
// ended records, oldest first, then the oldest bytes of running ones.
func (m *Manager) enforceBudget() {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.used.Load() <= m.cfg.OutputBudget {
		return
	}
	target := m.cfg.OutputBudget / 4 * 3
	var ended, running []*Execution
	for _, e := range m.execs {
		if _, done := e.Ended(); done {
			ended = append(ended, e)
		} else {
			running = append(running, e)
		}
	}
	slices.SortFunc(ended, func(a, b *Execution) int { return a.endedAt.Compare(b.endedAt) })
	for _, e := range ended {
		if m.used.Load() <= target {
			return
		}
		m.used.Add(-e.trimOut(0))
	}
	if m.used.Load() <= target || len(running) == 0 {
		return
	}
	share := int(target / int64(2*len(running)))
	for _, e := range running {
		m.used.Add(-e.trimOut(share))
	}
	m.cfg.Log.Warn("output budget reached: kept only the latest output", "running", len(running), "bytes_per_stream", share)
}

// lookPath resolves name with the PATH of the command's env, not the
// daemon's. Relative PATH entries are relative to dir, the command's
// working directory.
func lookPath(name, dir string, env []string) (string, error) {
	if strings.Contains(name, "/") {
		return name, nil
	}
	path := ""
	for _, kv := range env {
		if v, ok := strings.CutPrefix(kv, "PATH="); ok {
			path = v
		}
	}
	for _, d := range filepath.SplitList(path) {
		if d == "" {
			d = "."
		}
		if !filepath.IsAbs(d) {
			d = filepath.Join(dir, d)
		}
		p := filepath.Join(d, name)
		if st, err := os.Stat(p); err == nil && st.Mode().IsRegular() && st.Mode().Perm()&0o111 != 0 {
			return p, nil
		}
	}
	return "", fmt.Errorf("%q: %w", name, exec.ErrNotFound)
}

// newID uses crypto/rand: userspace PRNG state is the same in every clone
// of a snapshot.
func newID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}
