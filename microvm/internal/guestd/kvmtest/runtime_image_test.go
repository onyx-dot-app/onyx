//go:build kvm && linux

package kvmtest

import (
	"context"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

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
	checkBrowserOutlivesCommands(keyed(ctx, key), t, c)
}

func checkBrowserOutlivesCommands(ctx context.Context, t *testing.T, c pb.SandboxdClient) {
	t.Helper()
	started, err := c.BrowserStart(ctx, &pb.BrowserStartRequest{})
	if err != nil || !started.GetStarted() || started.GetCdpPort() == 0 {
		t.Fatalf("browser start: %v %v", started, err)
	}
	cdp := "http://127.0.0.1:" + strconv.Itoa(int(started.GetCdpPort()))
	open, err := run(ctx, c, &pb.Command{Argv: []string{"curl", "-sf", "-X", "PUT", cdp + "/json/new?about:blank%23kept"}})
	if err != nil || open.res.GetExitCode() != 0 {
		t.Fatalf("open a tab: %v %v %s", err, open.res, open.stderr)
	}
	list, err := run(ctx, c, &pb.Command{Argv: []string{"curl", "-sf", cdp + "/json/list"}})
	if err != nil || list.res.GetExitCode() != 0 || !strings.Contains(list.stdout, "about:blank#kept") {
		t.Fatalf("the tab did not outlive the command that opened it: %v %v\n%s", err, list.res, list.stdout)
	}
	health, err := c.Health(ctx, &pb.HealthRequest{})
	if err != nil || health.GetRunningExecutions() != 0 {
		t.Fatalf("the browser counts as an execution: %v %v", health, err)
	}
	again, err := c.BrowserStart(ctx, &pb.BrowserStartRequest{})
	if err != nil || again.GetStarted() || again.GetCdpPort() != started.GetCdpPort() {
		t.Fatalf("repeat browser start: %v %v", again, err)
	}
	stopped, err := c.BrowserStop(ctx, &pb.BrowserStopRequest{})
	if err != nil || !stopped.GetStopped() {
		t.Fatalf("browser stop: %v %v", stopped, err)
	}
}
