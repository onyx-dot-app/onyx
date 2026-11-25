package browser

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/browser/browsertest"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
)

func TestMain(m *testing.M) {
	browsertest.Main()
	os.Exit(m.Run())
}

func newFake(t *testing.T, mode string) (*Browser, []string) {
	t.Helper()
	b := New(Config{
		Binary:       browsertest.Binary(t),
		ProfileDir:   filepath.Join(t.TempDir(), "home", ".config", "onyx-browser"),
		Isolator:     execs.ProcessGroups{},
		StartTimeout: 10 * time.Second,
	})
	t.Cleanup(func() { _, _ = b.Stop() })
	return b, []string{browsertest.EnvMode + "=" + mode}
}

func answers(port int) bool {
	c := &http.Client{Timeout: time.Second}
	resp, err := c.Get("http://127.0.0.1:" + strconv.Itoa(port) + "/json/version")
	if err != nil {
		return false
	}
	_ = resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

func runningPID(b *Browser) int {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.run == nil || b.run.exited() {
		return 0
	}
	return b.run.pid
}

func TestStartReusesAndRelaunches(t *testing.T) {
	b, env := newFake(t, browsertest.ModeServe)
	ctx := context.Background()

	port, started, err := b.Start(ctx, env)
	if err != nil || !started || port == 0 {
		t.Fatalf("first start: port %d started %v err %v", port, started, err)
	}
	if !answers(port) {
		t.Fatal("the DevTools endpoint does not answer after Start")
	}
	pid := runningPID(b)

	port2, started, err := b.Start(ctx, env)
	if err != nil || started || port2 != port || runningPID(b) != pid {
		t.Fatalf("second start: port %d started %v err %v pid %d, want pid %d", port2, started, err, runningPID(b), pid)
	}

	if err := syscall.Kill(pid, syscall.SIGKILL); err != nil {
		t.Fatal(err)
	}
	port, started, err = b.Start(ctx, env)
	if err != nil || !started {
		t.Fatalf("start after a crash: started %v err %v", started, err)
	}
	if newPID := runningPID(b); newPID == 0 || newPID == pid {
		t.Fatalf("relaunch pid %d, old pid %d", newPID, pid)
	}
	if !answers(port) {
		t.Fatal("the relaunched browser does not answer")
	}
}

func TestStop(t *testing.T) {
	b, env := newFake(t, browsertest.ModeServe)
	if stopped, err := b.Stop(); err != nil || stopped {
		t.Fatalf("stop with no browser: %v %v", stopped, err)
	}
	port, _, err := b.Start(context.Background(), env)
	if err != nil {
		t.Fatal(err)
	}
	if stopped, err := b.Stop(); err != nil || !stopped {
		t.Fatalf("stop: %v %v", stopped, err)
	}
	if answers(port) {
		t.Fatal("the port still answers after Stop")
	}
	if _, err := os.Stat(filepath.Join(b.cfg.ProfileDir, browsertest.FlushedFile)); err != nil {
		t.Fatalf("Stop did not let chrome exit cleanly and flush its profile: %v", err)
	}
	if stopped, err := b.Stop(); err != nil || stopped {
		t.Fatalf("second stop: %v %v", stopped, err)
	}
}

func TestStartFailureHasStderr(t *testing.T) {
	b, env := newFake(t, browsertest.ModeFail)
	_, _, err := b.Start(context.Background(), env)
	if err == nil || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("start of a failing chrome: %v", err)
	}
	if stopped, _ := b.Stop(); stopped {
		t.Fatal("a failed start left a browser")
	}
}

func TestStartIgnoresAnotherDevToolsServer(t *testing.T) {
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"Browser":"OtherChrome/1.0"}`))
	}))
	defer other.Close()
	otherPort := other.Listener.Addr().(*net.TCPAddr).Port
	b, env := newFake(t, browsertest.ModeFail)
	stale := filepath.Join(b.cfg.ProfileDir, "DevToolsActivePort")
	if err := os.MkdirAll(b.cfg.ProfileDir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(stale, []byte(strconv.Itoa(otherPort)+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	old := time.Now().Add(-time.Hour)
	if err := os.Chtimes(stale, old, old); err != nil {
		t.Fatal(err)
	}
	if port, _, err := b.Start(context.Background(), env); err == nil {
		t.Fatalf("start reported the other server on port %d as its browser", port)
	}
}

func TestChromeArgsProxy(t *testing.T) {
	cfg := Config{ProfileDir: "/home/sandbox/.config/onyx-browser"}
	with := chromeArgs(cfg, []string{"PATH=/bin", "HTTPS_PROXY=http://127.0.0.1:3128"})
	if !slices.Contains(with, "--proxy-server=http://127.0.0.1:3128") {
		t.Fatalf("HTTPS_PROXY set: %v", with)
	}
	for _, want := range []string{"--remote-debugging-port=0", "--user-data-dir=/home/sandbox/.config/onyx-browser", "--remote-debugging-address=127.0.0.1"} {
		if !slices.Contains(with, want) {
			t.Errorf("missing %s in %v", want, with)
		}
	}
	if with[len(with)-1] != "about:blank" {
		t.Errorf("last arg %q", with[len(with)-1])
	}
	if fallback := chromeArgs(cfg, []string{"HTTP_PROXY=http://127.0.0.1:3128"}); !slices.Contains(fallback, "--proxy-server=http://127.0.0.1:3128") {
		t.Errorf("HTTP_PROXY fallback: %v", fallback)
	}
	for _, a := range chromeArgs(cfg, []string{"PATH=/bin"}) {
		if strings.HasPrefix(a, "--proxy-server") {
			t.Fatalf("no proxy env, got %s", a)
		}
	}
}
