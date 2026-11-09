package server

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/files"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
)

const (
	saveSession  = "5e551011-0000-4000-8000-000000000001"
	saveSession2 = "5e551011-0000-4000-8000-000000000002"
)

// fakeStore is an object store that checks the signed headers of a PUT
// like S3 does (length and SHA-256).
type fakeStore struct {
	mu      sync.Mutex
	objects map[string][]byte
	puts    int
	failPut int
}

func (f *fakeStore) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if r.URL.Query().Get("X-Amz-Signature") != "sig" {
		http.Error(w, "SignatureDoesNotMatch", http.StatusForbidden)
		return
	}
	switch r.Method {
	case http.MethodPut:
		f.puts++
		if f.failPut > 0 {
			f.failPut--
			http.Error(w, "SlowDown", http.StatusServiceUnavailable)
			return
		}
		body, _ := io.ReadAll(r.Body)
		if strconv.Itoa(len(body)) != r.Header.Get("Content-Length") && r.ContentLength != int64(len(body)) {
			http.Error(w, "IncompleteBody", http.StatusBadRequest)
			return
		}
		sum := sha256.Sum256(body)
		if want := r.Header.Get("x-amz-checksum-sha256"); want != base64.StdEncoding.EncodeToString(sum[:]) {
			http.Error(w, "BadDigest", http.StatusBadRequest)
			return
		}
		f.objects[r.URL.Path] = body
		w.Header().Set("ETag", `"`+hex.EncodeToString(sum[:8])+`"`)
	case http.MethodGet:
		b, ok := f.objects[r.URL.Path]
		if !ok {
			http.Error(w, "NoSuchKey", http.StatusNotFound)
			return
		}
		_, _ = w.Write(b)
	}
}

type saveEnv struct {
	a        *ptAgent
	store    *fakeStore
	srv      *httptest.Server
	sessions string
}

func newSaveEnv(t *testing.T) *saveEnv {
	t.Helper()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	sessions := filepath.Join(root, "sessions")
	fs, err := files.New(files.Config{SessionsRoot: sessions})
	if err != nil {
		t.Fatal(err)
	}
	vm := startFakeVMFiles(t, fs)
	a := newPTAgent(t, false, map[string]string{sandbox2: vm.uds})
	initVM(t, a, sandbox2)
	store := &fakeStore{objects: map[string][]byte{}}
	srv := httptest.NewServer(store)
	t.Cleanup(srv.Close)
	return &saveEnv{a: a, store: store, srv: srv, sessions: sessions}
}

func (e *saveEnv) put(t *testing.T, session, rel, data string) {
	t.Helper()
	p := filepath.Join(e.sessions, session, rel)
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(data), 0o644); err != nil {
		t.Fatal(err)
	}
}

func (e *saveEnv) client() pb.HostAgentClient { return pb.NewHostAgentClient(e.a.conn) }

func (e *saveEnv) captureReq(session string) *pb.CaptureSessionRequest {
	vm := e.a.vms[sandbox2]
	return &pb.CaptureSessionRequest{SandboxId: sandbox2, Attempt: vm.Attempt, Generation: vm.Generation,
		SandboxdKey: vmKey, SessionId: session}
}

// presignPut is what FileStore.presign_upload returns for S3.
func (e *saveEnv) presignPut(key string, size int64, sha string) *pb.PresignedRequest {
	raw, _ := hex.DecodeString(sha)
	return &pb.PresignedRequest{
		Url: e.srv.URL + "/bucket/" + key + "?X-Amz-Signature=sig", Method: "PUT",
		Headers: map[string]string{
			"Content-Type": "application/zstd", "Content-Length": strconv.FormatInt(size, 10),
			"x-amz-checksum-sha256": base64.StdEncoding.EncodeToString(raw),
		},
	}
}

func (e *saveEnv) presignGet(key string) *pb.PresignedRequest {
	return &pb.PresignedRequest{Url: e.srv.URL + "/bucket/" + key + "?X-Amz-Signature=sig", Method: "GET"}
}

func (e *saveEnv) restoreReq(session, key string, size int64, sha string) *pb.RestoreSessionRequest {
	vm := e.a.vms[sandbox2]
	return &pb.RestoreSessionRequest{SandboxId: sandbox2, Attempt: vm.Attempt, Generation: vm.Generation,
		SandboxdKey: vmKey, SessionId: session, Request: e.presignGet(key), SizeBytes: size, Sha256: sha}
}

func TestSaveCaptureUploadRestore(t *testing.T) {
	e := newSaveEnv(t)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	e.put(t, saveSession, "outputs/report.md", "# report")
	e.put(t, saveSession, "outputs/web/node_modules/x.js", "dep")
	e.put(t, saveSession, "attachments/a.pdf", strings.Repeat("pdf", 1000))
	c := e.client()

	cr, err := c.CaptureSession(ctx, e.captureReq(saveSession))
	if err != nil {
		t.Fatal(err)
	}
	if cr.GetFiles() != 2 || cr.GetExcluded() != 1 || len(cr.GetCaptureId()) != 32 || cr.GetSizeBytes() <= 0 {
		t.Fatalf("capture = %v", cr)
	}
	spool, err := os.ReadFile(filepath.Join(e.a.saves.Dir, cr.GetCaptureId()))
	if err != nil {
		t.Fatal(err)
	}
	if s := sha256.Sum256(spool); hex.EncodeToString(s[:]) != cr.GetSha256() || int64(len(spool)) != cr.GetSizeBytes() {
		t.Fatal("spool does not match the returned size and sha256")
	}

	// A wrong signed length is refused before any byte is sent; the spool stays.
	bad := e.presignPut("s1", cr.GetSizeBytes()+1, cr.GetSha256())
	_, err = c.UploadCapture(ctx, &pb.UploadCaptureRequest{CaptureId: cr.GetCaptureId(), Request: bad})
	if _, r := errInfo(err); r != "ARCHIVE_MISMATCH" {
		t.Fatalf("bad length: %v", err)
	}
	// A failed PUT keeps the spool for a retry.
	e.store.failPut = 1
	_, err = c.UploadCapture(ctx, &pb.UploadCaptureRequest{CaptureId: cr.GetCaptureId(),
		Request: e.presignPut("s1", cr.GetSizeBytes(), cr.GetSha256())})
	if d, r := errInfo(err); r != "TRANSFER_FAILED" || d != "hostagent.craft.onyx.app" || strings.Contains(err.Error(), "X-Amz-Signature") {
		t.Fatalf("failed put: %v", err)
	}
	up, err := c.UploadCapture(ctx, &pb.UploadCaptureRequest{CaptureId: cr.GetCaptureId(),
		Request: e.presignPut("s1", cr.GetSizeBytes(), cr.GetSha256())})
	if err != nil || up.GetHttpStatus() != 200 || up.GetSha256() != cr.GetSha256() || up.GetEtag() == "" {
		t.Fatalf("upload = %v %v", up, err)
	}
	if _, err := os.Stat(filepath.Join(e.a.saves.Dir, cr.GetCaptureId())); !os.IsNotExist(err) {
		t.Fatal("spool kept after a good upload")
	}
	_, err = c.UploadCapture(ctx, &pb.UploadCaptureRequest{CaptureId: cr.GetCaptureId(),
		Request: e.presignPut("s1", cr.GetSizeBytes(), cr.GetSha256())})
	if _, r := errInfo(err); r != "CAPTURE_NOT_FOUND" {
		t.Fatalf("second upload: %v", err)
	}

	// Restore into another session; an old file in a root is replaced.
	e.put(t, saveSession2, "outputs/stale", "old")
	rr, err := c.RestoreSession(ctx, e.restoreReq(saveSession2, "s1", cr.GetSizeBytes(), cr.GetSha256()))
	if err != nil || rr.GetFiles() != 2 {
		t.Fatalf("restore = %v %v", rr, err)
	}
	if b, _ := os.ReadFile(filepath.Join(e.sessions, saveSession2, "outputs/report.md")); string(b) != "# report" {
		t.Fatalf("restored report %q", b)
	}
	if _, err := os.Stat(filepath.Join(e.sessions, saveSession2, "outputs/stale")); !os.IsNotExist(err) {
		t.Fatal("stale file kept")
	}

	// A wrong expected hash or size changes nothing.
	e.put(t, saveSession2, "outputs/marker", "keep")
	other := strings.Repeat("0", 64)
	_, err = c.RestoreSession(ctx, e.restoreReq(saveSession2, "s1", cr.GetSizeBytes(), other))
	if _, r := errInfo(err); r != "ARCHIVE_MISMATCH" {
		t.Fatalf("wrong sha: %v", err)
	}
	_, err = c.RestoreSession(ctx, e.restoreReq(saveSession2, "s1", cr.GetSizeBytes()-1, cr.GetSha256()))
	if _, r := errInfo(err); r != "ARCHIVE_MISMATCH" {
		t.Fatalf("wrong size: %v", err)
	}
	if b, _ := os.ReadFile(filepath.Join(e.sessions, saveSession2, "outputs/marker")); string(b) != "keep" {
		t.Fatal("a refused restore changed the session")
	}
	_, err = c.RestoreSession(ctx, e.restoreReq(saveSession2, "missing", cr.GetSizeBytes(), cr.GetSha256()))
	if _, r := errInfo(err); r != "TRANSFER_FAILED" {
		t.Fatalf("missing object: %v", err)
	}
}

func TestSaveErrors(t *testing.T) {
	e := newSaveEnv(t)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	e.put(t, saveSession, "outputs/a", strings.Repeat("a", 4096))
	c := e.client()

	req := e.captureReq(saveSession)
	req.Generation++
	if _, err := c.CaptureSession(ctx, req); func() string { _, r := errInfo(err); return r }() != "INSTANCE_MISMATCH" {
		t.Fatalf("wrong generation: %v", err)
	}
	req = e.captureReq(saveSession)
	req.SandboxdKey = ""
	if _, err := c.CaptureSession(ctx, req); func() string { _, r := errInfo(err); return r }() != "INVALID_ARGUMENT" {
		t.Fatalf("no key: %v", err)
	}
	// A wrong key is the daemon's error, in its own domain.
	req.SandboxdKey = strings.Repeat("x", 32)
	_, err := c.CaptureSession(ctx, req)
	if d, r := errInfo(err); d != "sandboxd.craft.onyx.app" || r != "UNAUTHENTICATED" {
		t.Fatalf("wrong key: %v", err)
	}
	// The daemon's own errors pass through.
	_, err = c.CaptureSession(ctx, e.captureReq("not-there"))
	if d, r := errInfo(err); d != "sandboxd.craft.onyx.app" || r != "FILE_NOT_FOUND" {
		t.Fatalf("missing session: %v", err)
	}
	// The agent limit.
	e.a.saves.MaxBytes = 64
	if _, err := c.CaptureSession(ctx, e.captureReq(saveSession)); func() string { _, r := errInfo(err); return r }() != "CAPTURE_TOO_LARGE" {
		t.Fatalf("over the agent limit: %v", err)
	}
	ents, _ := os.ReadDir(e.a.saves.Dir)
	if len(ents) != 0 {
		t.Fatalf("spool left after a failed capture: %v", ents)
	}
	e.a.saves.MaxBytes = DefaultCaptureMaxBytes

	// Expiry and discard.
	cr, err := c.CaptureSession(ctx, e.captureReq(saveSession))
	if err != nil {
		t.Fatal(err)
	}
	e.a.saves.expire(cr.GetCaptureId())
	_, err = c.UploadCapture(ctx, &pb.UploadCaptureRequest{CaptureId: cr.GetCaptureId(),
		Request: e.presignPut("x", cr.GetSizeBytes(), cr.GetSha256())})
	if _, r := errInfo(err); r != "CAPTURE_NOT_FOUND" {
		t.Fatalf("expired: %v", err)
	}
	cr, _ = c.CaptureSession(ctx, e.captureReq(saveSession))
	if d, err := c.DiscardCapture(ctx, &pb.DiscardCaptureRequest{CaptureId: cr.GetCaptureId()}); err != nil || !d.GetDiscarded() {
		t.Fatalf("discard = %v %v", d, err)
	}
	if d, _ := c.DiscardCapture(ctx, &pb.DiscardCaptureRequest{CaptureId: cr.GetCaptureId()}); d.GetDiscarded() {
		t.Fatal("second discard found it")
	}
	ents, _ = os.ReadDir(e.a.saves.Dir)
	if len(ents) != 0 {
		t.Fatalf("spool left: %v", ents)
	}

	// An https-only agent refuses http URLs.
	e.a.saves.Transfer.AllowHTTP = false
	cr, _ = c.CaptureSession(ctx, e.captureReq(saveSession))
	_, err = c.UploadCapture(ctx, &pb.UploadCaptureRequest{CaptureId: cr.GetCaptureId(),
		Request: e.presignPut("x", cr.GetSizeBytes(), cr.GetSha256())})
	if _, r := errInfo(err); r != "TRANSFER_FAILED" || e.store.puts != 0 {
		t.Fatalf("http url: %v (puts %d)", err, e.store.puts)
	}
}

func TestNewSavesEmptiesSpool(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "old"), []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := NewSaves(&Saves{Dir: dir}); err != nil {
		t.Fatal(err)
	}
	if ents, _ := os.ReadDir(dir); len(ents) != 0 {
		t.Fatalf("left %v", ents)
	}
}

func TestSaveDiskReservation(t *testing.T) {
	s, err := NewSaves(&Saves{Dir: t.TempDir(), MaxBytes: 100, MinFreeBytes: 50, FreeBytes: func() (uint64, error) { return 260, nil }})
	if err != nil {
		t.Fatal(err)
	}
	if err := s.reserve(100); err != nil {
		t.Fatal(err)
	}
	if err := s.reserve(100); err != nil {
		t.Fatal(err)
	}
	// 260 - 200 - 100 < 50.
	if err := s.reserve(100); err == nil || !strings.Contains(err.Error(), "CAPACITY_DISK") {
		t.Fatalf("third reservation: %v", err)
	}
	s.release(100)
	if err := s.reserve(100); err != nil {
		t.Fatal(err)
	}
}

func TestSaveBigArchive(t *testing.T) {
	e := newSaveEnv(t)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	// 24 MiB that does not compress, in many messages.
	data := make([]byte, 24<<20)
	x := uint64(88172645463325252)
	for i := range data {
		x ^= x << 13
		x ^= x >> 7
		x ^= x << 17
		data[i] = byte(x)
	}
	e.put(t, saveSession, "outputs/blob", string(data))
	c := e.client()
	cr, err := c.CaptureSession(ctx, e.captureReq(saveSession))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.UploadCapture(ctx, &pb.UploadCaptureRequest{CaptureId: cr.GetCaptureId(),
		Request: e.presignPut("big", cr.GetSizeBytes(), cr.GetSha256())}); err != nil {
		t.Fatal(err)
	}
	if _, err := c.RestoreSession(ctx, e.restoreReq(saveSession2, "big", cr.GetSizeBytes(), cr.GetSha256())); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(filepath.Join(e.sessions, saveSession2, "outputs/blob"))
	if !bytes.Equal(b, data) {
		t.Fatal("restored blob differs")
	}
}
