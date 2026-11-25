// Package browser runs the one long-lived headless Chrome of a guest VM.
// The daemon owns it, outside the per-execution cgroups, so it outlives the
// command that asked for it. Clients attach to it over CDP.
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
)

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
	// ProfileDir is the persistent --user-data-dir.
	ProfileDir string
	// Isolator must not be the executions' isolator: a cgroup root of its
	// own keeps the browser out of the execution records and kills.
	Isolator execs.Isolator
	// Credential runs Chrome as this user. Nil: the daemon user.
	Credential   *syscall.Credential
	StartTimeout time.Duration
	Log          *slog.Logger
}

// Browser starts and stops one Chrome process. It is safe for concurrent use.
type Browser struct {
	cfg    Config
	client *http.Client
	mu     sync.Mutex
	run    *running // nil: no browser
}

type running struct {
	group  execs.Group
	pid    int
	port   int // DevTools port; set once it answers
	start  time.Time
	pipe   *os.File // write end of Chrome's --remote-debugging-pipe input
	done   chan struct{}
	stderr *tail
}

func (r *running) exited() bool {
	select {
	case <-r.done:
		return true
	default:
		return false
	}
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
	return &Browser{cfg: cfg, client: &http.Client{Timeout: probeTimeout}}
}

// Start makes sure that Chrome runs and answers on its DevTools port.
// started is true when this call launched it. env is Chrome's environment.
func (b *Browser) Start(ctx context.Context, env []string) (port int, started bool, err error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.run != nil && !b.run.exited() && b.probe(ctx, b.run.port) {
		return b.run.port, false, nil
	}
	// A canceled call says nothing about the browser: keep it.
	if err := ctx.Err(); err != nil {
		return 0, false, err
	}
	if b.run != nil {
		if err := b.stopLocked(); err != nil {
			b.cfg.Log.Warn("stop the old browser", "err", err)
		}
	}
	r, err := b.launch(env)
	if err != nil {
		return 0, false, err
	}
	b.run = r
	if err := b.waitReady(ctx, r); err != nil {
		err = errors.Join(err, b.stopLocked())
		if tail := strings.TrimSpace(r.stderr.String()); tail != "" {
			err = fmt.Errorf("%w; chrome stderr: %s", err, tail)
		}
		return 0, false, err
	}
	b.cfg.Log.Info("browser started", "pid", r.pid, "port", r.port)
	return r.port, true, nil
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
	return errors.Join(err, r.group.Kill(), r.group.Close())
}

func (b *Browser) launch(env []string) (*running, error) {
	g, err := b.cfg.Isolator.NewGroup("chrome")
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
	stderr := &tail{max: stderrTailBytes}
	cmd := &exec.Cmd{
		Path: b.cfg.Binary, Args: append([]string{b.cfg.Binary}, chromeArgs(b.cfg, env)...),
		Dir: "/", Env: env, Stdout: io.Discard, Stderr: stderr,
		// Chrome reads DevTools messages from fd 3 and writes replies to fd 4.
		ExtraFiles: []*os.File{pipeR, devNull},
	}
	g.Prepare(cmd)
	if b.cfg.Credential != nil {
		if cmd.SysProcAttr == nil {
			cmd.SysProcAttr = &syscall.SysProcAttr{}
		}
		cmd.SysProcAttr.Credential = b.cfg.Credential
	}
	start := time.Now()
	if err := cmd.Start(); err != nil {
		_ = pipeW.Close()
		_ = g.Close()
		return nil, fmt.Errorf("start chrome: %w", err)
	}
	g.Started(cmd.Process.Pid)
	r := &running{group: g, pid: cmd.Process.Pid, start: start, pipe: pipeW, done: make(chan struct{}), stderr: stderr}
	go func() {
		_ = cmd.Wait()
		close(r.done)
	}()
	return r, nil
}

func (b *Browser) waitReady(ctx context.Context, r *running) error {
	ctx, cancel := context.WithTimeout(ctx, b.cfg.StartTimeout)
	defer cancel()
	tick := time.NewTicker(pollInterval)
	defer tick.Stop()
	for {
		if port := b.activePort(r.start); port != 0 && b.probe(ctx, port) {
			r.port = port
			return nil
		}
		select {
		case <-r.done:
			return errors.New("chrome exited before its DevTools endpoint answered")
		case <-ctx.Done():
			return fmt.Errorf("chrome DevTools endpoint did not answer: %w", ctx.Err())
		case <-tick.C:
		}
	}
}

// activePort reads the port that Chrome wrote to DevToolsActivePort in the
// profile. A file from an earlier launch stays after Chrome exits, so only a
// file written after start counts. The command user owns the profile, so
// the file may be a FIFO or a link: open it without blocking or following.
func (b *Browser) activePort(start time.Time) int {
	path := filepath.Join(b.cfg.ProfileDir, "DevToolsActivePort")
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
func chromeArgs(cfg Config, env []string) []string {
	args := []string{
		"--headless",
		"--remote-debugging-address=127.0.0.1",
		// Port 0: Chrome picks a free port, so a process that holds a fixed one
		// cannot pass for this browser.
		"--remote-debugging-port=0",
		"--remote-debugging-pipe",
		"--user-data-dir=" + cfg.ProfileDir,
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
