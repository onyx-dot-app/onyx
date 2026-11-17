package egressca

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/pem"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/testcerts"
)

func newCA(t *testing.T, name string) *testcerts.CA {
	t.Helper()
	ca, err := testcerts.NewCA(name)
	if err != nil {
		t.Fatal(err)
	}
	return ca
}

func TestParse(t *testing.T) {
	ca := newCA(t, "egress CA")
	got, err := Parse(append([]byte("# comment\n"), ca.PEM...))
	if err != nil {
		t.Fatal(err)
	}
	block, _ := pem.Decode(ca.PEM)
	sum := sha256.Sum256(block.Bytes)
	if got.Fingerprint != hex.EncodeToString(sum[:]) || string(got.PEM) != string(ca.PEM) || got.Cert.Subject.CommonName != "egress CA" {
		t.Fatalf("parsed %+v", got)
	}

	leaf, key, err := ca.Leaf("server", true)
	if err != nil {
		t.Fatal(err)
	}
	other := newCA(t, "other")
	for name, raw := range map[string][]byte{
		"empty":       nil,
		"not PEM":     []byte("hello"),
		"leaf":        leaf,
		"two certs":   append(append([]byte{}, ca.PEM...), other.PEM...),
		"private key": append(append([]byte{}, ca.PEM...), key...),
		"too large":   append(append([]byte{}, ca.PEM...), []byte(strings.Repeat("#", MaxPEMBytes))...),
	} {
		if _, err := Parse(raw); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestFile(t *testing.T) {
	ca := newCA(t, "file CA")
	p := filepath.Join(t.TempDir(), "ca.crt")
	src := File{Path: p}
	if _, err := src.CA(context.Background()); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("missing file: %v", err)
	}
	if err := os.WriteFile(p, ca.PEM, 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := src.CA(context.Background())
	if err != nil || string(got.PEM) != string(ca.PEM) {
		t.Fatalf("%v %v", got, err)
	}
	if err := os.WriteFile(p, []byte("junk"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := src.CA(context.Background()); err == nil || !strings.Contains(err.Error(), p) {
		t.Fatalf("junk file: %v", err)
	}
}

type fakeGetter struct {
	data map[string]string
	err  error
	n    int
}

func (f *fakeGetter) ConfigMap(_ context.Context, ns, name string) (map[string]string, error) {
	f.n++
	if ns != "onyx-sandboxes" || name != "sandbox-proxy-ca-bundle" {
		return nil, errors.New("wrong object " + ns + "/" + name)
	}
	return f.data, f.err
}

func TestConfigMap(t *testing.T) {
	ca := newCA(t, "proxy CA")
	g := &fakeGetter{data: map[string]string{"ca.crt": string(ca.PEM)}}
	src := ConfigMap{Getter: g, Namespace: "onyx-sandboxes", Name: "sandbox-proxy-ca-bundle", Key: "ca.crt"}
	got, err := src.CA(context.Background())
	if err != nil || string(got.PEM) != string(ca.PEM) {
		t.Fatalf("%v %v", got, err)
	}
	src.Key = "other"
	if _, err := src.CA(context.Background()); err == nil || !strings.Contains(err.Error(), "no key other") {
		t.Fatalf("missing key: %v", err)
	}
}

func TestParseConfigMapRef(t *testing.T) {
	for ref, want := range map[string][3]string{
		"onyx-sandboxes/sandbox-proxy-ca-bundle":        {"onyx-sandboxes", "sandbox-proxy-ca-bundle", "ca.crt"},
		"onyx-sandboxes/sandbox-proxy-ca-bundle:tls.ca": {"onyx-sandboxes", "sandbox-proxy-ca-bundle", "tls.ca"},
	} {
		ns, name, key, err := ParseConfigMapRef(ref)
		if err != nil || [3]string{ns, name, key} != want {
			t.Errorf("%s: %s %s %s %v", ref, ns, name, key, err)
		}
	}
	for _, bad := range []string{"", "name", "/name", "ns/", "ns/a/b", "ns/name:"} {
		if _, _, _, err := ParseConfigMapRef(bad); err == nil {
			t.Errorf("%q accepted", bad)
		}
	}
}

func TestCached(t *testing.T) {
	ca1, ca2 := newCA(t, "one"), newCA(t, "two")
	g := &fakeGetter{err: errors.New("HTTP 403")}
	now := time.Unix(1000, 0)
	c := &Cached{Src: ConfigMap{Getter: g, Namespace: "onyx-sandboxes", Name: "sandbox-proxy-ca-bundle", Key: "ca.crt"},
		TTL: 30 * time.Second, Now: func() time.Time { return now }}
	ctx := context.Background()
	// No CA yet and the read fails: an error.
	if _, _, err := c.Get(ctx); err == nil {
		t.Fatal("no error without a CA")
	}
	// A failed read is not repeated before RetryAfter.
	g.err, g.data = nil, map[string]string{"ca.crt": string(ca1.PEM)}
	if _, _, err := c.Get(ctx); err == nil || g.n != 1 {
		t.Fatalf("read again before RetryAfter: %v, %d reads", err, g.n)
	}
	now = now.Add(DefaultRetryAfter)
	got, refreshErr, err := c.Get(ctx)
	if err != nil || refreshErr != nil || string(got.PEM) != string(ca1.PEM) {
		t.Fatalf("first read: %v %v", refreshErr, err)
	}
	// Within the TTL: no read.
	g.data = map[string]string{"ca.crt": string(ca2.PEM)}
	n := g.n
	if got, _, _ = c.Get(ctx); string(got.PEM) != string(ca1.PEM) || g.n != n {
		t.Fatal("read within the TTL")
	}
	// After the TTL: the new CA.
	now = now.Add(31 * time.Second)
	if got, _, _ = c.Get(ctx); string(got.PEM) != string(ca2.PEM) {
		t.Fatal("rotated CA not read")
	}
	// A failed refresh keeps the last good CA and reports the failure.
	now = now.Add(31 * time.Second)
	g.err = errors.New("API down")
	got, refreshErr, err = c.Get(ctx)
	if err != nil || refreshErr == nil || string(got.PEM) != string(ca2.PEM) {
		t.Fatalf("stale: %v %v", refreshErr, err)
	}
}

func TestCachedMaxAge(t *testing.T) {
	ca1 := newCA(t, "one")
	g := &fakeGetter{data: map[string]string{"ca.crt": string(ca1.PEM)}}
	now := time.Unix(1000, 0)
	c := &Cached{Src: ConfigMap{Getter: g, Namespace: "onyx-sandboxes", Name: "sandbox-proxy-ca-bundle", Key: "ca.crt"},
		TTL: 30 * time.Second, MaxAge: time.Hour, Now: func() time.Time { return now }}
	ctx := context.Background()
	if _, _, err := c.Get(ctx); err != nil {
		t.Fatal(err)
	}
	g.err = errors.New("API down")
	now = now.Add(59 * time.Minute)
	if got, refreshErr, err := c.Get(ctx); err != nil || refreshErr == nil || got == nil {
		t.Fatalf("within MaxAge: %v %v", refreshErr, err)
	}
	// Past MaxAge the last CA is not used.
	now = now.Add(2 * time.Minute)
	n := g.n
	if _, _, err := c.Get(ctx); err == nil || !strings.Contains(err.Error(), "API down") || g.n != n+1 {
		t.Fatalf("past MaxAge: %v, %d reads", err, g.n-n)
	}
	// The backoff still applies.
	if _, _, err := c.Get(ctx); err == nil || g.n != n+1 {
		t.Fatalf("past MaxAge, before RetryAfter: %v, %d reads", err, g.n-n)
	}
}

// blockingSource blocks each read until release is closed or its context ends.
type blockingSource struct {
	ca      *CA
	release chan struct{}
	started chan struct{}
	reads   atomic.Int32
}

func (b *blockingSource) String() string { return "blocking" }

func (b *blockingSource) CA(ctx context.Context) (*CA, error) {
	b.reads.Add(1)
	b.started <- struct{}{}
	select {
	case <-b.release:
		return b.ca, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func TestCachedSlowSource(t *testing.T) {
	ca1, err := Parse(newCA(t, "one").PEM)
	if err != nil {
		t.Fatal(err)
	}
	src := &blockingSource{ca: ca1, release: make(chan struct{}), started: make(chan struct{}, 4)}
	var mu sync.Mutex
	now := time.Unix(1000, 0)
	clock := func() time.Time { mu.Lock(); defer mu.Unlock(); return now }
	c := &Cached{Src: src, TTL: 30 * time.Second, ReadTimeout: 50 * time.Millisecond, Now: clock}
	// The read times out; a caller with no deadline does not wait longer.
	if _, _, err := c.Get(context.Background()); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("slow read: %v", err)
	}
	<-src.started
	// A caller that cancels stops waiting for a read that another caller
	// started, and the read goes on.
	c.ReadTimeout = time.Minute
	mu.Lock()
	now = now.Add(DefaultRetryAfter)
	mu.Unlock()
	first := make(chan error, 1)
	go func() { _, _, err := c.Get(context.Background()); first <- err }()
	<-src.started
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, _, err := c.Get(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelled waiter: %v", err)
	}
	close(src.release)
	if err := <-first; err != nil {
		t.Fatal(err)
	}
	// After the TTL, a read in progress does not block callers: they get
	// the last CA.
	src.release = make(chan struct{})
	mu.Lock()
	now = now.Add(time.Minute)
	mu.Unlock()
	go func() { _, _, err := c.Get(context.Background()); first <- err }()
	<-src.started
	got, refreshErr, err := c.Get(context.Background())
	if err != nil || refreshErr != nil || string(got.PEM) != string(ca1.PEM) {
		t.Fatalf("during a read: %v %v", refreshErr, err)
	}
	close(src.release)
	if err := <-first; err != nil {
		t.Fatal(err)
	}
	if n := src.reads.Load(); n != 3 {
		t.Fatalf("%d reads, want 3", n)
	}
}
