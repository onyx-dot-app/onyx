package browser

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/egressrelay"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/browser/browsertest"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
)

// shortDir is a temp dir with a path short enough for a unix socket.
func shortDir(t *testing.T) string {
	t.Helper()
	d, err := os.MkdirTemp("", "ob")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(d) })
	return d
}

// newServiceFake returns a Browser of fake Chromes and services, their env
// and a profile dir.
func newServiceFake(t *testing.T) (*Browser, []string, string) {
	t.Helper()
	b := New(Config{
		Binary:        browsertest.Binary(t),
		ServiceScript: browsertest.ServiceScript,
		Node:          browsertest.Binary(t),
		SocketDir:     filepath.Join(shortDir(t), "run"),
		SessionsRoot:  "/sessions",
		Isolator:      execs.ProcessGroups{},
		StartTimeout:  10 * time.Second,
	})
	t.Cleanup(func() { _, _ = b.Stop() })
	return b, []string{browsertest.EnvMode + "=" + browsertest.ModeServe}, filepath.Join(t.TempDir(), "chrome")
}

type statusResult struct {
	OK     bool `json:"ok"`
	Result struct {
		Method       string `json:"method"`
		CDPURL       string `json:"cdpUrl"`
		SessionsRoot string `json:"sessionsRoot"`
		PID          int    `json:"pid"`
	} `json:"result"`
}

// callStatus sends a status call on conn and reads the answer.
func callStatus(t *testing.T, conn net.Conn) statusResult {
	t.Helper()
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	if err := browsertest.WriteJSON(conn, map[string]any{"op": "call", "chat": "c", "method": "status", "params": map[string]any{}}); err != nil {
		t.Fatal(err)
	}
	var res statusResult
	if err := browsertest.ReadJSON(conn, &res); err != nil {
		t.Fatal(err)
	}
	return res
}

func servicePID(b *Browser) int {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.run == nil || b.run.svc == nil {
		return 0
	}
	return b.run.svc.pid
}

func alive(pid int) bool {
	return pid > 0 && syscall.Kill(pid, 0) == nil
}

func TestServiceStartsWithChrome(t *testing.T) {
	b, env, profile := newServiceFake(t)
	ctx := context.Background()
	port, started, err := b.Start(ctx, profile, env)
	if err != nil || !started {
		t.Fatalf("start: started %v err %v", started, err)
	}
	fi, err := os.Stat(b.cfg.SocketDir)
	if err != nil || fi.Mode().Perm() != 0o700 {
		t.Fatalf("socket dir: %v %v", fi, err)
	}
	conn, err := b.DialService(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	res := callStatus(t, conn)
	if !res.OK || res.Result.Method != "status" || res.Result.CDPURL != "http://127.0.0.1:"+strconv.Itoa(port) || res.Result.SessionsRoot != "/sessions" {
		t.Fatalf("status answer: %+v", res)
	}

	svc := servicePID(b)
	if _, started, err := b.Start(ctx, profile, env); err != nil || started || servicePID(b) != svc {
		t.Fatalf("repeat start: started %v err %v", started, err)
	}

	if stopped, err := b.Stop(); err != nil || !stopped {
		t.Fatalf("stop: %v %v", stopped, err)
	}
	if alive(svc) {
		t.Fatal("the service outlived Stop")
	}
	if _, err := b.DialService(ctx); err == nil {
		t.Fatal("dial after Stop worked")
	}
}

// A service that exited, or whose socket no longer accepts (a command
// removed it, or its listener died), is started again without Chrome.
func TestBrokenServiceRestartsWithoutChrome(t *testing.T) {
	for name, breakService := range map[string]func(t *testing.T, b *Browser, svc int){
		"killed": func(t *testing.T, _ *Browser, svc int) {
			if err := syscall.Kill(svc, syscall.SIGKILL); err != nil {
				t.Fatal(err)
			}
			for alive(svc) {
				time.Sleep(10 * time.Millisecond)
			}
		},
		"socket removed": func(t *testing.T, b *Browser, _ int) {
			if err := os.Remove(b.SocketPath()); err != nil {
				t.Fatal(err)
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			b, env, profile := newServiceFake(t)
			ctx := context.Background()
			if _, _, err := b.Start(ctx, profile, env); err != nil {
				t.Fatal(err)
			}
			chrome, svc := runningPID(b), servicePID(b)
			breakService(t, b, svc)
			if _, started, err := b.Start(ctx, profile, env); err != nil || started {
				t.Fatalf("restart: started %v err %v", started, err)
			}
			if runningPID(b) != chrome || servicePID(b) == svc || alive(svc) {
				t.Fatalf("chrome %d->%d service %d->%d (old alive %v)", chrome, runningPID(b), svc, servicePID(b), alive(svc))
			}
			conn, err := b.DialService(ctx)
			if err != nil {
				t.Fatalf("dial after the restart: %v", err)
			}
			defer func() { _ = conn.Close() }()
			if res := callStatus(t, conn); !res.OK || res.Result.PID != servicePID(b) {
				t.Fatalf("status: %+v", res)
			}
		})
	}
}

func TestServiceFailureKeepsChrome(t *testing.T) {
	b, env, profile := newServiceFake(t)
	ctx := context.Background()
	bad := append(slices.Clone(env), browsertest.EnvServiceMode+"="+browsertest.ServiceFail)
	_, started, err := b.Start(ctx, profile, bad)
	if err == nil || !strings.Contains(err.Error(), "service boom") || !started {
		t.Fatalf("failing service: started %v err %v", started, err)
	}
	chrome := runningPID(b)
	if chrome == 0 {
		t.Fatal("a failed service stopped Chrome")
	}
	if _, started, err := b.Start(ctx, profile, env); err != nil || started || runningPID(b) != chrome {
		t.Fatalf("start after a failed service: started %v err %v", started, err)
	}
}

func TestProfileChangeRestartsChrome(t *testing.T) {
	b, env, _ := newServiceFake(t)
	ctx := context.Background()
	a := filepath.Join(t.TempDir(), "a", "chrome")
	if _, started, err := b.Start(ctx, a, env); err != nil || !started {
		t.Fatalf("start a: %v %v", started, err)
	}
	chrome := runningPID(b)
	if _, started, err := b.Start(ctx, a, env); err != nil || started {
		t.Fatalf("repeat start a: %v %v", started, err)
	}
	c := filepath.Join(t.TempDir(), "c", "chrome")
	if _, started, err := b.Start(ctx, c, env); err != nil || !started || runningPID(b) == chrome {
		t.Fatalf("start c: %v %v", started, err)
	}
	if _, err := os.Stat(filepath.Join(a, browsertest.FlushedFile)); err != nil {
		t.Fatalf("the profile change did not close Chrome cleanly: %v", err)
	}
	if _, err := os.Stat(filepath.Join(c, "DevToolsActivePort")); err != nil {
		t.Fatalf("chrome does not use the new profile: %v", err)
	}
}

func TestRelay(t *testing.T) {
	b, env, profile := newServiceFake(t)
	ctx := context.Background()
	ln, err := net.Listen("unix", filepath.Join(shortDir(t), "relay.sock"))
	if err != nil {
		t.Fatal(err)
	}
	r := &egressrelay.Relay{Dial: b.DialService}
	go func() { _ = r.Serve(ln) }()
	t.Cleanup(func() { _ = ln.Close() })

	// No service yet: the connection closes.
	conn, err := net.Dial("unix", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	if _, err := conn.Read(make([]byte, 1)); err != io.EOF {
		t.Fatalf("read with no service: %v", err)
	}
	_ = conn.Close()

	if _, _, err := b.Start(ctx, profile, env); err != nil {
		t.Fatal(err)
	}
	conn, err = net.Dial("unix", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	if res := callStatus(t, conn); !res.OK || res.Result.PID != servicePID(b) {
		t.Fatalf("status through the relay: %+v", res)
	}
}

// stopService must not signal the process group of a service that already
// exited: its PID may now lead another process group.
func TestStopServiceSkipsAnExitedService(t *testing.T) {
	other := exec.Command("sleep", "100")
	other.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := other.Start(); err != nil {
		t.Fatal(err)
	}
	exited := make(chan struct{})
	go func() { _ = other.Wait(); close(exited) }()
	t.Cleanup(func() { _ = other.Process.Kill(); <-exited })
	done := make(chan struct{})
	close(done)
	// The service's PID now leads the unrelated group of other.
	r := &running{svc: &proc{pid: other.Process.Pid, done: done, stderr: &tail{max: 1}}}
	if err := (&Browser{}).stopService(r); err != nil {
		t.Fatal(err)
	}
	select {
	case <-exited:
		t.Fatal("stopService killed the process group that reused the PID of an exited service")
	case <-time.After(200 * time.Millisecond):
	}
}

func TestExitedServiceIsLogged(t *testing.T) {
	b, env, profile := newServiceFake(t)
	var logs bytes.Buffer
	b.cfg.Log = slog.New(slog.NewTextHandler(&logs, nil))
	ctx := context.Background()
	if _, _, err := b.Start(ctx, profile, env); err != nil {
		t.Fatal(err)
	}
	svc := servicePID(b)
	if err := syscall.Kill(svc, syscall.SIGKILL); err != nil {
		t.Fatal(err)
	}
	for alive(svc) {
		time.Sleep(10 * time.Millisecond)
	}
	if _, _, err := b.Start(ctx, profile, env); err != nil {
		t.Fatal(err)
	}
	if want := `msg="browser service exited" pid=` + strconv.Itoa(svc); !strings.Contains(logs.String(), want) {
		t.Fatalf("log has no %q:\n%s", want, logs.String())
	}
}
