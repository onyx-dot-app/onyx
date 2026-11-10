// Package browser runs the guest's headful Chromium on Xvfb (ENG-4573):
// start and stop, restart after a crash, a CDP port on vsock, and the saved
// profile.
package browser

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/url"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
)

// State is the browser state.
type State int

const (
	Stopped State = iota
	Starting
	Running
	Restarting
	Stopping
	Failed
)

func (s State) String() string {
	return [...]string{"stopped", "starting", "running", "restarting", "stopping", "failed"}[s]
}

var (
	// ErrUnavailable means the VM has no browser (binary or user missing).
	ErrUnavailable = errors.New("browser not available")
	// ErrStartFailed means Xvfb or Chromium did not get ready.
	ErrStartFailed = errors.New("browser start failed")
	// ErrProfile means the saved profile could not be copied.
	ErrProfile = errors.New("browser profile")
)

// Config configures a Manager. Zero values get the defaults in New.
type Config struct {
	// ChromeBins are candidate Chromium binaries; Start uses the first that
	// exists. Empty: no browser.
	ChromeBins []string
	XvfbBin    string
	Display    int    // X display number (99)
	Screen     string // Xvfb screen, WxHxDepth (1280x800x24)
	// CDPPort is Chromium's DevTools TCP port on 127.0.0.1.
	CDPPort int
	// VsockPort is the guest vsock port that forwards to CDPPort.
	VsockPort uint32
	// Listen opens the CDP listener on VsockPort (vsock in the VM).
	Listen func(port uint32) (net.Listener, error)
	// ProfileDir is the saved profile; WorkDir holds the live one.
	ProfileDir string
	WorkDir    string
	// ProfileMaxBytes caps a saved profile (256 MiB).
	ProfileMaxBytes int64
	// User runs Xvfb and Chromium. Chromium's sandbox does not run as
	// root. Empty: the daemon's own user (tests).
	User string
	// TmpDir holds the X11 socket and lock (/tmp).
	TmpDir string
	// Env is the base environment (proxy and CA settings).
	Env []string
	// Isolator puts Xvfb and Chromium each in a kill group.
	Isolator execs.Isolator
	// CgroupRoot is the parent cgroup of the groups; it gets MemoryMax.
	// Empty: no memory limit.
	CgroupRoot string
	MemoryMax  int64 // 2 GiB
	// Times.
	StartTimeout time.Duration // 30 s
	StopTimeout  time.Duration // 10 s
	BackoffMin   time.Duration // 1 s
	BackoffMax   time.Duration // 30 s
	// StableAfter: a run this long resets the crash count and backoff (60 s).
	StableAfter time.Duration
	// MaxFastCrashes in a row before Failed (5).
	MaxFastCrashes int
	Log            *slog.Logger
}

func (c *Config) defaults() {
	set := func(d *time.Duration, v time.Duration) {
		if *d == 0 {
			*d = v
		}
	}
	set(&c.StartTimeout, 30*time.Second)
	set(&c.StopTimeout, 10*time.Second)
	set(&c.BackoffMin, time.Second)
	set(&c.BackoffMax, 30*time.Second)
	set(&c.StableAfter, time.Minute)
	if c.Display == 0 {
		c.Display = 99
	}
	if c.Screen == "" {
		c.Screen = "1280x800x24"
	}
	if c.CDPPort == 0 {
		c.CDPPort = 9222
	}
	if c.VsockPort == 0 {
		c.VsockPort = 9222
	}
	if c.ProfileMaxBytes == 0 {
		c.ProfileMaxBytes = 256 << 20
	}
	if c.MemoryMax == 0 {
		c.MemoryMax = 2 << 30
	}
	if c.MaxFastCrashes == 0 {
		c.MaxFastCrashes = 5
	}
	if c.TmpDir == "" {
		c.TmpDir = "/tmp"
	}
	if c.Log == nil {
		c.Log = slog.Default()
	}
}

// Status is a snapshot of the browser.
type Status struct {
	State         State
	VsockPort     uint32
	CDPPath       string // /devtools/browser/<id>
	PID           int
	StartedAt     time.Time
	StartDuration time.Duration
	Restarts      int
	LastError     string
	MemoryBytes   uint64
	MemoryMax     uint64
	ProfileDir    string
}

// StopResult is the outcome of Stop.
type StopResult struct {
	WasRunning   bool
	Clean        bool
	ProfileSaved bool
	ProfileBytes int64
	ProfileError string
}

// Manager owns the one browser of the VM.
type Manager struct {
	cfg Config

	op chan struct{} // one Start or Stop at a time; lock honors ctx

	mu       sync.Mutex
	st       Status
	sup      *supervisor
	runSeq   int
	limitSet bool
}

// New returns a Manager. It does not start anything.
func New(cfg Config) (*Manager, error) {
	cfg.defaults()
	if len(cfg.ChromeBins) > 0 && (cfg.Isolator == nil || cfg.Listen == nil || cfg.ProfileDir == "" || cfg.WorkDir == "") {
		return nil, errors.New("browser: Isolator, Listen, ProfileDir and WorkDir are required")
	}
	if cfg.MemoryMax < 0 || cfg.ProfileMaxBytes < 0 {
		return nil, errors.New("browser: limits must not be negative")
	}
	m := &Manager{cfg: cfg, op: make(chan struct{}, 1)}
	m.st = Status{State: Stopped, VsockPort: cfg.VsockPort, ProfileDir: cfg.ProfileDir}
	if cfg.CgroupRoot != "" {
		m.st.MemoryMax = uint64(cfg.MemoryMax)
	}
	return m, nil
}

func (m *Manager) lockOp(ctx context.Context) error {
	select {
	case m.op <- struct{}{}:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (m *Manager) unlockOp() { <-m.op }

// Status returns the current status.
func (m *Manager) Status() Status {
	m.mu.Lock()
	st := m.st
	m.mu.Unlock()
	if m.cfg.CgroupRoot != "" {
		st.MemoryBytes = memoryCurrent(m.cfg.CgroupRoot)
	}
	return st
}

func (m *Manager) update(f func(*Status)) {
	m.mu.Lock()
	f(&m.st)
	m.mu.Unlock()
}

type creds struct {
	cred *syscall.Credential // nil: the daemon's user
	home string
}

func (m *Manager) lookupUser() (creds, error) {
	if m.cfg.User == "" {
		return creds{home: os.Getenv("HOME")}, nil
	}
	u, err := user.Lookup(m.cfg.User)
	if err != nil {
		return creds{}, fmt.Errorf("%w: user %q: %v", ErrUnavailable, m.cfg.User, err)
	}
	uid, err1 := strconv.ParseUint(u.Uid, 10, 32)
	gid, err2 := strconv.ParseUint(u.Gid, 10, 32)
	if err1 != nil || err2 != nil || uid == 0 {
		return creds{}, fmt.Errorf("%w: user %q must be a non-root user", ErrUnavailable, m.cfg.User)
	}
	return creds{cred: &syscall.Credential{Uid: uint32(uid), Gid: uint32(gid), Groups: []uint32{}}, home: u.HomeDir}, nil
}

// Start starts the browser and waits until its CDP endpoint is ready. It
// returns already=true if the browser runs or restarts already.
func (m *Manager) Start(ctx context.Context) (st Status, already bool, err error) {
	if len(m.cfg.ChromeBins) == 0 {
		return Status{}, false, fmt.Errorf("%w: no Chromium binary configured", ErrUnavailable)
	}
	if err := m.lockOp(ctx); err != nil {
		return Status{}, false, err
	}
	defer m.unlockOp()
	m.mu.Lock()
	running := m.sup != nil
	m.mu.Unlock()
	if running {
		return m.Status(), true, nil
	}
	chrome := ""
	for _, bin := range m.cfg.ChromeBins {
		if st, err := os.Stat(bin); err == nil && st.Mode().IsRegular() {
			chrome = bin
			break
		}
	}
	if chrome == "" {
		return Status{}, false, fmt.Errorf("%w: no Chromium binary in %v", ErrUnavailable, m.cfg.ChromeBins)
	}
	if _, err := os.Stat(m.cfg.XvfbBin); err != nil {
		return Status{}, false, fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	cr, err := m.lookupUser()
	if err != nil {
		return Status{}, false, err
	}
	if m.cfg.CgroupRoot != "" && !m.limitSet {
		if err := limitCgroup(m.cfg.CgroupRoot, m.cfg.MemoryMax); err != nil {
			return Status{}, false, fmt.Errorf("%w: memory limit: %v", ErrStartFailed, err)
		}
		m.limitSet = true
	}
	p := m.profile(cr)
	if err := p.resetLive(ctx); err != nil {
		return Status{}, false, fmt.Errorf("%w: %v", ErrProfile, err)
	}
	ln, err := m.cfg.Listen(m.cfg.VsockPort)
	if err != nil {
		return Status{}, false, fmt.Errorf("%w: listen on CDP port %d: %v", ErrStartFailed, m.cfg.VsockPort, err)
	}
	fwd := newForwarder(ln, net.JoinHostPort("127.0.0.1", strconv.Itoa(m.cfg.CDPPort)), m.cfg.Log)
	s := &supervisor{m: m, chrome: chrome, cr: cr, live: p.live(), fwd: fwd, stop: make(chan chan bool), done: make(chan struct{})}
	m.update(func(st *Status) {
		*st = Status{State: Starting, VsockPort: m.cfg.VsockPort, ProfileDir: m.cfg.ProfileDir, MemoryMax: st.MemoryMax}
	})
	m.mu.Lock()
	m.sup = s
	m.mu.Unlock()
	ready := make(chan error, 1)
	go s.loop(ready)
	select {
	case err = <-ready:
	case <-ctx.Done():
		// The first launch has its own timeout; stop what it started.
		m.stopSupervisor(s)
		err = ctx.Err()
	}
	if err != nil {
		<-s.done
		return m.Status(), false, err
	}
	return m.Status(), false, nil
}

// Stop stops the browser. After a clean exit it saves the profile. If ctx
// ends first, Stop returns without the save and the saved profile stays as
// it was. Chromium's shutdown has its own limit, StopTimeout.
func (m *Manager) Stop(ctx context.Context) (StopResult, error) {
	if err := m.lockOp(ctx); err != nil {
		return StopResult{}, err
	}
	defer m.unlockOp()
	m.mu.Lock()
	s := m.sup
	m.mu.Unlock()
	if s == nil {
		return StopResult{}, nil
	}
	clean := m.stopSupervisor(s)
	res := StopResult{WasRunning: true, Clean: clean}
	if !clean {
		return res, nil
	}
	n, err := m.profile(s.cr).save(ctx)
	if err != nil {
		res.ProfileError = err.Error()
		m.cfg.Log.Warn("browser profile not saved", "err", err)
		return res, nil
	}
	res.ProfileSaved, res.ProfileBytes = true, n
	m.cfg.Log.Info("browser profile saved", "dir", m.cfg.ProfileDir, "bytes", n)
	return res, nil
}

// stopSupervisor asks the supervisor to stop and waits for it. It returns
// true if Chromium exited cleanly.
func (m *Manager) stopSupervisor(s *supervisor) bool {
	reply := make(chan bool, 1)
	clean := false
	select {
	case s.stop <- reply:
		clean = <-reply
	case <-s.done:
	}
	<-s.done
	return clean
}

func (m *Manager) profile(cr creds) *profile {
	return &profile{saved: m.cfg.ProfileDir, work: m.cfg.WorkDir, cred: cr.cred, max: m.cfg.ProfileMaxBytes}
}

// supervisor runs the browser from Start to Stop and restarts it after a
// crash.
type supervisor struct {
	m      *Manager
	chrome string
	cr     creds
	live   string
	fwd    *forwarder
	stop   chan chan bool
	done   chan struct{}
}

func (s *supervisor) loop(ready chan<- error) {
	m := s.m
	final := Stopped
	defer func() {
		s.fwd.close()
		m.mu.Lock()
		m.sup = nil
		m.st.State, m.st.PID, m.st.CDPPath = final, 0, ""
		m.mu.Unlock()
		close(s.done)
	}()
	first := true
	fast := 0
	backoff := m.cfg.BackoffMin
	for {
		r, err := s.launch()
		if err != nil {
			if first {
				m.update(func(st *Status) { st.LastError = err.Error() })
				ready <- fmt.Errorf("%w: %v", ErrStartFailed, err)
				return
			}
			m.cfg.Log.Warn("browser restart failed", "err", err)
			m.update(func(st *Status) { st.LastError = err.Error() })
			fast++
		} else {
			m.update(func(st *Status) {
				st.State, st.PID, st.CDPPath, st.StartedAt, st.StartDuration = Running, r.chromePID(), r.wsPath, r.started, r.startDur
			})
			if first {
				first = false
				ready <- nil
			}
			select {
			case reply := <-s.stop:
				m.update(func(st *Status) { st.State = Stopping })
				reply <- r.shutdown(m.cfg.StopTimeout)
				return
			case <-r.exited:
				why := r.exitReason()
				r.kill()
				ran := time.Since(r.started)
				if ran >= m.cfg.StableAfter {
					fast, backoff = 0, m.cfg.BackoffMin
				}
				fast++
				m.cfg.Log.Warn("browser exited; restarting", "reason", why, "ran", ran.Round(time.Millisecond))
				m.update(func(st *Status) { st.Restarts++; st.LastError = why })
			}
		}
		if fast >= m.cfg.MaxFastCrashes {
			m.cfg.Log.Error("browser keeps crashing; giving up until the next BrowserStart", "crashes", fast)
			final = Failed
			return
		}
		m.update(func(st *Status) { st.State, st.PID, st.CDPPath = Restarting, 0, "" })
		t := time.NewTimer(backoff)
		select {
		case <-t.C:
		case reply := <-s.stop:
			t.Stop()
			reply <- false
			return
		}
		backoff = min(backoff*2, m.cfg.BackoffMax)
		m.update(func(st *Status) { st.State = Starting })
		// Chromium refuses a profile that another host's lock holds.
		removeLocks(s.live)
	}
}

// proc is one supervised process (Xvfb or Chromium) in its kill group.
type proc struct {
	cmd    *exec.Cmd
	group  execs.Group
	waited chan struct{}
	tail   *tailBuf
	out    *os.File // read end of stdout+stderr
}

func (p *proc) kill() {
	if p == nil {
		return
	}
	_ = p.group.Kill()
}

// release waits for the process, closes its output and removes its group.
func (p *proc) release(log *slog.Logger) {
	if p == nil {
		return
	}
	<-p.waited
	_ = p.out.Close()
	if err := p.group.Close(); err != nil {
		log.Warn("remove browser kill group", "err", err)
	}
}

type run struct {
	m            *Manager
	xvfb, chrome *proc
	wsPath       string
	started      time.Time
	startDur     time.Duration
	exited       chan struct{} // closed when Xvfb or Chromium exits
	exitOnce     sync.Once
}

func (r *run) chromePID() int { return r.chrome.cmd.Process.Pid }

func (r *run) exitReason() string {
	for _, p := range []struct {
		name string
		p    *proc
	}{{"chromium", r.chrome}, {"xvfb", r.xvfb}} {
		if p.p == nil {
			continue
		}
		select {
		case <-p.p.waited:
			return fmt.Sprintf("%s exited (%s): %s", p.name, p.p.cmd.ProcessState, p.p.tail.String())
		default:
		}
	}
	return "unknown exit"
}

// kill stops both groups and releases them.
func (r *run) kill() {
	r.chrome.kill()
	r.xvfb.kill()
	r.chrome.release(r.m.cfg.Log)
	r.xvfb.release(r.m.cfg.Log)
}

// shutdown closes Chromium with the CDP command Browser.close (SIGTERM if
// that fails) and waits up to timeout for it to exit, then kills what is
// left. It returns true if Chromium exited in time after Browser.close.
func (r *run) shutdown(timeout time.Duration) bool {
	clean := false
	select {
	case <-r.chrome.waited:
		// It already exited: no clean shutdown of the profile.
	default:
		t := time.NewTimer(timeout)
		addr := net.JoinHostPort("127.0.0.1", strconv.Itoa(r.m.cfg.CDPPort))
		if err := cdpClose(addr, r.wsPath, min(timeout, 5*time.Second)); err != nil {
			// SIGTERM ends Chromium without committing its profile stores.
			r.m.cfg.Log.Warn("Browser.close failed; sending SIGTERM (the profile is not saved)", "err", err)
			_ = r.chrome.cmd.Process.Signal(syscall.SIGTERM)
		} else {
			clean = true
		}
		select {
		case <-r.chrome.waited:
		case <-t.C:
			clean = false
			r.m.cfg.Log.Warn("chromium did not exit; killing it", "timeout", timeout)
		}
		t.Stop()
	}
	r.kill()
	return clean
}

func (s *supervisor) launch() (*run, error) {
	m := s.m
	m.mu.Lock()
	m.runSeq++
	n := m.runSeq
	m.mu.Unlock()
	t0 := time.Now()
	r := &run{m: m, started: t0, exited: make(chan struct{})}
	deadline := time.NewTimer(m.cfg.StartTimeout)
	defer deadline.Stop()

	prepareX11(m.cfg.TmpDir, m.cfg.Display)
	// -displayfd writes the display number when Xvfb accepts clients.
	dr, dw, err := os.Pipe()
	if err != nil {
		return nil, err
	}
	xvfb, err := s.spawn(fmt.Sprintf("xvfb-%d", n), m.cfg.XvfbBin,
		[]string{":" + strconv.Itoa(m.cfg.Display), "-screen", "0", m.cfg.Screen, "-nolisten", "tcp", "-displayfd", "3"},
		nil, []*os.File{dw}, r)
	_ = dw.Close()
	if err != nil {
		_ = dr.Close()
		return nil, fmt.Errorf("start xvfb: %w", err)
	}
	r.xvfb = xvfb
	xready := make(chan error, 1)
	go func() {
		line, err := bufio.NewReader(dr).ReadString('\n')
		if err != nil {
			xready <- fmt.Errorf("xvfb closed -displayfd: %v", err)
			return
		}
		if strings.TrimSpace(line) != strconv.Itoa(m.cfg.Display) {
			xready <- fmt.Errorf("xvfb display %q", strings.TrimSpace(line))
			return
		}
		xready <- nil
	}()
	fail := func(err error) (*run, error) {
		r.chrome.kill()
		r.xvfb.kill()
		r.chrome.release(m.cfg.Log)
		r.xvfb.release(m.cfg.Log)
		return nil, err
	}
	select {
	case err = <-xready:
	case <-deadline.C:
		err = fmt.Errorf("xvfb not ready after %s", m.cfg.StartTimeout)
	}
	_ = dr.Close()
	if err != nil {
		return fail(fmt.Errorf("%w: %s", err, xvfb.tail.String()))
	}

	env := []string{"DISPLAY=:" + strconv.Itoa(m.cfg.Display)}
	if s.cr.home != "" {
		env = append(env, "HOME="+s.cr.home)
	}
	chrome, err := s.spawn(fmt.Sprintf("chrome-%d", n), s.chrome, chromeArgs(m.cfg, s.live), env, nil, r)
	if err != nil {
		return fail(fmt.Errorf("start chromium: %w", err))
	}
	r.chrome = chrome
	select {
	case ws := <-chrome.tail.ready:
		u, err := url.Parse(ws)
		if err != nil || u.Path == "" {
			return fail(fmt.Errorf("chromium DevTools URL %q", ws))
		}
		r.wsPath = u.Path
	case <-r.exited:
		return fail(errors.New(r.exitReason()))
	case <-deadline.C:
		return fail(fmt.Errorf("chromium DevTools not ready after %s: %s", m.cfg.StartTimeout, chrome.tail.String()))
	}
	r.startDur = time.Since(t0)
	m.cfg.Log.Info("browser ready", "pid", r.chromePID(), "start", r.startDur.Round(time.Millisecond), "cdp", r.wsPath)
	return r, nil
}

func chromeArgs(cfg Config, live string) []string {
	w, h := "1280", "800"
	if parts := strings.Split(cfg.Screen, "x"); len(parts) >= 2 {
		w, h = parts[0], parts[1]
	}
	args := []string{
		"--user-data-dir=" + live,
		"--remote-debugging-address=127.0.0.1",
		"--remote-debugging-port=" + strconv.Itoa(cfg.CDPPort),
		"--no-first-run",
		"--no-default-browser-check",
		"--disable-gpu",
		"--password-store=basic",
		"--window-position=0,0",
		"--window-size=" + w + "," + h,
	}
	// Chromium ignores the *_PROXY env: pass the egress proxy as a flag.
	if p := proxyFromEnv(cfg.Env); p != "" {
		args = append(args, "--proxy-server="+p, "--proxy-bypass-list=127.0.0.1;localhost;[::1]")
	}
	return append(args, "about:blank")
}

func proxyFromEnv(env []string) string {
	vals := map[string]string{}
	for _, kv := range env {
		if k, v, ok := strings.Cut(kv, "="); ok {
			vals[k] = v
		}
	}
	for _, k := range []string{"HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"} {
		if v := vals[k]; v != "" {
			return v
		}
	}
	return ""
}

// spawn starts one process in a new kill group with the browser user and
// env. Its stdout and stderr go to one pipe, read into a tail buffer.
func (s *supervisor) spawn(group, bin string, args, env []string, extra []*os.File, r *run) (*proc, error) {
	g, err := s.m.cfg.Isolator.NewGroup(group)
	if err != nil {
		return nil, fmt.Errorf("kill group: %w", err)
	}
	cmd := exec.Command(bin, args...)
	cmd.Env = append(append([]string{}, s.m.cfg.Env...), env...)
	cmd.Dir = "/"
	cmd.ExtraFiles = extra
	g.Prepare(cmd)
	if s.cr.cred != nil {
		if cmd.SysProcAttr == nil {
			cmd.SysProcAttr = &syscall.SysProcAttr{}
		}
		cmd.SysProcAttr.Credential = s.cr.cred
	}
	pr, pw, err := os.Pipe()
	if err != nil {
		_ = g.Close()
		return nil, err
	}
	cmd.Stdout, cmd.Stderr = pw, pw
	if err := cmd.Start(); err != nil {
		_ = pr.Close()
		_ = pw.Close()
		_ = g.Close()
		return nil, err
	}
	_ = pw.Close()
	g.Started(cmd.Process.Pid)
	p := &proc{cmd: cmd, group: g, waited: make(chan struct{}), tail: newTail(), out: pr}
	go func() { _, _ = io.Copy(p.tail, pr) }()
	go func() {
		_ = cmd.Wait()
		close(p.waited)
		r.exitOnce.Do(func() { close(r.exited) })
	}()
	return p, nil
}

// removeLocks deletes Chromium's singleton files: a killed Chromium leaves
// them, and a new one may refuse the profile.
func removeLocks(live string) {
	for _, f := range []string{"SingletonLock", "SingletonSocket", "SingletonCookie", "DevToolsActivePort"} {
		_ = os.Remove(filepath.Join(live, f))
	}
}

// tailBuf keeps the last bytes of a process's output and reports the
// DevTools URL that Chromium prints when its CDP endpoint is ready.
type tailBuf struct {
	mu    sync.Mutex
	buf   []byte
	line  []byte
	ready chan string
	sent  bool
}

const tailMax = 2048

func newTail() *tailBuf { return &tailBuf{ready: make(chan string, 1)} }

const devtoolsPrefix = "DevTools listening on "

func (t *tailBuf) Write(p []byte) (int, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.buf = append(t.buf, p...)
	if len(t.buf) > tailMax {
		t.buf = append([]byte(nil), t.buf[len(t.buf)-tailMax:]...)
	}
	if t.sent {
		return len(p), nil
	}
	t.line = append(t.line, p...)
	for {
		i := strings.IndexByte(string(t.line), '\n')
		if i < 0 {
			if len(t.line) > 4096 {
				t.line = t.line[len(t.line)-4096:]
			}
			return len(p), nil
		}
		l := strings.TrimSpace(string(t.line[:i]))
		t.line = t.line[i+1:]
		if _, ws, ok := strings.Cut(l, devtoolsPrefix); ok {
			t.ready <- ws
			t.sent, t.line = true, nil
			return len(p), nil
		}
	}
}

func (t *tailBuf) String() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return strings.TrimSpace(string(t.buf))
}
