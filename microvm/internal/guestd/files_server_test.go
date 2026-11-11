package guestd

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/execs"
	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/files"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

const fileSession = "0b9a8d3c-1111-4222-8333-944455556666"

func fileHarness(t *testing.T) (pb.SandboxdClient, string) {
	t.Helper()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	fs, err := files.New(files.Config{SessionsRoot: filepath.Join(root, "sessions"), MaxFileBytes: 4 << 20})
	if err != nil {
		t.Fatal(err)
	}
	h := newHarness(t, execs.Config{}, Config{Files: fs})
	return h.initialized(), filepath.Join(root, "sessions")
}

func hexSum(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

func TestFileCallsGRPC(t *testing.T) {
	c, sessions := fileHarness(t)
	ctx := keyed(context.Background())
	// 3 MiB in 1 MiB messages.
	data := bytes.Repeat([]byte("0123456789abcdef"), 3<<16)

	ws, err := c.WriteFile(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err := ws.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Header{Header: &pb.WriteFileHeader{
		SessionId: fileSession, Path: "outputs/data.bin", Size: int64(len(data)), Sha256: hexSum(data), MakeParents: true,
	}}}); err != nil {
		t.Fatal(err)
	}
	for off := 0; off < len(data); off += 1 << 20 {
		if err := ws.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Data{Data: data[off:min(off+1<<20, len(data))]}}); err != nil {
			t.Fatal(err)
		}
	}
	wr, err := ws.CloseAndRecv()
	if err != nil || wr.GetSha256() != hexSum(data) || wr.GetInfo().GetPath() != "outputs/data.bin" {
		t.Fatalf("write = %v %v", wr, err)
	}

	rs, err := c.ReadFile(ctx, &pb.ReadFileRequest{SessionId: fileSession, Path: "outputs/data.bin"})
	if err != nil {
		t.Fatal(err)
	}
	var got []byte
	first, err := rs.Recv()
	if err != nil || first.GetInfo().GetSize() != int64(len(data)) {
		t.Fatalf("first = %v %v", first, err)
	}
	for {
		m, err := rs.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		if len(m.GetData()) > files.ChunkBytes {
			t.Fatalf("chunk of %d bytes", len(m.GetData()))
		}
		got = append(got, m.GetData()...)
	}
	if !bytes.Equal(got, data) {
		t.Fatal("read data differs")
	}

	// Errors carry their reason.
	_, err = c.ListFiles(ctx, &pb.ListFilesRequest{SessionId: fileSession, Path: "nope"})
	if reason(err) != "FILE_NOT_FOUND" || status.Code(err) != codes.NotFound {
		t.Fatalf("list missing: %v", err)
	}
	_, err = c.ListFiles(ctx, &pb.ListFilesRequest{SessionId: fileSession, Path: "../x"})
	if reason(err) != "INVALID_ARGUMENT" {
		t.Fatalf("list escape: %v", err)
	}
	big, _ := c.WriteFile(ctx)
	_ = big.Send(&pb.WriteFileRequest{Part: &pb.WriteFileRequest_Header{Header: &pb.WriteFileHeader{
		SessionId: fileSession, Path: "outputs/big", Size: 5 << 20,
	}}})
	if _, err := big.CloseAndRecv(); reason(err) != "LIMIT_EXCEEDED" || status.Code(err) != codes.ResourceExhausted {
		t.Fatalf("write over limit: %v", err)
	}

	us, _ := c.UploadFile(ctx)
	_ = us.Send(&pb.UploadFileRequest{Part: &pb.UploadFileRequest_Header{Header: &pb.UploadFileHeader{
		SessionId: fileSession, FileName: "data.bin", Size: 3,
	}}})
	_ = us.Send(&pb.UploadFileRequest{Part: &pb.UploadFileRequest_Data{Data: []byte("abc")}})
	ur, err := us.CloseAndRecv()
	if err != nil || ur.GetInfo().GetPath() != "attachments/data.bin" {
		t.Fatalf("upload = %v %v", ur, err)
	}
	// A second header in the data fails.
	us, _ = c.UploadFile(ctx)
	_ = us.Send(&pb.UploadFileRequest{Part: &pb.UploadFileRequest_Header{Header: &pb.UploadFileHeader{SessionId: fileSession, FileName: "x", Size: 3}}})
	_ = us.Send(&pb.UploadFileRequest{Part: &pb.UploadFileRequest_Header{Header: &pb.UploadFileHeader{}}})
	if _, err := us.CloseAndRecv(); reason(err) != "INVALID_ARGUMENT" {
		t.Fatalf("second header: %v", err)
	}

	lr, err := c.ListFiles(ctx, &pb.ListFilesRequest{SessionId: fileSession, Recursive: true})
	if err != nil || len(lr.GetEntries()) != 4 {
		t.Fatalf("list = %v %v", lr, err)
	}

	zs, err := c.ZipFiles(ctx, &pb.ZipFilesRequest{SessionId: fileSession, Path: "outputs"})
	if err != nil {
		t.Fatal(err)
	}
	var zipBytes int64
	var summary *pb.ZipSummary
	for {
		m, err := zs.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		zipBytes += int64(len(m.GetData()))
		if m.GetSummary() != nil {
			summary = m.GetSummary()
		}
	}
	if summary.GetFiles() != 1 || summary.GetZipBytes() != zipBytes {
		t.Fatalf("zip summary %v, %d bytes", summary, zipBytes)
	}

	// Capture, then restore into another session.
	cs, err := c.CaptureSession(ctx, &pb.CaptureSessionRequest{SessionId: fileSession})
	if err != nil {
		t.Fatal(err)
	}
	var archive []byte
	var csum *pb.CaptureSummary
	for {
		m, err := cs.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		archive = append(archive, m.GetData()...)
		if m.GetSummary() != nil {
			csum = m.GetSummary()
		}
	}
	if csum.GetSha256() != hexSum(archive) || csum.GetFiles() != 2 {
		t.Fatalf("capture summary %v", csum)
	}
	other := "0b9a8d3c-1111-4222-8333-944455550000"
	rr, err := c.RestoreSession(ctx)
	if err != nil {
		t.Fatal(err)
	}
	_ = rr.Send(&pb.RestoreSessionRequest{Part: &pb.RestoreSessionRequest_Header{Header: &pb.RestoreSessionHeader{
		SessionId: other, SizeBytes: int64(len(archive)), Sha256: hexSum(archive),
	}}})
	for off := 0; off < len(archive); off += 1 << 20 {
		_ = rr.Send(&pb.RestoreSessionRequest{Part: &pb.RestoreSessionRequest_Data{Data: archive[off:min(off+1<<20, len(archive))]}})
	}
	res, err := rr.CloseAndRecv()
	if err != nil || res.GetFiles() != 2 {
		t.Fatalf("restore = %v %v", res, err)
	}
	if b, _ := os.ReadFile(filepath.Join(sessions, other, "outputs/data.bin")); !bytes.Equal(b, data) {
		t.Fatal("restored data differs")
	}

	// A restore with a wrong hash fails and changes nothing.
	rr, _ = c.RestoreSession(ctx)
	_ = rr.Send(&pb.RestoreSessionRequest{Part: &pb.RestoreSessionRequest_Header{Header: &pb.RestoreSessionHeader{
		SessionId: other, SizeBytes: int64(len(archive)), Sha256: hexSum([]byte("x")),
	}}})
	_ = rr.Send(&pb.RestoreSessionRequest{Part: &pb.RestoreSessionRequest_Data{Data: archive}})
	if _, err := rr.CloseAndRecv(); reason(err) != "ARCHIVE_INVALID" {
		t.Fatalf("bad hash: %v", err)
	}

	dr, err := c.DeleteFile(ctx, &pb.DeleteFileRequest{SessionId: fileSession, Path: "attachments", Recursive: true})
	if err != nil || !dr.GetDeleted() {
		t.Fatalf("delete = %v %v", dr, err)
	}

	// Without the key the file calls fail like every other call.
	if _, err := c.ListFiles(context.Background(), &pb.ListFilesRequest{SessionId: fileSession}); reason(err) != "UNAUTHENTICATED" {
		t.Fatalf("no key: %v", err)
	}
}

func TestListFilesResponseSizeCap(t *testing.T) {
	c, sessions := fileHarness(t)
	ctx := keyed(context.Background())
	dir := filepath.Join(sessions, fileSession, "outputs")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	for i := range 40 {
		name := fmt.Sprintf("%02d-%s", i, strings.Repeat("n", 200))
		if err := os.WriteFile(filepath.Join(dir, name), nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	orig := listMaxBytes
	t.Cleanup(func() { listMaxBytes = orig })
	listMaxBytes = 4 << 10

	lr, err := c.ListFiles(ctx, &pb.ListFilesRequest{SessionId: fileSession, Path: "outputs"})
	if err != nil {
		t.Fatal(err)
	}
	if !lr.GetTruncated() || len(lr.GetEntries()) == 0 || len(lr.GetEntries()) >= 40 {
		t.Fatalf("entries = %d, truncated = %v", len(lr.GetEntries()), lr.GetTruncated())
	}
	if n := proto.Size(lr); n > listMaxBytes {
		t.Fatalf("response of %d bytes, cap %d", n, listMaxBytes)
	}
}

func TestListFilesSkipsInvalidUTF8(t *testing.T) {
	c, sessions := fileHarness(t)
	ctx := keyed(context.Background())
	dir := filepath.Join(sessions, fileSession, "outputs")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "good.txt"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("t\xff", filepath.Join(dir, "link")); err != nil {
		t.Fatal(err)
	}
	// Some filesystems (APFS) refuse names that are not UTF-8.
	if err := os.WriteFile(filepath.Join(dir, "bad\xff.txt"), nil, 0o644); err != nil {
		t.Logf("no non-UTF-8 name on this filesystem: %v", err)
	}

	lr, err := c.ListFiles(ctx, &pb.ListFilesRequest{SessionId: fileSession, Path: "outputs"})
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, e := range lr.GetEntries() {
		names = append(names, e.GetName())
		if e.GetName() == "link" && e.GetLinkTarget() != "t�" {
			t.Fatalf("link target = %q", e.GetLinkTarget())
		}
	}
	if strings.Join(names, ",") != "good.txt,link" {
		t.Fatalf("names = %v", names)
	}
}
