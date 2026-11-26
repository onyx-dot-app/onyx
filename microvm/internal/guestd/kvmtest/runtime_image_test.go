//go:build kvm && linux

package kvmtest

import (
	"context"
	"net"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/browser/browsertest"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// browserPort is the guest daemon's browser service relay port.
const browserPort = 3011

func TestRuntimeImageKVM(t *testing.T) {
	if os.Getenv("KVM_RUNTIME_IMAGE") != "1" {
		t.Skip("set KVM_RUNTIME_IMAGE=1 with a craft-runtime rootfs")
	}
	e := loadEnv(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	v := bootVM(t, e, "runtime-image", "")
	if _, err := waitHealth(ctx, v); err != nil {
		t.Fatalf("health: %v\n%s", err, v.console())
	}
	c, _ := client(t, v)
	key := randHex(32)
	if _, err := keyInit(ctx, c, key, initRequest("runtime-image")); err != nil {
		t.Fatal(err)
	}
	result, err := run(keyed(ctx, key), c, &pb.Command{Argv: []string{"/opt/onyx/check-runtime"}})
	t.Logf("stdout:\n%s\nstderr:\n%s", result.stdout, result.stderr)
	if err != nil || result.res.GetCompletion() != pb.Completion_EXITED || result.res.GetExitCode() != 0 || !strings.Contains(result.stdout, "Craft runtime smoke checks passed.") {
		t.Fatalf("runtime image check: error=%v result=%v", err, result.res)
	}
	checkBrowserOutlivesCommands(keyed(ctx, key), t, c, v)
}

// checkBrowserOutlivesCommands also checks the browser service: a status
// call through the vsock relay answers, and the profile is in the session.
// A repeat start keeps Chrome and its tabs.
func checkBrowserOutlivesCommands(ctx context.Context, t *testing.T, c pb.SandboxdClient, v *vm) {
	t.Helper()
	const profileSession = "0b7c6f9e-4a1d-4d2b-9a57-3f1e2c8d9a10"
	req := &pb.BrowserStartRequest{ProfileSessionId: profileSession}
	if _, err := c.BrowserStart(ctx, req); err != nil {
		t.Fatalf("browser start: %v", err)
	}
	profile, err := run(ctx, c, &pb.Command{Argv: []string{"head", "-n1", "/home/onyx/workspaces/" + profileSession + "/chrome/DevToolsActivePort"}})
	port, perr := strconv.Atoi(strings.TrimSpace(profile.stdout))
	if err != nil || profile.res.GetExitCode() != 0 || perr != nil {
		t.Fatalf("chrome does not use the profile session: %v %v %q", err, profile.res, profile.stdout)
	}
	cdp := "http://127.0.0.1:" + strconv.Itoa(port)
	open, err := run(ctx, c, &pb.Command{Argv: []string{"curl", "-sf", "-X", "PUT", cdp + "/json/new?about:blank%23kept"}})
	if err != nil || open.res.GetExitCode() != 0 {
		t.Fatalf("open a tab: %v %v %s", err, open.res, open.stderr)
	}
	checkTabKept := func(when string) {
		list, err := run(ctx, c, &pb.Command{Argv: []string{"curl", "-sf", cdp + "/json/list"}})
		if err != nil || list.res.GetExitCode() != 0 || !strings.Contains(list.stdout, "about:blank#kept") {
			t.Fatalf("the tab is gone %s: %v %v\n%s", when, err, list.res, list.stdout)
		}
	}
	checkTabKept("after the command that opened it")
	checkBrowserServiceStatus(ctx, t, v)
	health, err := c.Health(ctx, &pb.HealthRequest{})
	if err != nil || health.GetRunningExecutions() != 0 {
		t.Fatalf("the browser counts as an execution: %v %v", health, err)
	}
	if _, err := c.BrowserStart(ctx, req); err != nil {
		t.Fatalf("repeat browser start: %v", err)
	}
	checkTabKept("after a repeat start")
	checkBrowserServiceStatus(ctx, t, v)
	stopped, err := c.BrowserStop(ctx, &pb.BrowserStopRequest{})
	if err != nil || !stopped.GetStopped() {
		t.Fatalf("browser stop: %v %v", stopped, err)
	}
	conn, err := dialVsock(ctx, v.vsock(), browserPort)
	if err == nil {
		_ = conn.SetDeadline(time.Now().Add(10 * time.Second))
		_, err = conn.Read(make([]byte, 1))
		_ = conn.Close()
		if ne, ok := err.(net.Error); err == nil || ok && ne.Timeout() {
			t.Fatalf("relay with no service: read %v, want a closed connection", err)
		}
	}
}

// checkBrowserServiceStatus sends a framed status call to the service
// through the relay port and wants {"ok":true,"result":{"tabs":[...]}}.
func checkBrowserServiceStatus(ctx context.Context, t *testing.T, v *vm) {
	t.Helper()
	conn, err := dialVsock(ctx, v.vsock(), browserPort)
	if err != nil {
		t.Fatalf("dial the browser relay: %v", err)
	}
	defer func() { _ = conn.Close() }()
	_ = conn.SetDeadline(time.Now().Add(30 * time.Second))
	call := map[string]any{"op": "call", "chat": "5f0e3c1a-8b2d-4e6f-9a1b-2c3d4e5f6a7b", "method": "status", "params": map[string]any{}}
	if err := browsertest.WriteJSON(conn, call); err != nil {
		t.Fatal(err)
	}
	var res struct {
		OK     bool `json:"ok"`
		Result struct {
			Tabs []any `json:"tabs"`
		} `json:"result"`
		Error any `json:"error"`
	}
	if err := browsertest.ReadJSON(conn, &res); err != nil {
		t.Fatalf("status answer: %v", err)
	}
	if !res.OK || res.Result.Tabs == nil {
		t.Fatalf("status answer: %+v", res)
	}
}
