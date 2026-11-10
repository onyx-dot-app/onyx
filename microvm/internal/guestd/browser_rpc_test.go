package guestd

import (
	"context"
	"net"
	"testing"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/browser"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

func TestBrowserCallsGateAndErrors(t *testing.T) {
	ctx := context.Background()

	// No browser configured.
	h := newHarness(t, execs.Config{}, Config{})
	c, _ := h.client()
	if _, err := c.BrowserStatus(keyed(ctx), &pb.BrowserStatusRequest{}); reason(err) != "KEY_NOT_SET" {
		t.Fatalf("before SetKey: %v", err)
	}
	c = h.initialized()
	for name, call := range map[string]func() error{
		"start":  func() error { _, err := c.BrowserStart(keyed(ctx), &pb.BrowserStartRequest{}); return err },
		"stop":   func() error { _, err := c.BrowserStop(keyed(ctx), &pb.BrowserStopRequest{}); return err },
		"status": func() error { _, err := c.BrowserStatus(keyed(ctx), &pb.BrowserStatusRequest{}); return err },
	} {
		if err := call(); reason(err) != "BROWSER_NOT_AVAILABLE" {
			t.Errorf("%s without a browser: %v", name, err)
		}
	}

	// A browser whose binaries are missing.
	b, err := browser.New(browser.Config{
		ChromeBins: []string{"/nonexistent/chrome"}, XvfbBin: "/nonexistent/Xvfb", Isolator: execs.ProcessGroups{},
		Listen:     func(uint32) (net.Listener, error) { return net.Listen("tcp", "127.0.0.1:0") },
		ProfileDir: t.TempDir() + "/profile", WorkDir: t.TempDir(), VsockPort: 9300,
	})
	if err != nil {
		t.Fatal(err)
	}
	h = newHarness(t, execs.Config{}, Config{Browser: b})
	c = h.initialized()
	if _, err := c.BrowserStart(keyed(ctx), &pb.BrowserStartRequest{}); reason(err) != "BROWSER_NOT_AVAILABLE" {
		t.Fatalf("start with no binary: %v", err)
	}
	st, err := c.BrowserStatus(keyed(ctx), &pb.BrowserStatusRequest{})
	if err != nil || st.GetStatus().GetState() != pb.BrowserState_BROWSER_STOPPED || st.GetStatus().GetCdpPort() != 9300 {
		t.Fatalf("status: %v %v", st, err)
	}
	r, err := c.BrowserStop(keyed(ctx), &pb.BrowserStopRequest{})
	if err != nil || r.GetWasRunning() {
		t.Fatalf("stop: %v %v", r, err)
	}
}
