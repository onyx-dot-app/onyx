package server

import (
	"bufio"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"hash"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/agent"
	"github.com/onyx-dot-app/onyx/microvm/internal/apierr"
	"github.com/onyx-dot-app/onyx/microvm/internal/transfer"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/hostagent/v1"
	sdpb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

const (
	// DefaultCaptureTTL is how long an un-uploaded capture stays spooled.
	DefaultCaptureTTL = 15 * time.Minute
	// DefaultCaptureMaxBytes caps one spooled archive (A6: 1 GiB stored).
	DefaultCaptureMaxBytes = int64(1) << 30
	// daemonKeyHeader is guestd.KeyHeader.
	daemonKeyHeader = "x-sandboxd-key"
	// restoreChunk is the data size of one RestoreSession message.
	restoreChunk = 1 << 20
	partSuffix   = ".part"
)

var (
	captureIDRE = regexp.MustCompile(`^[0-9a-f]{32}$`)
	sha256RE    = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

// Saves runs the session save calls (ENG-4572): it spools daemon captures
// on the node and moves archives with presigned URLs.
type Saves struct {
	M  *agent.Manager
	PT *Passthrough
	// Dir holds the spooled captures. NewSaves empties it.
	Dir string
	// TTL of a spooled capture. 0 means DefaultCaptureTTL.
	TTL time.Duration
	// MaxBytes caps one archive. 0 means DefaultCaptureMaxBytes.
	MaxBytes int64
	// MinFreeBytes stays free on the spool disk: a capture reserves its
	// largest size first.
	MinFreeBytes uint64
	// FreeBytes reports free bytes of Dir's file system.
	FreeBytes func() (uint64, error)
	Transfer  *transfer.Client
	Log       *slog.Logger

	mu       sync.Mutex
	caps     map[string]*spooled
	reserved int64
}

type spooled struct {
	id, path, sandboxID string
	size                int64
	sha                 string
	expires             time.Time
	busy, expired       bool
	timer               *time.Timer
}

// NewSaves returns Saves with s's settings, after it removes the spools
// that an earlier agent left (their IDs are gone with it).
func NewSaves(s *Saves) (*Saves, error) {
	if s.TTL == 0 {
		s.TTL = DefaultCaptureTTL
	}
	if s.MaxBytes == 0 {
		s.MaxBytes = DefaultCaptureMaxBytes
	}
	if s.MaxBytes < 0 || s.TTL < 0 {
		return nil, errors.New("capture limits must not be negative")
	}
	if s.Transfer == nil {
		s.Transfer = &transfer.Client{}
	}
	if s.Log == nil {
		s.Log = slog.Default()
	}
	if err := os.MkdirAll(s.Dir, 0o700); err != nil {
		return nil, err
	}
	ents, err := os.ReadDir(s.Dir)
	if err != nil {
		return nil, err
	}
	for _, e := range ents {
		if err := os.RemoveAll(filepath.Join(s.Dir, e.Name())); err != nil {
			return nil, err
		}
	}
	s.caps = map[string]*spooled{}
	return s, nil
}

// saveErr keeps daemon statuses as they are (domain sandboxd) and maps the
// agent's own errors.
func saveErr(err error) error {
	var ae *apierr.Error
	switch {
	case err == nil:
		return nil
	case errors.As(err, &ae):
		return apierr.Status(err).Err()
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		return status.FromContextError(err).Err()
	}
	if _, ok := status.FromError(err); ok {
		return err
	}
	return apierr.Status(err).Err()
}

func transferErr(err error) error {
	switch {
	case errors.Is(err, transfer.ErrMismatch):
		return apierr.New(pb.ErrorReason_ARCHIVE_MISMATCH, "%v", err)
	case errors.Is(err, context.Canceled):
		return err
	default:
		return apierr.New(pb.ErrorReason_TRANSFER_FAILED, "%v", err)
	}
}

// daemon returns a client for the guest daemon of the named VM instance,
// and a context that carries the key.
func (s *Saves) daemon(ctx context.Context, id string, attempt, gen uint64, key string) (sdpb.SandboxdClient, *upstream, context.Context, error) {
	if key == "" {
		return nil, nil, nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "sandboxd_key is required")
	}
	if err := validateDaemonKey(key); err != nil {
		return nil, nil, nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "sandboxd_key: %v", err)
	}
	if _, err := s.M.Instance(id, attempt, gen); err != nil {
		return nil, nil, nil, err
	}
	u, err := s.PT.get(id)
	if err != nil {
		return nil, nil, nil, err
	}
	if u.gen != gen {
		return nil, nil, nil, apierr.New(pb.ErrorReason_VM_NOT_RUNNING, "sandbox %s was replaced during the call", id)
	}
	return sdpb.NewSandboxdClient(u.conn), u, metadata.NewOutgoingContext(ctx, metadata.Pairs(daemonKeyHeader, key)), nil
}

func (s *Saves) reserve(n int64) error {
	free := uint64(0)
	if s.FreeBytes != nil {
		f, err := s.FreeBytes()
		if err != nil {
			return apierr.New(pb.ErrorReason_INTERNAL, "spool disk: %v", err)
		}
		free = f
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.FreeBytes != nil && int64(free)-s.reserved-n < int64(s.MinFreeBytes) {
		return apierr.New(pb.ErrorReason_CAPACITY_DISK, "the spool disk has %d bytes free, %d reserved; a capture needs %d",
			free, s.reserved, n)
	}
	s.reserved += n
	return nil
}

func (s *Saves) release(n int64) {
	s.mu.Lock()
	s.reserved -= n
	s.mu.Unlock()
}

func newCaptureID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}

// hashWriter counts and hashes what goes to the spool file.
type hashWriter struct {
	w   io.Writer
	h   hash.Hash
	n   int64
	max int64
}

func (w *hashWriter) Write(p []byte) (int, error) {
	if w.n+int64(len(p)) > w.max {
		return 0, apierr.New(pb.ErrorReason_CAPTURE_TOO_LARGE, "the archive is over %d bytes", w.max)
	}
	n, err := w.w.Write(p)
	w.h.Write(p[:n])
	w.n += int64(n)
	return n, err
}

// Capture runs CaptureSession.
func (s *Saves) Capture(ctx context.Context, r *pb.CaptureSessionRequest) (*pb.CaptureSessionResponse, error) {
	start := time.Now()
	maxBytes := s.MaxBytes
	if v := r.GetLimits().GetMaxStoredBytes(); v != 0 {
		if v < 0 || v > s.MaxBytes {
			return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "limits.max_stored_bytes must be 1 to %d", s.MaxBytes)
		}
		maxBytes = v
	}
	client, u, dctx, err := s.daemon(ctx, r.GetSandboxId(), r.GetAttempt(), r.GetGeneration(), r.GetSandboxdKey())
	if err != nil {
		return nil, err
	}
	if err := s.reserve(maxBytes); err != nil {
		return nil, err
	}
	defer s.release(maxBytes)

	id := newCaptureID()
	part := filepath.Join(s.Dir, id+partSuffix)
	f, err := os.OpenFile(part, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return nil, apierr.New(pb.ErrorReason_INTERNAL, "spool: %v", err)
	}
	ok := false
	defer func() {
		_ = f.Close()
		if !ok {
			_ = os.Remove(part)
		}
	}()
	dctx, cancel := context.WithCancel(dctx)
	defer cancel()
	lim := r.GetLimits()
	stream, err := client.CaptureSession(dctx, &sdpb.CaptureSessionRequest{
		SessionId: r.GetSessionId(), Roots: r.GetRoots(), ExcludeNames: r.GetExcludeNames(),
		Limits: &sdpb.ArchiveLimits{
			MaxStoredBytes: lim.GetMaxStoredBytes(), MaxExpandedBytes: lim.GetMaxExpandedBytes(), MaxEntries: lim.GetMaxEntries(),
		},
	})
	if err != nil {
		return nil, s.PT.upstreamErr(ctx, u, r.GetSandboxId(), err, true)
	}
	bw := bufio.NewWriterSize(f, 1<<20)
	hw := &hashWriter{w: bw, h: sha256.New(), max: maxBytes}
	var sum *sdpb.CaptureSummary
	for {
		m, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, s.PT.upstreamErr(ctx, u, r.GetSandboxId(), err, false)
		}
		if sum != nil {
			return nil, apierr.New(pb.ErrorReason_INTERNAL, "guest daemon sent data after the summary")
		}
		if d := m.GetData(); len(d) > 0 {
			if _, err := hw.Write(d); err != nil {
				return nil, err
			}
		}
		if m.GetSummary() != nil {
			sum = m.GetSummary()
		}
	}
	got := hex.EncodeToString(hw.h.Sum(nil))
	if sum == nil || sum.GetStoredBytes() != hw.n || sum.GetSha256() != got {
		return nil, apierr.New(pb.ErrorReason_INTERNAL, "the capture stream does not match the daemon summary")
	}
	if err := bw.Flush(); err != nil {
		return nil, apierr.New(pb.ErrorReason_INTERNAL, "spool: %v", err)
	}
	if err := f.Close(); err != nil {
		return nil, apierr.New(pb.ErrorReason_INTERNAL, "spool: %v", err)
	}
	final := filepath.Join(s.Dir, id)
	if err := os.Rename(part, final); err != nil {
		return nil, apierr.New(pb.ErrorReason_INTERNAL, "spool: %v", err)
	}
	ok = true
	sp := &spooled{id: id, path: final, sandboxID: r.GetSandboxId(), size: hw.n, sha: got, expires: time.Now().Add(s.TTL)}
	s.mu.Lock()
	s.caps[id] = sp
	sp.timer = time.AfterFunc(s.TTL, func() { s.expire(id) })
	s.mu.Unlock()
	ms := time.Since(start).Milliseconds()
	s.Log.Info("capture spooled", "sandbox_id", r.GetSandboxId(), "session_id", r.GetSessionId(), "capture_id", id,
		"bytes", hw.n, "files", sum.GetFiles(), "expanded_bytes", sum.GetExpandedBytes(), "ms", ms)
	return &pb.CaptureSessionResponse{
		CaptureId: id, SizeBytes: hw.n, Sha256: got, Files: sum.GetFiles(), Directories: sum.GetDirectories(),
		ExpandedBytes: sum.GetExpandedBytes(), Excluded: sum.GetExcluded(), Skipped: sum.GetSkipped(),
		Changed: sum.GetChanged(), Roots: sum.GetRoots(), CaptureMs: uint64(ms), ExpiresAt: timestamppb.New(sp.expires),
	}, nil
}

// expire deletes a spool at its TTL, or after its running upload.
func (s *Saves) expire(id string) {
	s.mu.Lock()
	sp := s.caps[id]
	if sp == nil {
		s.mu.Unlock()
		return
	}
	sp.expired = true
	if sp.busy {
		s.mu.Unlock()
		return
	}
	delete(s.caps, id)
	s.mu.Unlock()
	_ = os.Remove(sp.path)
	s.Log.Info("capture expired", "capture_id", id, "sandbox_id", sp.sandboxID)
}

// drop deletes a spool that is not busy.
func (s *Saves) drop(sp *spooled) {
	s.mu.Lock()
	delete(s.caps, sp.id)
	s.mu.Unlock()
	if sp.timer != nil {
		sp.timer.Stop()
	}
	_ = os.Remove(sp.path)
}

// Upload runs UploadCapture.
func (s *Saves) Upload(ctx context.Context, r *pb.UploadCaptureRequest) (*pb.UploadCaptureResponse, error) {
	start := time.Now()
	id := r.GetCaptureId()
	if !captureIDRE.MatchString(id) {
		return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "capture_id is not a capture ID")
	}
	s.mu.Lock()
	sp := s.caps[id]
	switch {
	case sp == nil || sp.expired:
		s.mu.Unlock()
		return nil, apierr.New(pb.ErrorReason_CAPTURE_NOT_FOUND, "no spooled capture %s (uploaded, discarded or expired)", id)
	case sp.busy:
		s.mu.Unlock()
		return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "capture %s is being uploaded", id)
	}
	sp.busy = true
	s.mu.Unlock()
	done := false
	defer func() {
		s.mu.Lock()
		sp.busy = false
		expired := sp.expired
		s.mu.Unlock()
		if done || expired {
			s.drop(sp)
		}
	}()

	f, err := os.Open(sp.path)
	if err != nil {
		return nil, apierr.New(pb.ErrorReason_INTERNAL, "spool: %v", err)
	}
	defer func() { _ = f.Close() }()
	pr := r.GetRequest()
	res, err := s.Transfer.Put(ctx, transfer.Request{URL: pr.GetUrl(), Method: pr.GetMethod(), Headers: pr.GetHeaders()},
		f, sp.size)
	if err != nil {
		return nil, transferErr(err)
	}
	done = true
	ms := time.Since(start).Milliseconds()
	s.Log.Info("capture uploaded", "capture_id", id, "sandbox_id", sp.sandboxID, "bytes", sp.size, "status", res.Status,
		"url", transfer.Redacted(pr.GetUrl()), "ms", ms)
	return &pb.UploadCaptureResponse{SizeBytes: sp.size, Sha256: sp.sha, HttpStatus: uint32(res.Status), Etag: res.ETag,
		UploadMs: uint64(ms)}, nil
}

// Discard runs DiscardCapture.
func (s *Saves) Discard(r *pb.DiscardCaptureRequest) (*pb.DiscardCaptureResponse, error) {
	s.mu.Lock()
	sp := s.caps[r.GetCaptureId()]
	if sp == nil {
		s.mu.Unlock()
		return &pb.DiscardCaptureResponse{}, nil
	}
	if sp.busy {
		// The running upload deletes it when it ends.
		sp.expired = true
		s.mu.Unlock()
		return &pb.DiscardCaptureResponse{Discarded: true}, nil
	}
	s.mu.Unlock()
	s.drop(sp)
	return &pb.DiscardCaptureResponse{Discarded: true}, nil
}

// Restore runs RestoreSession.
func (s *Saves) Restore(ctx context.Context, r *pb.RestoreSessionRequest) (*pb.RestoreSessionResponse, error) {
	start := time.Now()
	want := strings.ToLower(r.GetSha256())
	if !sha256RE.MatchString(want) {
		return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "sha256 must be 64 hex characters")
	}
	size := r.GetSizeBytes()
	if size <= 0 || size > s.MaxBytes {
		return nil, apierr.New(pb.ErrorReason_INVALID_ARGUMENT, "size_bytes must be 1 to %d", s.MaxBytes)
	}
	client, u, dctx, err := s.daemon(ctx, r.GetSandboxId(), r.GetAttempt(), r.GetGeneration(), r.GetSandboxdKey())
	if err != nil {
		return nil, err
	}
	pr := r.GetRequest()
	body, err := s.Transfer.Get(ctx, transfer.Request{URL: pr.GetUrl(), Method: pr.GetMethod(), Headers: pr.GetHeaders()}, size)
	if err != nil {
		return nil, transferErr(err)
	}
	defer func() { _ = body.Close() }()

	dctx, cancel := context.WithCancel(dctx)
	defer cancel()
	stream, err := client.RestoreSession(dctx)
	if err != nil {
		return nil, s.PT.upstreamErr(ctx, u, r.GetSandboxId(), err, true)
	}
	lim := r.GetLimits()
	if err := stream.Send(&sdpb.RestoreSessionRequest{Part: &sdpb.RestoreSessionRequest_Header{Header: &sdpb.RestoreSessionHeader{
		SessionId: r.GetSessionId(), SizeBytes: size, Sha256: want, Roots: r.GetRoots(),
		Limits: &sdpb.ArchiveLimits{
			MaxStoredBytes: lim.GetMaxStoredBytes(), MaxExpandedBytes: lim.GetMaxExpandedBytes(), MaxEntries: lim.GetMaxEntries(),
		},
	}}}); err != nil {
		return nil, s.restoreSendErr(ctx, u, r.GetSandboxId(), stream, err)
	}
	h := sha256.New()
	var n int64
	var readWait, sendWait time.Duration
	buf := make([]byte, restoreChunk)
	for {
		t0 := time.Now()
		k, rerr := io.ReadFull(body, buf)
		readWait += time.Since(t0)
		if k > 0 {
			n += int64(k)
			if n > size {
				return nil, apierr.New(pb.ErrorReason_ARCHIVE_MISMATCH, "the object has more than %d bytes", size)
			}
			h.Write(buf[:k])
			t1 := time.Now()
			if err := stream.Send(&sdpb.RestoreSessionRequest{Part: &sdpb.RestoreSessionRequest_Data{Data: buf[:k]}}); err != nil {
				return nil, s.restoreSendErr(ctx, u, r.GetSandboxId(), stream, err)
			}
			sendWait += time.Since(t1)
		}
		if errors.Is(rerr, io.EOF) || errors.Is(rerr, io.ErrUnexpectedEOF) {
			break
		}
		if rerr != nil {
			return nil, transferErr(rerr)
		}
	}
	if got := hex.EncodeToString(h.Sum(nil)); n != size || got != want {
		// Returning cancels the daemon call, so it replaces nothing.
		return nil, apierr.New(pb.ErrorReason_ARCHIVE_MISMATCH, "downloaded %d bytes with sha256 %s, want %d bytes with %s",
			n, got, size, want)
	}
	resp, err := stream.CloseAndRecv()
	if err != nil {
		return nil, s.PT.upstreamErr(ctx, u, r.GetSandboxId(), err, false)
	}
	ms := time.Since(start).Milliseconds()
	s.Log.Info("session restored", "sandbox_id", r.GetSandboxId(), "session_id", r.GetSessionId(), "bytes", size,
		"files", resp.GetFiles(), "url", transfer.Redacted(pr.GetUrl()), "ms", ms,
		"download_wait_ms", readWait.Milliseconds(), "send_wait_ms", sendWait.Milliseconds())
	return &pb.RestoreSessionResponse{Files: resp.GetFiles(), Directories: resp.GetDirectories(),
		ExpandedBytes: resp.GetExpandedBytes(), Roots: resp.GetRoots(), RestoreMs: uint64(ms)}, nil
}

// restoreSendErr gets the daemon's status after a failed Send (io.EOF
// means the daemon ended the call).
func (s *Saves) restoreSendErr(ctx context.Context, u *upstream, id string,
	stream grpc.ClientStreamingClient[sdpb.RestoreSessionRequest, sdpb.RestoreSessionResponse], err error) error {
	if errors.Is(err, io.EOF) {
		_, err = stream.CloseAndRecv()
		if err == nil {
			err = status.Error(codes.Internal, "guest daemon ended the restore early")
		}
	}
	return s.PT.upstreamErr(ctx, u, id, err, false)
}

// CaptureSession implements pb.HostAgentServer.
func (s *Service) CaptureSession(ctx context.Context, r *pb.CaptureSessionRequest) (*pb.CaptureSessionResponse, error) {
	if s.Saves == nil {
		return nil, status.Error(codes.Unimplemented, "session saves are off on this node")
	}
	resp, err := s.Saves.Capture(ctx, r)
	return resp, saveErr(err)
}

// UploadCapture implements pb.HostAgentServer.
func (s *Service) UploadCapture(ctx context.Context, r *pb.UploadCaptureRequest) (*pb.UploadCaptureResponse, error) {
	if s.Saves == nil {
		return nil, status.Error(codes.Unimplemented, "session saves are off on this node")
	}
	resp, err := s.Saves.Upload(ctx, r)
	return resp, saveErr(err)
}

// DiscardCapture implements pb.HostAgentServer.
func (s *Service) DiscardCapture(_ context.Context, r *pb.DiscardCaptureRequest) (*pb.DiscardCaptureResponse, error) {
	if s.Saves == nil {
		return nil, status.Error(codes.Unimplemented, "session saves are off on this node")
	}
	resp, err := s.Saves.Discard(r)
	return resp, saveErr(err)
}

// RestoreSession implements pb.HostAgentServer.
func (s *Service) RestoreSession(ctx context.Context, r *pb.RestoreSessionRequest) (*pb.RestoreSessionResponse, error) {
	if s.Saves == nil {
		return nil, status.Error(codes.Unimplemented, "session saves are off on this node")
	}
	resp, err := s.Saves.Restore(ctx, r)
	if err != nil {
		return nil, saveErr(err)
	}
	return resp, nil
}
