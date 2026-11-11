package nodereport

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/relay"
)

func newSigner(t *testing.T) *relay.Signer {
	t.Helper()
	_, key, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	return relay.NewSigner("node-a", "node-a-1700000000-0a0b0c0d", key)
}

func quiet() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

func oneVM() []VM {
	started := time.Date(2026, 11, 10, 12, 0, 0, 0, time.UTC)
	return []VM{{
		SandboxID: "3b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69", TenantID: "public", Attempt: 2, Generation: 1700000000123,
		State: "RUNNING", Template: "v1-abc", VCPUs: 2, MemMiB: 4096, ScratchGiB: 4, PID: 42, StartedAt: &started,
	}}
}

// decode checks the token signature and returns its header and claims.
func decode(s *relay.Signer, token string) (tokenHeader, map[string]any, bool) {
	var h tokenHeader
	var c map[string]any
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return h, c, false
	}
	sig, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil || !ed25519.Verify(s.PublicKey(), []byte(parts[0]+"."+parts[1]), sig) {
		return h, c, false
	}
	for i, out := range []any{&h, &c} {
		raw, err := base64.RawURLEncoding.DecodeString(parts[i])
		if err != nil || json.Unmarshal(raw, out) != nil {
			return h, c, false
		}
	}
	return h, c, true
}

func verify(t *testing.T, s *relay.Signer, token string) (tokenHeader, map[string]any) {
	t.Helper()
	h, c, ok := decode(s, token)
	if !ok {
		t.Fatal("bad token")
	}
	return h, c
}

// signal sends without blocking, so a stopped reader never blocks a sender.
func signal(ch chan struct{}) {
	select {
	case ch <- struct{}{}:
	default:
	}
}

func TestTokenFields(t *testing.T) {
	s := newSigner(t)
	now := time.Unix(1_800_000_000, 0)
	r := &Reporter{Signer: s, Now: func() time.Time { return now }}
	body, err := Body(s.NodeID, oneVM(), nil)
	if err != nil {
		t.Fatal(err)
	}
	token, err := r.Token(body)
	if err != nil {
		t.Fatal(err)
	}
	h, c := verify(t, s, token)
	if h.Alg != "EdDSA" || h.Typ != "JWT" || h.Kid != s.KeyID {
		t.Fatalf("header %+v", h)
	}
	sum := sha256.Sum256(body)
	if c["node"] != "node-a" || c["aud"] != Audience || c["aud"] == relay.Audience ||
		c["iat"] != float64(now.Unix()) || c["exp"] != float64(now.Add(60*time.Second).Unix()) ||
		c["body_sha256"] != hex.EncodeToString(sum[:]) {
		t.Fatalf("claims %v", c)
	}
	if jti, _ := c["jti"].(string); len(jti) != 32 {
		t.Fatalf("jti %v", c["jti"])
	}
	if len(c) != 6 {
		t.Fatalf("unexpected claims %v", c)
	}
	again, _ := r.Token(body)
	if _, c2 := verify(t, s, again); c2["jti"] == c["jti"] {
		t.Fatal("two tokens share a jti")
	}
}

func TestBodyCaps(t *testing.T) {
	body, err := Body("node-a", nil, nil)
	if err != nil || string(body) != `{"node_id":"node-a","vms":[],"ended":[]}` {
		t.Fatalf("empty body %q %v", body, err)
	}
	var got report
	body, _ = Body("node-a", oneVM(), nil)
	if err := json.Unmarshal(body, &got); err != nil || len(got.VMs) != 1 || got.VMs[0].State != "RUNNING" {
		t.Fatalf("body %s", body)
	}
	if !strings.Contains(string(body), `"started_at":"2026-11-10T12:00:00Z"`) {
		t.Fatalf("started_at missing: %s", body)
	}
	if _, err := Body("node-a", make([]VM, MaxVMs+1), nil); err == nil {
		t.Fatal("accepted more than MaxVMs")
	}
	big := make([]VM, 2)
	for i := range big {
		big[i].Template = strings.Repeat("x", MaxBodyBytes/2)
	}
	if _, err := Body("node-a", big, nil); err == nil {
		t.Fatal("accepted a body over MaxBodyBytes")
	}
}

func TestBodyHasEndedVMs(t *testing.T) {
	at := time.Date(2026, 11, 10, 12, 5, 0, 0, time.UTC)
	ended := []EndedVM{{
		SandboxID: "3b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69", TenantID: "public", Attempt: 1, Generation: 1700000000100,
		Reason: "EXITED", EndedAt: at,
	}}
	body, err := Body("node-a", oneVM(), ended)
	if err != nil {
		t.Fatal(err)
	}
	var got report
	if err := json.Unmarshal(body, &got); err != nil || len(got.Ended) != 1 || got.Ended[0] != ended[0] {
		t.Fatalf("body %s", body)
	}
	if !strings.Contains(string(body), `"ended_at":"2026-11-10T12:05:00Z"`) ||
		!strings.Contains(string(body), `"reason":"EXITED"`) {
		t.Fatalf("ended fields: %s", body)
	}

	many := make([]EndedVM, MaxEnded+2)
	for i := range many {
		many[i] = EndedVM{SandboxID: "s", Generation: uint64(i), Reason: "STOPPED", EndedAt: at}
	}
	body, err = Body("node-a", nil, many)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(body, &got); err != nil || len(got.Ended) != MaxEnded || got.Ended[0].Generation != 2 {
		t.Fatalf("over the cap: %d entries, first generation %d", len(got.Ended), got.Ended[0].Generation)
	}
}

func TestSendIncludesEnded(t *testing.T) {
	bodies := make(chan []byte, 1)
	s := newSigner(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		bodies <- b
		_, _ = w.Write([]byte(`{"reconciled":true}`))
	}))
	t.Cleanup(srv.Close)
	r := &Reporter{
		BaseURL: srv.URL, Signer: s, List: oneVM, Log: quiet(),
		Ended: func() []EndedVM {
			return []EndedVM{{SandboxID: "x", Attempt: 3, Generation: 9, Reason: "STOPPED", EndedAt: time.Unix(0, 0).UTC()}}
		},
	}
	if err := r.Send(t.Context()); err != nil {
		t.Fatal(err)
	}
	var got report
	if err := json.Unmarshal(<-bodies, &got); err != nil || len(got.VMs) != 1 || len(got.Ended) != 1 ||
		got.Ended[0].Attempt != 3 || got.Ended[0].Generation != 9 {
		t.Fatalf("sent %+v %v", got, err)
	}
}

func TestBackoff(t *testing.T) {
	for _, c := range []struct {
		interval, max time.Duration
		failures      int
		want          time.Duration
	}{
		{15 * time.Second, 2 * time.Minute, 0, 15 * time.Second},
		{15 * time.Second, 2 * time.Minute, 1, 30 * time.Second},
		{15 * time.Second, 2 * time.Minute, 3, 2 * time.Minute},
		{15 * time.Second, 2 * time.Minute, 1000, 2 * time.Minute},
		{5 * time.Minute, 2 * time.Minute, 4, 5 * time.Minute},
	} {
		if got := Backoff(c.interval, c.max, c.failures); got != c.want {
			t.Errorf("Backoff(%v, %v, %d) = %v, want %v", c.interval, c.max, c.failures, got, c.want)
		}
	}
}

type recorder struct {
	mu       sync.Mutex
	requests int
	fail     int
	got      chan struct{}
	signer   *relay.Signer
}

func (rec *recorder) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	rec.mu.Lock()
	rec.requests++
	n := rec.requests
	rec.mu.Unlock()
	defer signal(rec.got)
	if r.Method != http.MethodPost || r.URL.Path != Path || r.Header.Get("Content-Type") != "application/json" {
		http.Error(w, "bad route", http.StatusNotFound)
		return
	}
	token, ok := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer ")
	if !ok {
		http.Error(w, "no token", http.StatusUnauthorized)
		return
	}
	_, c, ok := decode(rec.signer, token)
	sum := sha256.Sum256(body)
	if !ok || c["body_sha256"] != hex.EncodeToString(sum[:]) {
		http.Error(w, "body hash", http.StatusUnauthorized)
		return
	}
	if n <= rec.fail {
		http.Error(w, "down", http.StatusServiceUnavailable)
		return
	}
	_, _ = w.Write([]byte(`{"reconciled":true}`))
}

func (rec *recorder) count() int {
	rec.mu.Lock()
	defer rec.mu.Unlock()
	return rec.requests
}

func newReporter(t *testing.T, rec *recorder, ready <-chan struct{}) (*Reporter, *httptest.Server) {
	t.Helper()
	srv := httptest.NewServer(rec)
	t.Cleanup(srv.Close)
	return &Reporter{
		BaseURL: srv.URL + "/", Signer: rec.signer, List: oneVM, Ready: ready, Log: quiet(),
		Interval: 5 * time.Millisecond, MaxBackoff: 20 * time.Millisecond,
	}, srv
}

func TestRunWaitsForRegistrationThenReports(t *testing.T) {
	rec := &recorder{got: make(chan struct{}, 64), signer: newSigner(t)}
	ready := make(chan struct{})
	r, _ := newReporter(t, rec, ready)
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan struct{})
	go func() { r.Run(ctx); close(done) }()

	select {
	case <-rec.got:
		t.Fatal("reported before the key registration")
	case <-time.After(50 * time.Millisecond):
	}
	close(ready)
	for i := 0; i < 3; i++ {
		select {
		case <-rec.got:
		case <-time.After(5 * time.Second):
			t.Fatalf("report %d did not arrive", i+1)
		}
	}
	cancel()
	<-done
}

func TestRunKeepsGoingAfterFailures(t *testing.T) {
	rec := &recorder{got: make(chan struct{}, 64), signer: newSigner(t), fail: 3}
	ready := make(chan struct{})
	close(ready)
	r, _ := newReporter(t, rec, ready)
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan struct{})
	go func() { r.Run(ctx); close(done) }()
	for i := 0; i < 5; i++ {
		select {
		case <-rec.got:
		case <-time.After(5 * time.Second):
			t.Fatalf("request %d did not arrive", i+1)
		}
	}
	cancel()
	<-done
	if rec.count() < 5 {
		t.Fatalf("%d requests", rec.count())
	}
}

func TestRunSurvivesPanicAndUnreachableServer(t *testing.T) {
	ready := make(chan struct{})
	close(ready)
	calls := make(chan struct{}, 8)
	var n atomic.Int32
	r := &Reporter{
		BaseURL: "http://127.0.0.1:1", Signer: newSigner(t), Ready: ready, Log: quiet(),
		Interval: time.Millisecond, MaxBackoff: 2 * time.Millisecond,
		List: func() []VM {
			signal(calls)
			if n.Add(1) == 1 {
				panic("boom")
			}
			return nil
		},
		Client: &http.Client{Timeout: time.Second},
	}
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan struct{})
	go func() { r.Run(ctx); close(done) }()
	for i := 0; i < 3; i++ {
		select {
		case <-calls:
		case <-time.After(5 * time.Second):
			t.Fatalf("attempt %d did not happen", i+1)
		}
	}
	cancel()
	<-done
}

func TestOversizedReportIsNotSent(t *testing.T) {
	rec := &recorder{got: make(chan struct{}, 4), signer: newSigner(t)}
	r, _ := newReporter(t, rec, nil)
	r.List = func() []VM { return make([]VM, MaxVMs+1) }
	if err := r.Send(t.Context()); err == nil {
		t.Fatal("sent a report over the cap")
	}
	if rec.count() != 0 {
		t.Fatal("the server got an oversized report")
	}
}

func TestSendReportsHTTPErrors(t *testing.T) {
	rec := &recorder{got: make(chan struct{}, 4), signer: newSigner(t), fail: 1}
	r, _ := newReporter(t, rec, nil)
	err := r.Send(t.Context())
	if err == nil || !strings.Contains(err.Error(), "HTTP 503") {
		t.Fatalf("err %v", err)
	}
	if err := r.Send(t.Context()); err != nil {
		t.Fatal(err)
	}
}

func TestRunObservesEachResult(t *testing.T) {
	rec := &recorder{got: make(chan struct{}, 64), signer: newSigner(t), fail: 1}
	ready := make(chan struct{})
	close(ready)
	r, _ := newReporter(t, rec, ready)
	results := make(chan error, 64)
	r.Observe = func(err error) { results <- err }
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan struct{})
	go func() { r.Run(ctx); close(done) }()
	var got []error
	for len(got) < 2 {
		select {
		case err := <-results:
			got = append(got, err)
		case <-time.After(5 * time.Second):
			t.Fatalf("result %d did not arrive", len(got)+1)
		}
	}
	cancel()
	<-done
	var h *relay.HTTPStatusError
	if !errors.As(got[0], &h) || h.HTTPStatus() != http.StatusServiceUnavailable {
		t.Fatalf("first result %v", got[0])
	}
	if got[1] != nil {
		t.Fatalf("second result %v", got[1])
	}
}
