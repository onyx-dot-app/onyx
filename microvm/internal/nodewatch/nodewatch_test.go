package nodewatch

import (
	"context"
	"encoding/pem"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestDrainTaints(t *testing.T) {
	n := Node{Taints: []Taint{
		{Key: "workload", Value: "sandbox", Effect: "NoSchedule"},
		{Key: "node.kubernetes.io/unschedulable", Effect: "NoSchedule"},
		{Key: "karpenter.sh/disrupted", Effect: "NoSchedule"},
		{Key: "node.kubernetes.io/unschedulable", Effect: "NoSchedule"},
	}}
	got := DrainTaints(n, DefaultTaintKeys)
	if !slices.Equal(got, []string{"node.kubernetes.io/unschedulable=:NoSchedule"}) {
		t.Errorf("default keys: %v", got)
	}
	got = DrainTaints(n, []string{"karpenter.sh/disrupted", "node.kubernetes.io/unschedulable"})
	if !slices.Equal(got, []string{"karpenter.sh/disrupted=:NoSchedule", "node.kubernetes.io/unschedulable=:NoSchedule"}) {
		t.Errorf("two keys: %v", got)
	}
	if got := DrainTaints(Node{Taints: n.Taints[:1]}, DefaultTaintKeys); got != nil {
		t.Errorf("no drain taint: %v", got)
	}
}

type fakeSource struct {
	mu    sync.Mutex
	nodes []Node
	errs  []error
	calls int
}

func (f *fakeSource) Node(context.Context) (Node, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	i := min(f.calls, len(f.nodes)-1)
	f.calls++
	return f.nodes[i], f.errs[i]
}

func TestWatcherOnce(t *testing.T) {
	cordon := Node{Taints: []Taint{{Key: "node.kubernetes.io/unschedulable", Effect: "NoSchedule"}}}
	src := &fakeSource{nodes: []Node{{}, cordon, {}, {}}, errs: []error{nil, nil, errors.New("HTTP 403"), nil}}
	type call struct {
		taints []string
		err    error
	}
	var got []call
	w := &Watcher{Source: src, Keys: DefaultTaintKeys, Interval: time.Second,
		Apply: func(taints []string, err error) { got = append(got, call{taints, err}) }}
	for range 4 {
		w.Once(context.Background())
	}
	if len(got) != 4 || got[0].taints != nil || got[0].err != nil ||
		!slices.Equal(got[1].taints, []string{"node.kubernetes.io/unschedulable=:NoSchedule"}) ||
		got[2].err == nil || got[3].taints != nil || got[3].err != nil {
		t.Fatalf("calls %+v", got)
	}
}

func TestWatcherRunStops(t *testing.T) {
	src := &fakeSource{nodes: []Node{{}}, errs: []error{nil}}
	ctx, cancel := context.WithCancel(context.Background())
	n := 0
	w := &Watcher{Source: src, Keys: DefaultTaintKeys, Interval: time.Millisecond, Apply: func([]string, error) {
		n++
		if n == 3 {
			cancel()
		}
	}}
	done := make(chan struct{})
	go func() { w.Run(ctx); close(done) }()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not stop")
	}
	if n < 3 {
		t.Fatalf("%d reads", n)
	}
}

func TestInClusterNode(t *testing.T) {
	var gotAuth, gotPath string
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotAuth, gotPath = r.Header.Get("Authorization"), r.URL.Path
		if r.URL.Path == "/api/v1/nodes/forbidden" {
			http.Error(w, `{"reason":"Forbidden"}`, http.StatusForbidden)
			return
		}
		_, _ = w.Write([]byte(`{"kind":"Node","spec":{"unschedulable":true,"taints":[
			{"key":"node.kubernetes.io/unschedulable","effect":"NoSchedule","timeAdded":"2026-11-09T00:00:00Z"},
			{"key":"workload","value":"sandbox","effect":"NoSchedule"}]}}`))
	}))
	defer srv.Close()
	caPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw})
	tok := filepath.Join(t.TempDir(), "token")
	if err := os.WriteFile(tok, []byte("tok-1\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	c, err := NewWithCA(srv.URL, "ip-10-0-0-1.us-west-1.compute.internal", tok, caPEM)
	if err != nil {
		t.Fatal(err)
	}
	n, err := c.Node(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if gotAuth != "Bearer tok-1" || gotPath != "/api/v1/nodes/ip-10-0-0-1.us-west-1.compute.internal" {
		t.Errorf("auth %q path %q", gotAuth, gotPath)
	}
	if got := DrainTaints(n, DefaultTaintKeys); !slices.Equal(got, []string{"node.kubernetes.io/unschedulable=:NoSchedule"}) {
		t.Errorf("taints %v", got)
	}
	// A rotated token is read again on the next call.
	if err := os.WriteFile(tok, []byte("tok-2"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Node(context.Background()); err != nil || gotAuth != "Bearer tok-2" {
		t.Errorf("rotated token: %q %v", gotAuth, err)
	}
	c.NodeName = "forbidden"
	if _, err := c.Node(context.Background()); err == nil || !strings.Contains(err.Error(), "HTTP 403") {
		t.Errorf("forbidden: %v", err)
	}
	// Another CA: the TLS handshake fails.
	other := httptest.NewTLSServer(http.NotFoundHandler())
	defer other.Close()
	c2, _ := NewWithCA(other.URL, "n", tok, caPEM)
	if _, err := c2.Node(context.Background()); err == nil {
		t.Error("untrusted server accepted")
	}
	if _, err := NewWithCA(srv.URL, "n", tok, []byte("no pem")); err == nil {
		t.Error("empty CA accepted")
	}
}

func TestNewInClusterNeedsPod(t *testing.T) {
	t.Setenv("KUBERNETES_SERVICE_HOST", "")
	if _, err := NewInCluster("node-1"); err == nil {
		t.Error("NewInCluster outside a pod")
	}
	if _, err := NewInCluster(""); err == nil {
		t.Error("NewInCluster with no node name")
	}
}
