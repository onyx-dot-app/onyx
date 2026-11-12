package relay

import (
	"bufio"
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
)

type vectorFile struct {
	Now      int64  `json:"now"`
	Node     string `json:"node"`
	Kid      string `json:"kid"`
	NodeSeed string `json:"node_seed_hex"`
	Other    string `json:"other_seed_hex"`
	Cases    []struct {
		Name       string  `json:"name"`
		HeaderJSON string  `json:"header_json"`
		ClaimsJSON string  `json:"claims_json"`
		Signer     string  `json:"signer"`
		Rejection  *string `json:"rejection"`
	} `json:"cases"`
}

func loadVectors(t *testing.T) vectorFile {
	t.Helper()
	raw, err := os.ReadFile("testdata/signed_identity_vectors.json")
	if err != nil {
		t.Fatal(err)
	}
	// The vectors are shared with the proxy tests. Keep the copy equal once
	// the proxy file is in this tree.
	backend := filepath.Join("..", "..", "..", "backend", "tests", "unit", "sandbox_proxy", "signed_identity_vectors.json")
	switch other, err := os.ReadFile(backend); {
	case errors.Is(err, os.ErrNotExist):
		// The proxy file is not in this tree yet.
	case err != nil:
		t.Fatalf("read %s: %v", backend, err)
	case !bytes.Equal(other, raw):
		t.Fatalf("testdata vectors differ from %s; copy the proxy file", backend)
	}
	var v vectorFile
	if err := json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	return v
}

func seedKey(t *testing.T, hexSeed string) ed25519.PrivateKey {
	t.Helper()
	seed, err := hex.DecodeString(hexSeed)
	if err != nil {
		t.Fatal(err)
	}
	return ed25519.NewKeyFromSeed(seed)
}

// TestSharedVectors signs the exact vector bytes and checks them against the
// node public key, as the proxy verifier does.
func TestSharedVectors(t *testing.T) {
	v := loadVectors(t)
	node := NewSigner(v.Node, v.Kid, seedKey(t, v.NodeSeed))
	other := NewSigner(v.Node, v.Kid, seedKey(t, v.Other))
	enc := base64.RawURLEncoding
	signed := 0
	for _, c := range v.Cases {
		var s *Signer
		switch c.Signer {
		case "node":
			s = node
		case "other":
			s = other
		default:
			continue // HS256: the relay never signs it.
		}
		tok := s.SignRaw([]byte(c.HeaderJSON), []byte(c.ClaimsJSON))
		parts := strings.Split(tok, ".")
		if len(parts) != 3 {
			t.Fatalf("%s: %d parts", c.Name, len(parts))
		}
		h, _ := enc.DecodeString(parts[0])
		cl, _ := enc.DecodeString(parts[1])
		if string(h) != c.HeaderJSON || string(cl) != c.ClaimsJSON {
			t.Fatalf("%s: signed bytes differ from the vector", c.Name)
		}
		sig, _ := enc.DecodeString(parts[2])
		ok := ed25519.Verify(node.PublicKey(), []byte(parts[0]+"."+parts[1]), sig)
		if ok != (c.Signer == "node") {
			t.Fatalf("%s: verify with the node key = %v", c.Name, ok)
		}
		signed++
	}
	if signed < 9 {
		t.Fatalf("signed %d vectors", signed)
	}
}

// TestWriteTokensForProxyVerifier writes live relay tokens for the Python
// verifier check (set RELAY_TOKENS_OUT). See the module README.
func TestWriteTokensForProxyVerifier(t *testing.T) {
	out := os.Getenv("RELAY_TOKENS_OUT")
	if out == "" {
		t.Skip("RELAY_TOKENS_OUT not set")
	}
	v := loadVectors(t)
	s := NewSigner(v.Node, v.Kid, seedKey(t, v.NodeSeed))
	s.now = func() time.Time { return time.Unix(v.Now, 0) }
	sub, _ := Subject("public", "0b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69")
	var toks []string
	for _, gen := range []uint64{0, 3, 1793811989739705740} {
		tok, err := s.Token(sub, gen)
		if err != nil {
			t.Fatal(err)
		}
		toks = append(toks, tok)
	}
	raw, _ := json.Marshal(map[string]any{"now": v.Now, "tokens": toks})
	if err := os.WriteFile(out, raw, 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestTokenClaims(t *testing.T) {
	v := loadVectors(t)
	s := NewSigner(v.Node, v.Kid, seedKey(t, v.NodeSeed))
	s.now = func() time.Time { return time.Unix(v.Now, 0) }
	sub, err := Subject("public", "0b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69")
	if err != nil {
		t.Fatal(err)
	}
	tok, err := s.Token(sub, 3)
	if err != nil {
		t.Fatal(err)
	}
	parts := strings.Split(tok, ".")
	h, _ := base64.RawURLEncoding.DecodeString(parts[0])
	if string(h) != v.Cases[0].HeaderJSON {
		t.Fatalf("header %s, want %s", h, v.Cases[0].HeaderJSON)
	}
	cl, _ := base64.RawURLEncoding.DecodeString(parts[1])
	var c map[string]any
	if err := json.Unmarshal(cl, &c); err != nil {
		t.Fatal(err)
	}
	if c["sub"] != sub || c["node"] != v.Node || c["gen"] != float64(3) ||
		c["iat"] != float64(v.Now) || c["exp"] != float64(v.Now+60) || len(c["jti"].(string)) != 32 ||
		c["aud"] != "sandbox-proxy" {
		t.Fatalf("claims %s", cl)
	}
	want := `{"sub":"` + sub + `","gen":3,"node":"node-a","iat":1800000000,"exp":1800000060,"jti":"`
	if !strings.HasPrefix(string(cl), want) {
		t.Fatalf("claim order: %s", cl)
	}
	if _, err := Subject("bad/tenant", "x"); err == nil {
		t.Fatal("bad tenant accepted")
	}
}

func readHead(t *testing.T, s string) (*Head, error) {
	t.Helper()
	return ReadHead(bufio.NewReader(strings.NewReader(s)))
}

func TestNewKeyIDIsUnique(t *testing.T) {
	now := time.Unix(1800000000, 0)
	a, err := NewKeyID("node-a", now)
	if err != nil {
		t.Fatal(err)
	}
	b, _ := NewKeyID("node-a", now)
	if a == b || !strings.HasPrefix(a, "node-a-1800000000-") || len(a) != len("node-a-1800000000-")+8 {
		t.Fatalf("key ids %q %q", a, b)
	}
}

func TestIdleTimeout(t *testing.T) {
	for _, c := range []struct{ in, want time.Duration }{
		{0, DefaultIdleTimeout},
		{-time.Second, DefaultIdleTimeout},
		{60 * time.Second, MinIdleTimeout},
		{MinIdleTimeout, MinIdleTimeout},
		{time.Hour, time.Hour},
	} {
		if got := (&Relay{IdleTimeout: c.in}).idle(); got != c.want {
			t.Errorf("idle(%v) = %v, want %v", c.in, got, c.want)
		}
	}
}

func TestHeadStripAndStamp(t *testing.T) {
	basic := base64.StdEncoding.EncodeToString([]byte("sess-42:x"))
	h, err := readHead(t, "GET http://example.com/a HTTP/1.1\r\nHost: example.com\r\n"+
		"Proxy-Authorization: Basic "+basic+"\r\nproxy-authorization: Bearer forged\r\n"+
		"X-Onyx-Session-Hint: forged\r\nConnection: keep-alive\r\nProxy-Connection: keep-alive\r\nKeep-Alive: 5\r\n\r\n")
	if err != nil {
		t.Fatal(err)
	}
	h.Stamp("TOKEN")
	got := string(h.Bytes())
	want := "GET http://example.com/a HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n" +
		"Proxy-Authorization: Bearer TOKEN\r\nX-Onyx-Session-Hint: sess-42\r\n\r\n"
	if got != want {
		t.Fatalf("stamped head\n got %q\nwant %q", got, want)
	}

	// CONNECT and Upgrade keep their Connection header.
	h, _ = readHead(t, "CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\nProxy-Connection: keep-alive\r\n\r\n")
	h.Stamp("T")
	if s := string(h.Bytes()); !strings.Contains(s, "Proxy-Connection: keep-alive") || strings.Contains(s, "Connection: close") || strings.Contains(s, SessionHintHeader) {
		t.Fatalf("CONNECT head %q", s)
	}
	h, _ = readHead(t, "GET http://h/ws HTTP/1.1\r\nHost: h\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n")
	h.Stamp("T")
	if s := string(h.Bytes()); !strings.Contains(s, "Connection: Upgrade") {
		t.Fatalf("upgrade head %q", s)
	}
	// A hint with control bytes is dropped.
	evil := base64.StdEncoding.EncodeToString([]byte("a\r\nX-Evil: 1:p"))
	h, _ = readHead(t, "CONNECT h:443 HTTP/1.1\r\nProxy-Authorization: Basic "+evil+"\r\n\r\n")
	h.Stamp("T")
	if s := string(h.Bytes()); strings.Contains(s, "Evil") || strings.Contains(s, SessionHintHeader) {
		t.Fatalf("unsafe hint passed: %q", s)
	}
}

func TestHeadRejects(t *testing.T) {
	for name, in := range map[string]string{
		"bare LF":       "GET / HTTP/1.1\nHost: x\r\n\r\n",
		"obs-fold":      "GET / HTTP/1.1\r\nHost: x\r\n folded\r\n\r\n",
		"bad line":      "GET /  HTTP/1.1\r\n\r\n",
		"bad version":   "GET / HTTP/2\r\n\r\n",
		"no colon":      "GET / HTTP/1.1\r\nHost x\r\n\r\n",
		"space in name": "GET / HTTP/1.1\r\nHo st: x\r\n\r\n",
		"empty":         "\r\n",
		"too big":       "GET / HTTP/1.1\r\n" + strings.Repeat("X-A: "+strings.Repeat("a", 1000)+"\r\n", 70) + "\r\n",
	} {
		if _, err := readHead(t, in); !errors.Is(err, ErrBadHead) {
			t.Errorf("%s: err %v, want ErrBadHead", name, err)
		}
	}
}

// upstream records the head of each connection and answers it.
type upstream struct {
	ln    net.Listener
	mu    sync.Mutex
	heads []string
}

func newUpstream(t *testing.T) *upstream {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	u := &upstream{ln: ln}
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go u.serve(c)
		}
	}()
	t.Cleanup(func() { _ = ln.Close() })
	return u
}

func (u *upstream) serve(c net.Conn) {
	defer func() { _ = c.Close() }()
	br := bufio.NewReader(c)
	var head strings.Builder
	for {
		l, err := br.ReadString('\n')
		if err != nil {
			return
		}
		head.WriteString(l)
		if l == "\r\n" {
			break
		}
	}
	u.mu.Lock()
	u.heads = append(u.heads, head.String())
	u.mu.Unlock()
	if strings.HasPrefix(head.String(), "CONNECT ") {
		_, _ = io.WriteString(c, "HTTP/1.1 200 Connection established\r\n\r\n")
		_, _ = io.Copy(c, br) // echo the tunnel
		return
	}
	_, _ = io.WriteString(c, "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
}

func (u *upstream) lastHead() string {
	u.mu.Lock()
	defer u.mu.Unlock()
	if len(u.heads) == 0 {
		return ""
	}
	return u.heads[len(u.heads)-1]
}

func newRelay(t *testing.T, up *upstream, opts ...func(*Relay)) (*Relay, string, VM) {
	t.Helper()
	v := loadVectors(t)
	r := &Relay{Signer: NewSigner(v.Node, v.Kid, seedKey(t, v.NodeSeed)), Upstream: up.ln.Addr().String(),
		Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	for _, o := range opts {
		o(r)
	}
	sock := shortSock(t, "relay")
	ln, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	vm := VM{SandboxID: "0b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69", Subject: "spiffe://onyx/tenant/public/sandbox/0b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69", Generation: 7}
	go r.Serve(ln, vm)
	t.Cleanup(func() { r.Detach(vm.SandboxID); _ = os.Remove(sock) })
	return r, sock, vm
}

func TestPlainHTTPGetsConnectionClose(t *testing.T) {
	up := newUpstream(t)
	_, sock, _ := newRelay(t, up)
	c, err := net.Dial("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	_, _ = io.WriteString(c, "GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\nConnection: keep-alive\r\nProxy-Authorization: Bearer vm-forged\r\n\r\n")
	resp, err := http.ReadResponse(bufio.NewReader(c), nil)
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	if string(body) != "ok" {
		t.Fatalf("body %q", body)
	}
	h := up.lastHead()
	if !strings.Contains(h, "Connection: close\r\n") || strings.Contains(h, "keep-alive") || strings.Contains(h, "vm-forged") ||
		strings.Count(h, "Proxy-Authorization: Bearer ") != 1 {
		t.Fatalf("upstream head %q", h)
	}
}

func TestConnectStampsThenSplices(t *testing.T) {
	up := newUpstream(t)
	_, sock, vm := newRelay(t, up)
	c, err := net.Dial("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	// The tunnel bytes right after the head must not be lost or parsed.
	_, _ = io.WriteString(c, "CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\nGET /inner HTTP/1.1\r\nProxy-Authorization: x\r\n\r\n")
	br := bufio.NewReader(c)
	resp, err := http.ReadResponse(br, &http.Request{Method: http.MethodConnect})
	if err != nil || resp.StatusCode != 200 {
		t.Fatalf("connect: %v %v", resp, err)
	}
	echo := make([]byte, len("GET /inner HTTP/1.1\r\nProxy-Authorization: x\r\n\r\n"))
	if _, err := io.ReadFull(br, echo); err != nil || !strings.HasPrefix(string(echo), "GET /inner") {
		t.Fatalf("tunnel echo %q %v", echo, err)
	}
	h := up.lastHead()
	parts := strings.SplitN(h, "Proxy-Authorization: Bearer ", 2)
	if len(parts) != 2 {
		t.Fatalf("no token in %q", h)
	}
	tok := strings.TrimSpace(strings.SplitN(parts[1], "\r\n", 2)[0])
	seg := strings.Split(tok, ".")
	cl, _ := base64.RawURLEncoding.DecodeString(seg[1])
	if !strings.Contains(string(cl), `"sub":"`+vm.Subject+`","gen":7,"node":"node-a"`) {
		t.Fatalf("claims %s", cl)
	}
}

func TestCloseAll(t *testing.T) {
	up := newUpstream(t)
	r, sock, vm := newRelay(t, up)
	var conns []net.Conn
	for i := 0; i < 5; i++ {
		c, err := net.Dial("unix", sock)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = io.WriteString(c, "CONNECT example.com:443 HTTP/1.1\r\n\r\n")
		if _, err := http.ReadResponse(bufio.NewReader(c), &http.Request{Method: http.MethodConnect}); err != nil {
			t.Fatal(err)
		}
		conns = append(conns, c)
	}
	waitFor(t, func() bool { return r.Live(vm.SandboxID) == 5 })
	if n := r.CloseAll(vm.SandboxID); n != 5 {
		t.Fatalf("closed %d", n)
	}
	for i, c := range conns {
		_ = c.SetReadDeadline(time.Now().Add(2 * time.Second))
		if _, err := c.Read(make([]byte, 1)); err == nil || isTimeout(err) {
			t.Fatalf("conn %d still open after CloseAll: %v", i, err)
		}
		_ = c.Close()
	}
	// The listener stays: a new connection works.
	c, err := net.Dial("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	_, _ = io.WriteString(c, "GET http://x/ HTTP/1.1\r\nHost: x\r\n\r\n")
	if _, err := http.ReadResponse(bufio.NewReader(c), nil); err != nil {
		t.Fatalf("after CloseAll: %v", err)
	}
}

func TestBadHeadGets400(t *testing.T) {
	up := newUpstream(t)
	_, sock, _ := newRelay(t, up)
	c, err := net.Dial("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	_, _ = io.WriteString(c, "GET / HTTP/1.1\nHost: x\n\n")
	resp, err := http.ReadResponse(bufio.NewReader(c), nil)
	if err != nil || resp.StatusCode != 400 {
		t.Fatalf("bad head: %v %v", resp, err)
	}
	if up.lastHead() != "" {
		t.Fatal("a bad head reached the proxy")
	}
}

// TestFDsFlatAfterManyConnections: the prototype leaked 2 fds per closed
// connection. Open and close 10k connections and compare the fd count.
func TestFDsFlatAfterManyConnections(t *testing.T) {
	if runtime.GOOS != "linux" && runtime.GOOS != "darwin" {
		t.Skip("needs /dev/fd")
	}
	up := newUpstream(t)
	r, sock, vm := newRelay(t, up)
	one := func(i int) {
		c, err := net.Dial("unix", sock)
		if err != nil {
			t.Fatal(err)
		}
		if i%2 == 0 {
			_, _ = io.WriteString(c, "GET http://x/ HTTP/1.1\r\nHost: x\r\n\r\n")
			resp, err := http.ReadResponse(bufio.NewReader(c), nil)
			if err != nil {
				t.Fatalf("conn %d: %v", i, err)
			}
			_, _ = io.Copy(io.Discard, resp.Body)
		} else {
			// A client that sends a CONNECT and goes away.
			_, _ = io.WriteString(c, "CONNECT x:443 HTTP/1.1\r\n\r\n")
		}
		_ = c.Close()
	}
	for i := 0; i < 200; i++ {
		one(i)
	}
	waitFor(t, func() bool { return r.Live(vm.SandboxID) == 0 })
	before := fdCount(t)
	var wg sync.WaitGroup
	for w := 0; w < 20; w++ {
		wg.Add(1)
		go func(w int) {
			defer wg.Done()
			for i := 0; i < 500; i++ {
				one(w*500 + i)
			}
		}(w)
	}
	wg.Wait()
	waitFor(t, func() bool { return r.Live(vm.SandboxID) == 0 })
	var after int
	waitFor(t, func() bool { after = fdCount(t); return after <= before+5 })
	t.Logf("fds before %d, after 10000 connections %d", before, after)
}

func fdCount(t *testing.T) int {
	t.Helper()
	ents, err := os.ReadDir("/dev/fd")
	if err != nil {
		t.Fatal(err)
	}
	return len(ents)
}

func waitFor(t *testing.T, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatal("condition not met in 10 s")
		}
		time.Sleep(5 * time.Millisecond)
	}
}

func isTimeout(err error) bool {
	var ne net.Error
	return errors.As(err, &ne) && ne.Timeout()
}

func TestRegistrar(t *testing.T) {
	v := loadVectors(t)
	s := NewSigner(v.Node, v.Kid, seedKey(t, v.NodeSeed))
	var got registration
	var auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPut || r.URL.Path != SigningKeyPath {
			http.Error(w, "bad route", http.StatusNotFound)
			return
		}
		auth = r.Header.Get("Authorization")
		_ = json.NewDecoder(r.Body).Decode(&got)
		if auth != "Bearer s3cret" {
			http.Error(w, "no", http.StatusUnauthorized)
		}
	}))
	defer srv.Close()
	g := &Registrar{BaseURL: srv.URL + "/", Secret: "s3cret", Signer: s, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	if err := g.Register(t.Context()); err != nil {
		t.Fatal(err)
	}
	pub, _ := base64.StdEncoding.DecodeString(got.PublicKey)
	if got.NodeID != "node-a" || got.KeyID != "node-a-1" || !bytes.Equal(pub, s.PublicKey()) || got.AgentAddress != "" {
		t.Fatalf("registration %+v", got)
	}
	g.AgentAddress = "10.0.3.7:7443"
	if err := g.Register(t.Context()); err != nil {
		t.Fatal(err)
	}
	if got.AgentAddress != "10.0.3.7:7443" {
		t.Fatalf("agent address %+v", got)
	}
	g.Secret = "wrong"
	if err := g.Register(t.Context()); err == nil || !strings.Contains(err.Error(), "401") {
		t.Fatalf("wrong secret: %v", err)
	}
}

// connect opens a CONNECT tunnel through the relay.
func connect(t *testing.T, sock string) net.Conn {
	t.Helper()
	c, err := net.Dial("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.WriteString(c, "CONNECT example.com:443 HTTP/1.1\r\n\r\n")
	if _, err := http.ReadResponse(bufio.NewReader(c), &http.Request{Method: http.MethodConnect}); err != nil {
		t.Fatal(err)
	}
	return c
}

// closeConn records whether Close was called.
type closeConn struct {
	net.Conn
	closed chan struct{}
	once   sync.Once
}

func (c *closeConn) Close() error {
	c.once.Do(func() { close(c.closed) })
	return c.Conn.Close()
}

func TestCloseAllDuringTheDialClosesTheNewSocket(t *testing.T) {
	up := newUpstream(t)
	dialing := make(chan struct{})
	release := make(chan struct{})
	upConn := make(chan *closeConn, 1)
	r, sock, vm := newRelay(t, up, func(r *Relay) {
		r.dial = func(ctx context.Context, network, addr string) (net.Conn, error) {
			close(dialing)
			<-release
			c, err := (&net.Dialer{}).DialContext(ctx, network, addr)
			if err != nil {
				return nil, err
			}
			cc := &closeConn{Conn: c, closed: make(chan struct{})}
			upConn <- cc
			return cc, nil
		}
	})
	c, err := net.Dial("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	_, _ = io.WriteString(c, "CONNECT example.com:443 HTTP/1.1\r\n\r\n")
	<-dialing
	if n := r.CloseAll(vm.SandboxID); n != 1 {
		t.Fatalf("closed %d, want 1", n)
	}
	close(release)
	select {
	case <-(<-upConn).closed:
	case <-time.After(5 * time.Second):
		t.Fatal("the upstream socket of a closed pair leaked")
	}
}

func TestConnectionCap(t *testing.T) {
	up := newUpstream(t)
	r, sock, vm := newRelay(t, up, func(r *Relay) { r.MaxConns = 2 })
	a, b := connect(t, sock), connect(t, sock)
	defer func() { _ = b.Close() }()
	over, err := net.Dial("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = over.Close() }()
	_ = over.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := over.Read(make([]byte, 1)); !errors.Is(err, io.EOF) {
		t.Fatalf("connection over the cap: %v, want EOF", err)
	}
	_ = a.Close()
	waitFor(t, func() bool { return r.Live(vm.SandboxID) == 1 })
	// A slot is free again. The relay may still be freeing it, so retry.
	waitFor(t, func() bool {
		c, err := net.Dial("unix", sock)
		if err != nil {
			return false
		}
		defer func() { _ = c.Close() }()
		_ = c.SetDeadline(time.Now().Add(time.Second))
		_, _ = io.WriteString(c, "GET http://x/ HTTP/1.1\r\nHost: x\r\n\r\n")
		_, err = http.ReadResponse(bufio.NewReader(c), nil)
		return err == nil
	})
}

// flakyListener fails its first Accept calls with a passing error.
type flakyListener struct {
	net.Listener
	fails int
}

func (l *flakyListener) Accept() (net.Conn, error) {
	if l.fails > 0 {
		l.fails--
		return nil, &net.OpError{Op: "accept", Net: "unix", Err: syscall.EMFILE}
	}
	return l.Listener.Accept()
}

func TestAcceptErrorsDoNotStopTheRelay(t *testing.T) {
	up := newUpstream(t)
	r, _, _ := newRelay(t, up)
	sock := shortSock(t, "relay-flaky")
	ln, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	vm := VM{SandboxID: "1b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69", Subject: "s", Generation: 1}
	r.Start(&flakyListener{Listener: ln, fails: 3}, vm)
	t.Cleanup(func() { r.Detach(vm.SandboxID) })
	c, err := net.Dial("unix", sock)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	_ = c.SetDeadline(time.Now().Add(5 * time.Second))
	_, _ = io.WriteString(c, "GET http://x/ HTTP/1.1\r\nHost: x\r\n\r\n")
	if _, err := http.ReadResponse(bufio.NewReader(c), nil); err != nil {
		t.Fatalf("after accept errors: %v", err)
	}
}

func TestStartRegistersTheListenerAtOnce(t *testing.T) {
	up := newUpstream(t)
	r, _, _ := newRelay(t, up)
	dir, err := os.MkdirTemp("/tmp", "reg")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	path := filepath.Join(dir, "v.sock_3128")
	vm := VM{SandboxID: "3b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69", Subject: "s", Generation: 1}
	for i := 0; i < 100; i++ {
		ln, err := net.Listen("unix", path)
		if err != nil {
			t.Fatal(err)
		}
		r.Start(ln, vm)
		r.Detach(vm.SandboxID)
		if c, err := net.Dial("unix", path); err == nil {
			_ = c.Close()
			t.Fatalf("round %d: the relay listens after Detach", i)
		}
	}
	// A new listener on the same path replaces the old one; closing the
	// old one must not remove the new socket file.
	old, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	r.Start(old, vm)
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	ln, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	r.Start(ln, vm)
	defer r.Detach(vm.SandboxID)
	if c, err := net.Dial("unix", path); err != nil {
		t.Fatalf("after the second Start: %v", err)
	} else {
		_ = c.Close()
	}
}

func TestAttachRegistersTheListenerBeforeItReturns(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("needs root (chown to the VM UID)")
	}
	up := newUpstream(t)
	r, _, _ := newRelay(t, up)
	dir, err := os.MkdirTemp("/tmp", "att")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	a := &AgentEgress{Relay: r}
	vm := agent.VM{SandboxID: "2b5f8a52-6a4e-4f63-9a8f-3f1d2c4b5a69", TenantID: "public", Generation: 1, UID: 1000001}
	info := agent.ProcInfo{VsockUDS: filepath.Join(dir, "v.sock")}
	path := info.VsockUDS + "_3128"
	for i := 0; i < 100; i++ {
		if err := a.Attach(vm, info); err != nil {
			t.Fatal(err)
		}
		a.Detach(vm.SandboxID)
		if c, err := net.Dial("unix", path); err == nil {
			_ = c.Close()
			t.Fatalf("round %d: the relay listens after Detach", i)
		}
	}
	// Attach twice: the second socket must keep working.
	for i := 0; i < 2; i++ {
		if err := a.Attach(vm, info); err != nil {
			t.Fatal(err)
		}
	}
	defer a.Detach(vm.SandboxID)
	c, err := net.Dial("unix", path)
	if err != nil {
		t.Fatalf("after a second Attach: %v", err)
	}
	defer func() { _ = c.Close() }()
	_ = c.SetDeadline(time.Now().Add(5 * time.Second))
	_, _ = io.WriteString(c, "GET http://x/ HTTP/1.1\r\nHost: x\r\n\r\n")
	if _, err := http.ReadResponse(bufio.NewReader(c), nil); err != nil {
		t.Fatalf("after a second Attach: %v", err)
	}
}

func TestRegistrarRegisteredClosesAfterFirstSuccess(t *testing.T) {
	var ok atomic.Bool
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if !ok.Load() {
			http.Error(w, "down", http.StatusServiceUnavailable)
		}
	}))
	defer srv.Close()
	_, key, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	g := &Registrar{BaseURL: srv.URL, Secret: "s", Signer: NewSigner("node-a", "node-a-1", key), Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	ready := g.Registered()
	if err := g.Register(t.Context()); err == nil {
		t.Fatal("a failed registration returned nil")
	}
	select {
	case <-ready:
		t.Fatal("Registered closed after a failure")
	default:
	}
	ok.Store(true)
	for i := 0; i < 2; i++ {
		if err := g.Register(t.Context()); err != nil {
			t.Fatal(err)
		}
	}
	select {
	case <-ready:
	default:
		t.Fatal("Registered did not close after a success")
	}
	if g.Registered() != ready {
		t.Fatal("Registered returned another channel")
	}
}

func TestRegistrarRunObservesEachResult(t *testing.T) {
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if calls.Add(1) == 1 {
			http.Error(w, "bad secret", http.StatusUnauthorized)
		}
	}))
	defer srv.Close()
	_, key, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatal(err)
	}
	results := make(chan error, 8)
	g := &Registrar{
		BaseURL: srv.URL, Secret: "s", Signer: NewSigner("node-a", "node-a-1", key),
		Log: slog.New(slog.NewTextHandler(io.Discard, nil)), Interval: time.Millisecond, Retry: time.Millisecond,
		Observe: func(err error) {
			// Never block Run: only the first results are checked.
			select {
			case results <- err:
			default:
			}
		},
	}
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan struct{})
	go func() { g.Run(ctx); close(done) }()
	var first, second error
	for i, dst := range []*error{&first, &second} {
		select {
		case *dst = <-results:
		case <-time.After(5 * time.Second):
			t.Fatalf("result %d did not arrive", i+1)
		}
	}
	cancel()
	<-done
	var h *HTTPStatusError
	if !errors.As(first, &h) || h.HTTPStatus() != http.StatusUnauthorized || !strings.Contains(first.Error(), "HTTP 401: bad secret") {
		t.Fatalf("first result %v", first)
	}
	if second != nil {
		t.Fatalf("second result %v", second)
	}
}
