package browser

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
)

// The test binary is also the fake Xvfb and the fake Chromium
// (BROWSER_FAKE=1). FAKE_CTL is a dir of control files.
func TestMain(m *testing.M) {
	if os.Getenv("BROWSER_FAKE") == "1" {
		fakeMain()
		return
	}
	os.Exit(m.Run())
}

func ctl(name string) bool {
	_, err := os.Stat(filepath.Join(os.Getenv("FAKE_CTL"), name))
	return err == nil
}

func fakeMain() {
	args := os.Args[1:]
	if len(args) > 0 && strings.HasPrefix(args[0], ":") {
		fakeXvfb(args)
		return
	}
	fakeChrome(args)
}

func fakeXvfb(args []string) {
	if ctl("xvfb-fail") {
		fmt.Fprintln(os.Stderr, "fake xvfb: cannot open display")
		os.Exit(1)
	}
	fd := os.NewFile(3, "displayfd")
	_, _ = fmt.Fprintf(fd, "%s\n", strings.TrimPrefix(args[0], ":"))
	_ = fd.Close()
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGTERM)
	<-sig
}

func fakeChrome(args []string) {
	var udd string
	port := 0
	for _, a := range args {
		if v, ok := strings.CutPrefix(a, "--user-data-dir="); ok {
			udd = v
		}
		if v, ok := strings.CutPrefix(a, "--remote-debugging-port="); ok {
			port, _ = strconv.Atoi(v)
		}
	}
	if os.Getenv("DISPLAY") == "" || udd == "" {
		fmt.Fprintln(os.Stderr, "fake chrome: no DISPLAY or profile")
		os.Exit(2)
	}
	// Each run counts itself in the profile, plus a cache file and a lock.
	if _, err := os.Lstat(filepath.Join(udd, "SingletonLock")); err == nil {
		fmt.Fprintln(os.Stderr, "fake chrome: profile is locked")
		os.Exit(21)
	}
	_ = os.Symlink("sandbox-123", filepath.Join(udd, "SingletonLock"))
	def := filepath.Join(udd, "Default")
	_ = os.MkdirAll(filepath.Join(def, "Cache"), 0o700)
	_ = os.WriteFile(filepath.Join(def, "Cache", "data_0"), make([]byte, 1024), 0o600)
	raw, _ := os.ReadFile(filepath.Join(def, "Cookies"))
	n, _ := strconv.Atoi(strings.TrimSpace(string(raw)))
	_ = os.WriteFile(filepath.Join(def, "Cookies"), []byte(strconv.Itoa(n+1)), 0o600)
	if ctl("big") {
		_ = os.WriteFile(filepath.Join(def, "Big"), make([]byte, 64<<10), 0o600)
	}

	if ctl("no-ready") {
		hang()
	}
	ln, err := net.Listen("tcp", "127.0.0.1:"+strconv.Itoa(port))
	if err != nil {
		fmt.Fprintln(os.Stderr, "fake chrome:", err)
		os.Exit(3)
	}
	exitClean := func() {
		_ = os.Remove(filepath.Join(udd, "SingletonLock"))
		_ = os.WriteFile(filepath.Join(def, "Preferences"), []byte(`{"exit_type":"Normal"}`), 0o600)
		os.Exit(0)
	}
	go func() {
		_ = http.Serve(ln, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !strings.HasPrefix(r.URL.Path, "/devtools/browser/") {
				_, _ = fmt.Fprintf(w, `{"Browser":"Fake/1","cookies":%d}`, n+1)
				return
			}
			if ctl("no-ws") || r.Header.Get("Origin") != "" {
				http.NotFound(w, r)
				return
			}
			conn, brw, err := w.(http.Hijacker).Hijack()
			if err != nil {
				return
			}
			defer func() { _ = conn.Close() }()
			_, _ = brw.WriteString("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
			_ = brw.Flush()
			hdr := make([]byte, 6)
			if _, err := io.ReadFull(brw, hdr); err != nil || hdr[1]&0x80 == 0 {
				return
			}
			msg := make([]byte, hdr[1]&0x7f)
			if _, err := io.ReadFull(brw, msg); err != nil {
				return
			}
			for i := range msg {
				msg[i] ^= hdr[2+i%4]
			}
			if strings.Contains(string(msg), `"Browser.close"`) && !ctl("hang-term") {
				exitClean()
			}
		}))
	}()
	fmt.Fprintf(os.Stderr, "\nDevTools listening on ws://127.0.0.1:%d/devtools/browser/fake-%d\n", port, os.Getpid())
	if ctl("crash-once") {
		_ = os.Remove(filepath.Join(os.Getenv("FAKE_CTL"), "crash-once"))
		time.Sleep(100 * time.Millisecond)
		os.Exit(1)
	}
	if ctl("crash-always") {
		time.Sleep(50 * time.Millisecond)
		os.Exit(1)
	}
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGTERM)
	<-sig
	if ctl("hang-term") {
		hang()
	}
	// SIGTERM: exit without the clean-shutdown file (as Chromium leaves its
	// stores uncommitted).
	os.Exit(0)
}

// hang blocks until SIGKILL (select{} alone is a runtime deadlock).
func hang() {
	signal.Ignore(syscall.SIGTERM)
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGUSR2)
	for {
		<-sig
	}
}

type fixture struct {
	m       *Manager
	ctlDir  string
	saved   string
	sockDir string
}

func freePort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = ln.Close() }()
	return ln.Addr().(*net.TCPAddr).Port
}

func newFixture(t *testing.T, mod func(*Config)) *fixture {
	t.Helper()
	dir := t.TempDir()
	// Unix socket paths must be short.
	sockDir, err := os.MkdirTemp("", "brw")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(sockDir) })
	f := &fixture{ctlDir: filepath.Join(dir, "ctl"), saved: filepath.Join(dir, "ws", "profile"), sockDir: sockDir}
	if err := os.Mkdir(f.ctlDir, 0o700); err != nil {
		t.Fatal(err)
	}
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cfg := Config{
		ChromeBins: []string{"/nonexistent/chrome", self}, XvfbBin: self, Display: 77, CDPPort: freePort(t), VsockPort: 9222,
		Listen: func(port uint32) (net.Listener, error) {
			return net.Listen("unix", filepath.Join(sockDir, strconv.Itoa(int(port))))
		},
		ProfileDir: f.saved, WorkDir: filepath.Join(dir, "work"), TmpDir: filepath.Join(dir, "tmp"),
		Env:          []string{"BROWSER_FAKE=1", "FAKE_CTL=" + f.ctlDir, "HTTPS_PROXY=http://127.0.0.1:3128"},
		Isolator:     execs.ProcessGroups{},
		StartTimeout: 10 * time.Second, StopTimeout: 2 * time.Second,
		BackoffMin: 10 * time.Millisecond, BackoffMax: 40 * time.Millisecond, MaxFastCrashes: 3,
		Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	if mod != nil {
		mod(&cfg)
	}
	m, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	f.m = m
	t.Cleanup(func() { _, _ = m.Stop(context.Background()) })
	return f
}

func (f *fixture) set(t *testing.T, name string, on bool) {
	t.Helper()
	p := filepath.Join(f.ctlDir, name)
	if on {
		if err := os.WriteFile(p, nil, 0o600); err != nil {
			t.Fatal(err)
		}
	} else {
		_ = os.Remove(p)
	}
}

// cdpGet sends a GET through the CDP listener, as node agent Dial does.
func (f *fixture) cdpGet(t *testing.T, path string) string {
	t.Helper()
	c, err := net.DialTimeout("unix", filepath.Join(f.sockDir, "9222"), 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	_ = c.SetDeadline(time.Now().Add(5 * time.Second))
	_, _ = fmt.Fprintf(c, "GET %s HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n", path)
	resp, err := http.ReadResponse(bufio.NewReader(c), nil)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	b, _ := io.ReadAll(resp.Body)
	return string(b)
}

// waitState waits for the state, driven by the supervisor's own timers.
func waitState(t *testing.T, m *Manager, want State) Status {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for {
		st := m.Status()
		if st.State == want {
			return st
		}
		if time.Now().After(deadline) {
			t.Fatalf("state %s, want %s (last error %q)", st.State, want, st.LastError)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

func readCookies(t *testing.T, dir string) string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(dir, "Default", "Cookies"))
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

func TestStartStopSavesProfile(t *testing.T) {
	f := newFixture(t, nil)
	ctx := context.Background()
	st, already, err := f.m.Start(ctx)
	if err != nil || already {
		t.Fatalf("start: %v already=%v", err, already)
	}
	if st.State != Running || !strings.HasPrefix(st.CDPPath, "/devtools/browser/fake-") || st.PID == 0 || st.StartDuration <= 0 {
		t.Fatalf("status %+v", st)
	}
	if body := f.cdpGet(t, "/json/version"); !strings.Contains(body, `"cookies":1`) {
		t.Fatalf("cdp: %q", body)
	}
	// A second Start returns the running browser.
	if st2, already, err := f.m.Start(ctx); err != nil || !already || st2.PID != st.PID {
		t.Fatalf("second start: %v %v %+v", err, already, st2)
	}

	r, err := f.m.Stop(ctx)
	if err != nil || !r.WasRunning || !r.Clean || !r.ProfileSaved || r.ProfileBytes == 0 {
		t.Fatalf("stop: %v %+v", err, r)
	}
	if got := readCookies(t, f.saved); got != "1" {
		t.Fatalf("saved cookies %q", got)
	}
	for _, p := range []string{"Default/Cache", "SingletonLock"} {
		if _, err := os.Lstat(filepath.Join(f.saved, p)); !errors.Is(err, os.ErrNotExist) {
			t.Errorf("%s saved: %v", p, err)
		}
	}
	if _, err := os.Stat(filepath.Join(f.saved, "Default", "Preferences")); err != nil {
		t.Errorf("clean-exit file not saved: %v", err)
	}
	if st := f.m.Status(); st.State != Stopped || st.PID != 0 {
		t.Fatalf("after stop %+v", st)
	}
	if _, err := net.Dial("unix", filepath.Join(f.sockDir, "9222")); err == nil {
		t.Fatal("CDP port still open after stop")
	}

	// The profile survives stop and start: the next run sees cookie 1.
	if _, _, err := f.m.Start(ctx); err != nil {
		t.Fatal(err)
	}
	if body := f.cdpGet(t, "/json/version"); !strings.Contains(body, `"cookies":2`) {
		t.Fatalf("profile not restored: %q", body)
	}
	if r, err := f.m.Stop(ctx); err != nil || !r.ProfileSaved {
		t.Fatalf("stop 2: %v %+v", err, r)
	}
	if got := readCookies(t, f.saved); got != "2" {
		t.Fatalf("saved cookies %q", got)
	}
	// Stop with no browser is not an error.
	if r, err := f.m.Stop(ctx); err != nil || r.WasRunning {
		t.Fatalf("idle stop: %v %+v", err, r)
	}
}

func TestUncleanStopKeepsSavedProfile(t *testing.T) {
	f := newFixture(t, nil)
	ctx := context.Background()
	if _, _, err := f.m.Start(ctx); err != nil {
		t.Fatal(err)
	}
	if r, err := f.m.Stop(ctx); err != nil || !r.ProfileSaved {
		t.Fatalf("stop: %v %+v", err, r)
	}
	f.set(t, "hang-term", true)
	if _, _, err := f.m.Start(ctx); err != nil {
		t.Fatal(err)
	}
	t0 := time.Now()
	r, err := f.m.Stop(ctx)
	if err != nil || !r.WasRunning || r.Clean || r.ProfileSaved {
		t.Fatalf("hung stop: %v %+v", err, r)
	}
	if d := time.Since(t0); d < 2*time.Second || d > 8*time.Second {
		t.Errorf("stop took %s, want about the 2 s stop timeout", d)
	}
	// The killed run (cookie 2) is not saved; the last clean one stays.
	if got := readCookies(t, f.saved); got != "1" {
		t.Fatalf("saved cookies %q", got)
	}
}

func TestStopFallsBackToSIGTERM(t *testing.T) {
	f := newFixture(t, nil)
	ctx := context.Background()
	if _, _, err := f.m.Start(ctx); err != nil {
		t.Fatal(err)
	}
	if r, err := f.m.Stop(ctx); err != nil || !r.ProfileSaved {
		t.Fatalf("stop: %v %+v", err, r)
	}
	// Browser.close fails: SIGTERM ends Chromium, but that is not a clean
	// stop, so the saved profile stays.
	f.set(t, "no-ws", true)
	if _, _, err := f.m.Start(ctx); err != nil {
		t.Fatal(err)
	}
	r, err := f.m.Stop(ctx)
	if err != nil || !r.WasRunning || r.Clean || r.ProfileSaved {
		t.Fatalf("stop without CDP: %v %+v", err, r)
	}
	if got := readCookies(t, f.saved); got != "1" {
		t.Fatalf("saved cookies %q", got)
	}
}

func TestCrashRestarts(t *testing.T) {
	f := newFixture(t, nil)
	f.set(t, "crash-once", true)
	if _, _, err := f.m.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	// The first run crashes; the supervisor starts a new one on the live
	// profile (cookie 2), with the stale lock removed.
	deadline := time.Now().Add(10 * time.Second)
	var st Status
	for time.Now().Before(deadline) {
		if st = f.m.Status(); st.Restarts == 1 && st.State == Running {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if st.Restarts != 1 || st.State != Running || !strings.Contains(st.LastError, "chromium exited") {
		t.Fatalf("after crash %+v", st)
	}
	if body := f.cdpGet(t, "/json/version"); !strings.Contains(body, `"cookies":2`) {
		t.Fatalf("restarted run: %q", body)
	}
	r, err := f.m.Stop(context.Background())
	if err != nil || !r.Clean || !r.ProfileSaved {
		t.Fatalf("stop: %v %+v", err, r)
	}
}

func TestCrashLoopFails(t *testing.T) {
	f := newFixture(t, nil)
	f.set(t, "crash-always", true)
	if _, _, err := f.m.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	st := waitState(t, f.m, Failed)
	if st.Restarts < 3 || st.PID != 0 {
		t.Fatalf("failed status %+v", st)
	}
	if _, err := net.Dial("unix", filepath.Join(f.sockDir, "9222")); err == nil {
		t.Fatal("CDP port open after Failed")
	}
	if r, err := f.m.Stop(context.Background()); err != nil || r.WasRunning {
		t.Fatalf("stop after failed: %v %+v", err, r)
	}
	// Start tries again.
	f.set(t, "crash-always", false)
	st, _, err := f.m.Start(context.Background())
	if err != nil || st.State != Running || st.Restarts != 0 {
		t.Fatalf("start after failed: %v %+v", err, st)
	}
}

func TestStartFailures(t *testing.T) {
	t.Run("xvfb", func(t *testing.T) {
		f := newFixture(t, nil)
		f.set(t, "xvfb-fail", true)
		_, _, err := f.m.Start(context.Background())
		if !errors.Is(err, ErrStartFailed) || !strings.Contains(err.Error(), "cannot open display") {
			t.Fatalf("err %v", err)
		}
		if st := f.m.Status(); st.State != Stopped || st.LastError == "" {
			t.Fatalf("status %+v", st)
		}
	})
	t.Run("not_ready", func(t *testing.T) {
		f := newFixture(t, func(c *Config) { c.StartTimeout = 300 * time.Millisecond })
		f.set(t, "no-ready", true)
		_, _, err := f.m.Start(context.Background())
		if !errors.Is(err, ErrStartFailed) || !strings.Contains(err.Error(), "not ready") {
			t.Fatalf("err %v", err)
		}
		// Nothing keeps running: the next Start works.
		f.set(t, "no-ready", false)
		if _, _, err := f.m.Start(context.Background()); err != nil {
			t.Fatal(err)
		}
	})
	t.Run("unavailable", func(t *testing.T) {
		m, err := New(Config{})
		if err != nil {
			t.Fatal(err)
		}
		if _, _, err := m.Start(context.Background()); !errors.Is(err, ErrUnavailable) {
			t.Fatalf("no binary: %v", err)
		}
		f := newFixture(t, func(c *Config) { c.XvfbBin = "/nonexistent/Xvfb" })
		if _, _, err := f.m.Start(context.Background()); !errors.Is(err, ErrUnavailable) {
			t.Fatalf("no xvfb: %v", err)
		}
		f = newFixture(t, func(c *Config) { c.User = "no-such-user-eng4573" })
		if _, _, err := f.m.Start(context.Background()); !errors.Is(err, ErrUnavailable) {
			t.Fatalf("no user: %v", err)
		}
	})
}

func TestProfileSizeLimit(t *testing.T) {
	f := newFixture(t, func(c *Config) { c.ProfileMaxBytes = 32 << 10 })
	ctx := context.Background()
	if _, _, err := f.m.Start(ctx); err != nil {
		t.Fatal(err)
	}
	if r, err := f.m.Stop(ctx); err != nil || !r.ProfileSaved {
		t.Fatalf("small profile: %v %+v", err, r)
	}
	f.set(t, "big", true)
	if _, _, err := f.m.Start(ctx); err != nil {
		t.Fatal(err)
	}
	r, err := f.m.Stop(ctx)
	if err != nil || !r.Clean || r.ProfileSaved || !strings.Contains(r.ProfileError, "size limit") {
		t.Fatalf("big profile: %v %+v", err, r)
	}
	if got := readCookies(t, f.saved); got != "1" {
		t.Fatalf("saved cookies %q", got)
	}
	if _, err := os.Stat(f.saved + ".tmp"); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("tmp left: %v", err)
	}
}

func TestStartContextCanceled(t *testing.T) {
	f := newFixture(t, nil)
	f.set(t, "no-ready", true)
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	if _, _, err := f.m.Start(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err %v", err)
	}
	if st := f.m.Status(); st.State != Stopped {
		t.Fatalf("state %s", st.State)
	}
}

func TestRecoverSwap(t *testing.T) {
	dir := t.TempDir()
	p := &profile{saved: filepath.Join(dir, "profile"), work: filepath.Join(dir, "work")}
	// A crash between the two renames of save: only .old and .tmp exist.
	for _, d := range []string{p.saved + ".old", p.saved + ".tmp"} {
		if err := os.MkdirAll(filepath.Join(d, "Default"), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(p.saved+".old", "Default", "Cookies"), []byte("7"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := p.resetLive(); err != nil {
		t.Fatal(err)
	}
	if got := readCookies(t, p.saved); got != "7" {
		t.Fatalf("recovered %q", got)
	}
	if got := readCookies(t, p.live()); got != "7" {
		t.Fatalf("live %q", got)
	}
	for _, d := range []string{p.saved + ".old", p.saved + ".tmp"} {
		if _, err := os.Stat(d); !errors.Is(err, os.ErrNotExist) {
			t.Errorf("%s left", d)
		}
	}
}

func TestChromeArgs(t *testing.T) {
	cfg := Config{Screen: "1920x1080x24", CDPPort: 9333, Env: []string{"http_proxy=http://p:1", "HTTPS_PROXY=http://127.0.0.1:3128"}}
	got := strings.Join(chromeArgs(cfg, "/live"), " ")
	for _, want := range []string{"--user-data-dir=/live", "--remote-debugging-port=9333", "--remote-debugging-address=127.0.0.1",
		"--window-size=1920,1080", "--proxy-server=http://127.0.0.1:3128", "--disable-gpu"} {
		if !strings.Contains(got, want) {
			t.Errorf("args %q lack %q", got, want)
		}
	}
	if strings.Contains(got, "--no-sandbox") {
		t.Errorf("Chromium sandbox must stay on: %q", got)
	}
}
