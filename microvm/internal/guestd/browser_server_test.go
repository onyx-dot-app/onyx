package guestd

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/browser"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/browser/browsertest"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

func TestMain(m *testing.M) {
	browsertest.Main()
	os.Exit(m.Run())
}

func browserHarness(t *testing.T, mode string) (*harness, int) {
	t.Helper()
	port := browsertest.FreePort(t)
	b := browser.New(browser.Config{
		Binary: browsertest.Binary(t), ProfileDir: filepath.Join(t.TempDir(), "onyx-browser"), Port: port,
		Isolator: execs.ProcessGroups{}, StartTimeout: 10 * time.Second,
	})
	t.Cleanup(func() { _, _ = b.Stop() })
	h := newHarness(t, execs.Config{}, Config{Browser: b, BaseEnv: map[string]string{browsertest.EnvMode: mode}})
	return h, port
}

func TestBrowserStartStop(t *testing.T) {
	h, port := browserHarness(t, browsertest.ModeServe)
	c, _ := h.client()
	if _, err := c.SetKey(context.Background(), &pb.SetKeyRequest{Key: testKey}); err != nil {
		t.Fatal(err)
	}
	ctx := keyed(context.Background())
	if _, err := c.BrowserStart(ctx, &pb.BrowserStartRequest{}); reason(err) != "NOT_INITIALIZED" {
		t.Fatalf("browser start before Init: %v", err)
	}
	if _, err := c.Init(ctx, initReq()); err != nil {
		t.Fatal(err)
	}

	r, err := c.BrowserStart(ctx, &pb.BrowserStartRequest{})
	if err != nil || !r.GetStarted() || r.GetCdpPort() != uint32(port) {
		t.Fatalf("first start: %v %v", r, err)
	}
	r, err = c.BrowserStart(ctx, &pb.BrowserStartRequest{})
	if err != nil || r.GetStarted() || r.GetCdpPort() != uint32(port) {
		t.Fatalf("second start: %v %v", r, err)
	}
	if hr, err := c.Health(context.Background(), &pb.HealthRequest{}); err != nil || hr.GetRunningExecutions() != 0 {
		t.Fatalf("the browser counts as an execution: %v %v", hr, err)
	}
	if sr, err := c.BrowserStop(ctx, &pb.BrowserStopRequest{}); err != nil || !sr.GetStopped() {
		t.Fatalf("stop: %v %v", sr, err)
	}
	if sr, err := c.BrowserStop(ctx, &pb.BrowserStopRequest{}); err != nil || sr.GetStopped() {
		t.Fatalf("second stop: %v %v", sr, err)
	}
}

func TestBrowserStartFailed(t *testing.T) {
	h, _ := browserHarness(t, browsertest.ModeFail)
	c := h.initialized()
	_, err := c.BrowserStart(keyed(context.Background()), &pb.BrowserStartRequest{})
	if reason(err) != "BROWSER_START_FAILED" || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("failing chrome: %v", err)
	}
}
