// Package browser runs the one long-lived headless Chrome of a guest VM and
// the browser service that drives it. The daemon owns both, outside the
// per-execution cgroups, so they outlive the command that asked for them.
// Clients attach to Chrome over CDP and to the service over its socket.
package browser

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
)

// Defaults for the zero Config fields.
const (
	DefaultBinary       = "/opt/chrome/chrome"
	DefaultStartTimeout = 20 * time.Second
	defaultSocketDir    = "/run/onyx-browser"
)

// The browser service and the Node that runs it, in the runtime image.
const (
	ServiceScript = "/opt/onyx/browser-service/main.ts"
	Node          = "/usr/local/bin/node"
)

// socketName is the service socket in Config.SocketDir.
const socketName = "service.sock"

const (
	stderrTailBytes = 8 << 10
	probeTimeout    = time.Second
	closeTimeout    = 5 * time.Second
	stopTimeout     = 5 * time.Second
	pollInterval    = 100 * time.Millisecond
)

// Config configures a Browser.
type Config struct {
	Binary string
	// ServiceScript is the browser service that Node runs after Chrome
	// answers. Empty: no service.
	ServiceScript string
	// Node runs ServiceScript.
	Node string
	// SocketDir holds the service socket. The daemon makes it (mode 0700,
	// owned by Credential).
	SocketDir string
	// SessionsRoot is the service's ONYX_SESSIONS_ROOT.
	SessionsRoot string
	// Isolator must not be the executions' isolator: a cgroup root of its
	// own keeps the browser out of the execution records and kills.
	Isolator execs.Isolator
	// Credential runs Chrome and the service as this user. Nil: the daemon user.
	Credential   *syscall.Credential
	StartTimeout time.Duration
	Log          *slog.Logger
}

// Browser starts and stops one Chrome process and its service. It is safe
// for concurrent use.
type Browser struct {
	cfg    Config
	client *http.Client
	mu     sync.Mutex
	// launches names each launch's group: a group that failed to close must
	// not block the next launch. Daemon start-up removes leftovers.
	launches int
	run      *running // nil: no browser
}

// proc is a started process: Chrome, or the browser service.
type proc struct {
	pid    int
	done   chan struct{} // closed when the process exits
	stderr *tail
}

func (p *proc) exited() bool {
	select {
	case <-p.done:
		return true
	default:
		return false
	}
}

type running struct {
	proc
	group   execs.Group
	port    int // DevTools port; set once it answers
	profile string
	start   time.Time
	pipe    *os.File // write end of Chrome's --remote-debugging-pipe input
	// svc is the service. Setsid makes it the leader of its own process
	// group in Chrome's group. Nil: no service.
	svc *proc
}

// New returns a Browser with the defaults for zero fields.
func New(cfg Config) *Browser {
	if cfg.Binary == "" {
		cfg.Binary = DefaultBinary
	}
	if cfg.StartTimeout <= 0 {
		cfg.StartTimeout = DefaultStartTimeout
	}
	if cfg.Log == nil {
		cfg.Log = slog.Default()
	}
	if cfg.SocketDir == "" {
		cfg.SocketDir = defaultSocketDir
	}
	return &Browser{cfg: cfg, client: &http.Client{Timeout: probeTimeout}}
}

// SocketPath is the service socket.
func (b *Browser) SocketPath() string {
	return filepath.Join(b.cfg.SocketDir, socketName)
}

// Start makes sure that Chrome runs with profileDir and answers on its
// DevTools port, and that the service accepts connections. Chrome with
// another profile dir is stopped first. started is true when this call
// launched Chrome. env is the environment of both.
func (b *Browser) Start(ctx context.Context, profileDir string, env []string) (port int, started bool, err error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	r := b.run
	if r == nil || r.exited() || r.profile != profileDir || !b.probe(ctx, r.port) {
		// A canceled call says nothing about the browser: keep it.
		if err := ctx.Err(); err != nil {
			return 0, false, err
		}
		if b.run != nil {
			if err := b.stopLocked(); err != nil {
				b.cfg.Log.Warn("stop the old browser", "err", err)
			}
		}
		if r, err = b.launch(profileDir, env); err != nil {
			return 0, false, err
		}
		b.run = r
		answers := func(ctx context.Context) bool {
			r.port = activePort(r.profile, r.start)
			return r.port != 0 && b.probe(ctx, r.port)
		}
		if err := b.waitUntil(ctx, r.done, "chrome", answers); err != nil {
			return 0, false, withStderr(errors.Join(err, b.stopLocked()), "chrome", r.stderr)
		}
		started = true
		b.cfg.Log.Info("browser started", "pid", r.pid, "port", r.port, "profile", profileDir)
	}
	// A failed service leaves Chrome up; the next Start tries the service again.
	if err := b.ensureService(ctx, r, env); err != nil {
		return 0, started, err
	}
	return r.port, started, nil
}

// Stop closes Chrome and ends every process in its group. stopped is false
// when no browser ran.
func (b *Browser) Stop() (stopped bool, err error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.run == nil {
		return false, nil
	}
	return true, b.stopLocked()
}

func (b *Browser) stopLocked() error {
	r := b.run
	b.run = nil
	svcErr := b.stopService(r)
	// Closing the DevTools pipe makes Chrome exit cleanly. A kill loses the
	// cookies that it has not written to the profile yet.
	err := r.pipe.Close()
	select {
	case <-r.done:
	case <-time.After(closeTimeout):
		err = errors.Join(err, r.group.Kill())
		select {
		case <-r.done:
		case <-time.After(stopTimeout):
			err = errors.Join(err, fmt.Errorf("chrome pid %d did not exit in %v", r.pid, stopTimeout))
		}
	}
	return errors.Join(svcErr, err, r.group.Kill(), r.group.Close())
}

func (b *Browser) launch(profile string, env []string) (*running, error) {
	b.launches++
	g, err := b.cfg.Isolator.NewGroup("chrome-" + strconv.Itoa(b.launches))
	if err != nil {
		return nil, fmt.Errorf("kill group: %w", err)
	}
	pipeR, pipeW, err := os.Pipe()
	if err != nil {
		_ = g.Close()
		return nil, err
	}
	defer func() { _ = pipeR.Close() }()
	devNull, err := os.OpenFile(os.DevNull, os.O_WRONLY, 0)
	if err != nil {
		_ = pipeW.Close()
		_ = g.Close()
		return nil, err
	}
	defer func() { _ = devNull.Close() }()
	cmd := &exec.Cmd{
		Path: b.cfg.Binary, Args: append([]string{b.cfg.Binary}, chromeArgs(profile, env)...),
		Env: env,
		// Chrome reads DevTools messages from fd 3 and writes replies to fd 4.
		ExtraFiles: []*os.File{pipeR, devNull},
	}
	start := time.Now()
	p, err := b.startProc(g, cmd)
	if err != nil {
		_ = pipeW.Close()
		_ = g.Close()
		return nil, fmt.Errorf("start chrome: %w", err)
	}
	g.Started(p.pid)
	return &running{proc: *p, group: g, profile: profile, start: start, pipe: pipeW}, nil
}

// startProc starts cmd in group g, as the command user, in "/" with stdout
// discarded and the stderr tail kept.
func (b *Browser) startProc(g execs.Group, cmd *exec.Cmd) (*proc, error) {
	stderr := &tail{max: stderrTailBytes}
	cmd.Dir, cmd.Stdout, cmd.Stderr = "/", io.Discard, stderr
	b.prepare(g, cmd)
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	p := &proc{pid: cmd.Process.Pid, done: make(chan struct{}), stderr: stderr}
	go func() {
		_ = cmd.Wait()
		close(p.done)
	}()
	return p, nil
}

// prepare puts cmd in group g, as the command user.
func (b *Browser) prepare(g execs.Group, cmd *exec.Cmd) {
	g.Prepare(cmd)
	if b.cfg.Credential != nil {
		if cmd.SysProcAttr == nil {
			cmd.SysProcAttr = &syscall.SysProcAttr{}
		}
		cmd.SysProcAttr.Credential = b.cfg.Credential
	}
}

// waitUntil polls ready until it reports true. It fails when done closes
// first or the start timeout ends. what names the process that done tracks.
func (b *Browser) waitUntil(ctx context.Context, done <-chan struct{}, what string, ready func(context.Context) bool) error {
	ctx, cancel := context.WithTimeout(ctx, b.cfg.StartTimeout)
	defer cancel()
	tick := time.NewTicker(pollInterval)
	defer tick.Stop()
	for !ready(ctx) {
		select {
		case <-done:
			return fmt.Errorf("%s exited before it was ready", what)
		case <-ctx.Done():
			return fmt.Errorf("%s was not ready: %w", what, ctx.Err())
		case <-tick.C:
		}
	}
	return nil
}

// withStderr adds the stderr tail of the named process to err.
func withStderr(err error, name string, t *tail) error {
	if s := strings.TrimSpace(t.String()); s != "" {
		return fmt.Errorf("%w; %s stderr: %s", err, name, s)
	}
	return err
}

// activePort reads the port that Chrome wrote to DevToolsActivePort in the
// profile. A file from an earlier launch stays after Chrome exits, so only a
// file written after start counts. The command user owns the profile, so
// the file may be a FIFO or a link: open it without blocking or following.
func activePort(profile string, start time.Time) int {
	path := filepath.Join(profile, "DevToolsActivePort")
	f, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NONBLOCK|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return 0
	}
	defer func() { _ = f.Close() }()
	fi, err := f.Stat()
	// File times come from the kernel's coarse clock, a few ms behind time.Now.
	if err != nil || !fi.Mode().IsRegular() || fi.ModTime().Before(start.Add(-time.Second)) {
		return 0
	}
	data, err := io.ReadAll(io.LimitReader(f, 256))
	if err != nil {
		return 0
	}
	line, _, _ := strings.Cut(string(data), "\n")
	port, err := strconv.Atoi(strings.TrimSpace(line))
	if err != nil || port <= 0 || port > 65535 {
		return 0
	}
	return port
}

// probe reports whether the DevTools endpoint on port answers.
func (b *Browser) probe(ctx context.Context, port int) bool {
	url := "http://127.0.0.1:" + strconv.Itoa(port) + "/json/version"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return false
	}
	resp, err := b.client.Do(req)
	if err != nil {
		return false
	}
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 64<<10))
	_ = resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// chromeArgs returns Chrome's arguments, without the program name.
func chromeArgs(profile string, env []string) []string {
	args := []string{
		"--headless",
		"--remote-debugging-address=127.0.0.1",
		// Port 0: Chrome picks a free port, so a process that holds a fixed one
		// cannot pass for this browser.
		"--remote-debugging-port=0",
		"--remote-debugging-pipe",
		"--user-data-dir=" + profile,
		// The guest kernel has no user namespaces, so Chrome's sandbox cannot start.
		"--no-sandbox",
		"--no-first-run",
		"--no-default-browser-check",
		"--disable-dev-shm-usage",
		"--disable-gpu",
		"--window-size=1280,800",
	}
	// Chrome ignores *_PROXY; the VM reaches the network only through the egress relay.
	if p := lookupEnv(env, "HTTPS_PROXY"); p != "" {
		args = append(args, "--proxy-server="+p)
	} else if p := lookupEnv(env, "HTTP_PROXY"); p != "" {
		args = append(args, "--proxy-server="+p)
	}
	return append(args, "about:blank")
}

// lookupEnv returns the last value of key in env.
func lookupEnv(env []string, key string) string {
	v := ""
	for _, kv := range env {
		if k, val, ok := strings.Cut(kv, "="); ok && k == key {
			v = val
		}
	}
	return v
}

// tail keeps the last max bytes written to it.
type tail struct {
	mu  sync.Mutex
	buf []byte
	max int
}

func (t *tail) Write(p []byte) (int, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.buf = append(t.buf, p...)
	if over := len(t.buf) - t.max; over > 0 {
		t.buf = append(t.buf[:0], t.buf[over:]...)
	}
	return len(p), nil
}

func (t *tail) String() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return string(t.buf)
}
