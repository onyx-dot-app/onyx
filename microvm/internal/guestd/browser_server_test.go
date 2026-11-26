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
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/files"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

func TestMain(m *testing.M) {
	browsertest.Main()
	os.Exit(m.Run())
}

// browserHarness serves a Browser of fake Chromes, with sessions in a temp dir.
func browserHarness(t *testing.T, mode string) (*harness, string) {
	t.Helper()
	sessions := filepath.Join(t.TempDir(), "sessions")
	fs, err := files.New(files.Config{SessionsRoot: sessions})
	if err != nil {
		t.Fatal(err)
	}
	b := browser.New(browser.Config{
		Binary: browsertest.Binary(t), Isolator: execs.ProcessGroups{}, StartTimeout: 10 * time.Second,
	})
	t.Cleanup(func() { _, _ = b.Stop() })
	h := newHarness(t, execs.Config{}, Config{Browser: b, Files: fs, BaseEnv: map[string]string{browsertest.EnvMode: mode}})
	return h, sessions
}

func TestBrowserStartStop(t *testing.T) {
	h, sessions := browserHarness(t, browsertest.ModeServe)
	c, _ := h.client()
	if _, err := c.SetKey(context.Background(), &pb.SetKeyRequest{Key: testKey}); err != nil {
		t.Fatal(err)
	}
	ctx := keyed(context.Background())
	if _, err := c.BrowserStart(ctx, &pb.BrowserStartRequest{ProfileSessionId: "sbx-1"}); reason(err) != "NOT_INITIALIZED" {
		t.Fatalf("browser start before Init: %v", err)
	}
	if _, err := c.Init(ctx, initReq()); err != nil {
		t.Fatal(err)
	}

	// Each fake Chrome writes the free port that it got to DevToolsActivePort.
	activePort := func() string {
		data, err := os.ReadFile(filepath.Join(sessions, "sbx-1", "chrome", "DevToolsActivePort"))
		if err != nil {
			t.Fatal(err)
		}
		return string(data)
	}
	if _, err := c.BrowserStart(ctx, &pb.BrowserStartRequest{ProfileSessionId: "sbx-1"}); err != nil {
		t.Fatalf("first start: %v", err)
	}
	first := activePort()
	if _, err := c.BrowserStart(ctx, &pb.BrowserStartRequest{ProfileSessionId: "sbx-1"}); err != nil || activePort() != first {
		t.Fatalf("second start did not keep Chrome: %v", err)
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
	_, err := c.BrowserStart(keyed(context.Background()), &pb.BrowserStartRequest{ProfileSessionId: "sbx-1"})
	if reason(err) != "BROWSER_START_FAILED" || !strings.Contains(err.Error(), "boom") {
		t.Fatalf("failing chrome: %v", err)
	}
}

func TestBrowserStartProfileSession(t *testing.T) {
	h, sessions := browserHarness(t, browsertest.ModeServe)
	c := h.initialized()
	ctx := keyed(context.Background())
	for _, id := range []string{"../x", ""} {
		if _, err := c.BrowserStart(ctx, &pb.BrowserStartRequest{ProfileSessionId: id}); reason(err) != "INVALID_ARGUMENT" {
			t.Fatalf("profile session %q: %v", id, err)
		}
	}
	if _, err := c.BrowserStart(ctx, &pb.BrowserStartRequest{ProfileSessionId: "sbx-1"}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(sessions, "sbx-1", "chrome", "DevToolsActivePort")); err != nil {
		t.Fatalf("chrome does not use the session profile: %v", err)
	}
}

// service_protocol tells a client that port 3011 serves the service. It is
// 0 when the daemon has no service or no relay.
func TestBrowserStartServiceProtocol(t *testing.T) {
	for name, tc := range map[string]struct {
		service bool
		relay   bool
		want    uint32
	}{
		"service and relay": {service: true, relay: true, want: browser.ServiceProtocol},
		"no relay":          {service: true},
		"no service":        {relay: true},
	} {
		t.Run(name, func(t *testing.T) {
			fs, err := files.New(files.Config{SessionsRoot: filepath.Join(t.TempDir(), "sessions")})
			if err != nil {
				t.Fatal(err)
			}
			cfg := browser.Config{Binary: browsertest.Binary(t), Isolator: execs.ProcessGroups{}, StartTimeout: 10 * time.Second}
			if tc.service {
				dir, err := os.MkdirTemp("", "ob")
				if err != nil {
					t.Fatal(err)
				}
				t.Cleanup(func() { _ = os.RemoveAll(dir) })
				cfg.ServiceScript, cfg.Node, cfg.SocketDir = browsertest.ServiceScript, browsertest.Binary(t), filepath.Join(dir, "run")
			}
			b := browser.New(cfg)
			t.Cleanup(func() { _, _ = b.Stop() })
			h := newHarness(t, execs.Config{}, Config{Browser: b, BrowserRelay: tc.relay, Files: fs,
				BaseEnv: map[string]string{browsertest.EnvMode: browsertest.ModeServe}})
			c := h.initialized()
			resp, err := c.BrowserStart(keyed(context.Background()), &pb.BrowserStartRequest{ProfileSessionId: "sbx-1"})
			if err != nil || resp.GetServiceProtocol() != tc.want {
				t.Fatalf("service protocol %d, want %d (err %v)", resp.GetServiceProtocol(), tc.want, err)
			}
		})
	}
}
