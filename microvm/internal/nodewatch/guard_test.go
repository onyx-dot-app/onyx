package nodewatch

import (
	"context"
	"encoding/json"
	"encoding/pem"
	"errors"
	"io"
	"log/slog"
	"maps"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// fakeNode is a Node with annotations that counts patches.
type fakeNode struct {
	ann      map[string]string
	patches  int
	reads    int
	patchErr error
}

func (f *fakeNode) Node(context.Context) (Node, error) {
	f.reads++
	return Node{Annotations: maps.Clone(f.ann)}, nil
}

func (f *fakeNode) SetAnnotations(_ context.Context, set map[string]*string) error {
	if f.patchErr != nil {
		return f.patchErr
	}
	f.patches++
	if f.ann == nil {
		f.ann = map[string]string{}
	}
	for k, v := range set {
		if v == nil {
			delete(f.ann, k)
		} else {
			f.ann[k] = *v
		}
	}
	return nil
}

type guardFixture struct {
	node  *fakeNode
	vms   int
	clock time.Time
	g     *ScaleDownGuard
}

func newGuard(t *testing.T, ann map[string]string) *guardFixture {
	t.Helper()
	f := &guardFixture{node: &fakeNode{ann: ann}, clock: time.Unix(1_800_000_000, 0)}
	f.g = &ScaleDownGuard{
		Node: f.node, VMs: func() int { return f.vms }, Grace: 10 * time.Minute, Interval: time.Second,
		Log: slog.New(slog.NewTextHandler(io.Discard, nil)), Now: func() time.Time { return f.clock },
	}
	return f
}

func (f *guardFixture) blocked() bool {
	return f.node.ann[ScaleDownDisabledKey] == "true" && f.node.ann[GuardOwnerKey] == "true"
}

func TestScaleDownGuardBlocksWhileVMsRun(t *testing.T) {
	f := newGuard(t, nil)
	ctx := context.Background()

	f.g.Once(ctx) // no VMs, idle for less than the grace: nothing to do
	if f.node.reads != 0 || f.node.patches != 0 {
		t.Fatalf("idle start: %d reads %d patches", f.node.reads, f.node.patches)
	}
	f.vms = 1
	f.g.Once(ctx)
	if !f.blocked() || f.node.patches != 1 {
		t.Fatalf("VM runs: %v after %d patches", f.node.ann, f.node.patches)
	}
	f.g.Once(ctx)
	if f.node.patches != 1 || f.node.reads != 2 {
		t.Fatalf("no change, but %d reads %d patches", f.node.reads, f.node.patches)
	}
	// Someone removes the annotation while VMs run: the next check sets it again.
	f.node.ann = nil
	f.g.Once(ctx)
	if !f.blocked() || f.node.patches != 2 {
		t.Fatalf("not set again: %v after %d patches", f.node.ann, f.node.patches)
	}

	f.vms = 0
	f.g.Once(ctx)
	f.clock = f.clock.Add(9 * time.Minute)
	f.g.Once(ctx)
	if !f.blocked() {
		t.Fatal("annotation removed inside the grace")
	}
	// A VM inside the grace restarts the idle time.
	f.vms = 2
	f.g.Once(ctx)
	f.vms = 0
	f.g.Once(ctx)
	f.clock = f.clock.Add(9 * time.Minute)
	f.g.Once(ctx)
	if !f.blocked() || f.node.patches != 2 {
		t.Fatalf("idle time not reset: %v after %d patches", f.node.ann, f.node.patches)
	}
	f.clock = f.clock.Add(time.Minute)
	f.g.Once(ctx)
	if len(f.node.ann) != 0 || f.node.patches != 3 {
		t.Fatalf("after the grace: %v after %d patches", f.node.ann, f.node.patches)
	}
	reads := f.node.reads
	f.g.Once(ctx)
	if f.node.patches != 3 || f.node.reads != reads {
		t.Fatalf("idle node read again: %d reads %d patches", f.node.reads-reads, f.node.patches)
	}
}

// readHook runs fn at each Node read, for a VM that starts during the read.
type readHook struct {
	*fakeNode
	fn func()
}

func (r readHook) Node(ctx context.Context) (Node, error) {
	r.fn()
	return r.fakeNode.Node(ctx)
}

func TestScaleDownGuardKeepsAnnotationForVMStartedDuringRead(t *testing.T) {
	ctx := context.Background()
	f := newGuard(t, map[string]string{ScaleDownDisabledKey: "true", GuardOwnerKey: "true"})
	f.g.Node = readHook{f.node, func() { f.vms = 1 }}
	f.g.Once(ctx)
	f.clock = f.clock.Add(10 * time.Minute)
	f.vms = 0
	f.g.Once(ctx) // after the grace; the read admits a VM
	if !f.blocked() || f.node.patches != 0 {
		t.Fatalf("removed for a new VM: %v after %d patches", f.node.ann, f.node.patches)
	}
	// The idle time starts again.
	f.g.Node = f.node
	f.vms = 0
	f.g.Once(ctx)
	f.clock = f.clock.Add(9 * time.Minute)
	f.g.Once(ctx)
	if !f.blocked() {
		t.Fatal("removed inside the new grace")
	}
}

func TestScaleDownGuardAfterRestart(t *testing.T) {
	ctx := context.Background()
	ours := map[string]string{ScaleDownDisabledKey: "true", GuardOwnerKey: "true"}

	// VMs were adopted: the annotation is already there.
	f := newGuard(t, maps.Clone(ours))
	f.vms = 1
	f.g.Once(ctx)
	if !f.blocked() || f.node.patches != 0 {
		t.Fatalf("adopted VMs: %v after %d patches", f.node.ann, f.node.patches)
	}

	// No VMs left: the annotation goes after the grace, counted from start.
	f = newGuard(t, maps.Clone(ours))
	f.g.Once(ctx)
	if !f.blocked() {
		t.Fatal("removed at start")
	}
	f.clock = f.clock.Add(10 * time.Minute)
	f.g.Once(ctx)
	if len(f.node.ann) != 0 {
		t.Fatalf("stale annotation stays: %v", f.node.ann)
	}
}

func TestScaleDownGuardLeavesForeignAnnotation(t *testing.T) {
	ctx := context.Background()
	f := newGuard(t, map[string]string{ScaleDownDisabledKey: "true"})
	f.vms = 1
	f.g.Once(ctx)
	f.vms = 0
	f.g.Once(ctx)
	f.clock = f.clock.Add(time.Hour)
	f.g.Once(ctx)
	if f.node.patches != 0 || f.node.ann[ScaleDownDisabledKey] != "true" || f.node.ann[GuardOwnerKey] != "" {
		t.Fatalf("operator annotation changed: %v after %d patches", f.node.ann, f.node.patches)
	}

	// An operator "false" does not keep VMs from the guard.
	f = newGuard(t, map[string]string{ScaleDownDisabledKey: "false"})
	f.vms = 1
	f.g.Once(ctx)
	if !f.blocked() {
		t.Fatalf("false not replaced: %v", f.node.ann)
	}
}

func TestScaleDownGuardRetriesFailedPatch(t *testing.T) {
	ctx := context.Background()
	f := newGuard(t, nil)
	f.node.patchErr = errors.New("HTTP 403")
	f.vms = 1
	f.g.Once(ctx)
	f.g.Once(ctx)
	if f.node.patches != 0 || f.node.reads != 2 {
		t.Fatalf("%d reads %d patches", f.node.reads, f.node.patches)
	}
	f.node.patchErr = nil
	f.g.Once(ctx)
	if !f.blocked() {
		t.Fatalf("no retry: %v", f.node.ann)
	}
}

// syncNode is a fakeNode for Run, which reads it from another goroutine.
type syncNode struct {
	mu sync.Mutex
	fakeNode
}

func (n *syncNode) Node(ctx context.Context) (Node, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	return n.fakeNode.Node(ctx)
}

func (n *syncNode) SetAnnotations(ctx context.Context, set map[string]*string) error {
	n.mu.Lock()
	defer n.mu.Unlock()
	return n.fakeNode.SetAnnotations(ctx, set)
}

func (n *syncNode) patched() int {
	n.mu.Lock()
	defer n.mu.Unlock()
	return n.patches
}

func TestScaleDownGuardKickChecksAtOnce(t *testing.T) {
	node := &syncNode{}
	var vms atomic.Int32
	g := &ScaleDownGuard{
		Node: node, VMs: func() int { return int(vms.Load()) }, Grace: time.Hour, Interval: time.Hour,
		Timeout: time.Second, Log: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	g.Kick() // before Run: never blocks
	g.Kick()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go g.Run(ctx)
	vms.Store(1)
	g.Kick()
	deadline := time.Now().Add(5 * time.Second)
	for node.patched() == 0 {
		if time.Now().After(deadline) {
			t.Fatal("Kick did not run a check")
		}
		time.Sleep(time.Millisecond)
	}
}

func TestInClusterSetAnnotations(t *testing.T) {
	var method, ctype, path string
	var body map[string]any
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		method, ctype, path = r.Method, r.Header.Get("Content-Type"), r.URL.Path
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		if strings.HasSuffix(path, "/forbidden") {
			http.Error(w, `{"reason":"Forbidden"}`, http.StatusForbidden)
			return
		}
		_, _ = w.Write([]byte(`{"kind":"Node","metadata":{"annotations":{"a":"1"}}}`))
	}))
	defer srv.Close()
	caPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw})
	tok := filepath.Join(t.TempDir(), "token")
	if err := os.WriteFile(tok, []byte("tok"), 0o600); err != nil {
		t.Fatal(err)
	}
	c, err := NewWithCA(srv.URL, "node-1", tok, caPEM)
	if err != nil {
		t.Fatal(err)
	}
	v := "true"
	if err := c.SetAnnotations(context.Background(), map[string]*string{ScaleDownDisabledKey: &v, GuardOwnerKey: nil}); err != nil {
		t.Fatal(err)
	}
	if method != http.MethodPatch || ctype != "application/merge-patch+json" || path != "/api/v1/nodes/node-1" {
		t.Fatalf("%s %s %s", method, ctype, path)
	}
	ann := body["metadata"].(map[string]any)["annotations"].(map[string]any)
	if got, ok := ann[GuardOwnerKey]; !ok || got != nil || ann[ScaleDownDisabledKey] != "true" {
		t.Fatalf("patch %v", body)
	}
	c.NodeName = "forbidden"
	if err := c.SetAnnotations(context.Background(), nil); err == nil || !strings.Contains(err.Error(), "patch node forbidden: HTTP 403") {
		t.Fatalf("forbidden: %v", err)
	}
}
