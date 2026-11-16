package guestd

import (
	"bufio"
	"context"
	"errors"
	"io"
	"time"

	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/encoding/protowire"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/onyx-dot-app/onyx/microvm/internal/guestd/files"
	pb "github.com/onyx-dot-app/onyx/microvm/proto/sandboxd/v1"
)

// streamChunkBytes is the data size of one zip or capture message.
const streamChunkBytes = 1 << 20

// listMaxBytes caps the encoded size of a ListFiles response. It stays below
// the node agent pass-through's 16 MiB message limit.
var listMaxBytes = 12 << 20

// fileError maps a files error to a gRPC status.
func fileError(err error) error {
	switch {
	case err == nil:
		return nil
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		return execError(err)
	case errors.Is(err, files.ErrInvalid):
		return apiError(pb.ErrorReason_INVALID_ARGUMENT, "%v", err)
	case errors.Is(err, files.ErrNotFound):
		return apiError(pb.ErrorReason_FILE_NOT_FOUND, "%v", err)
	case errors.Is(err, files.ErrExists):
		return apiError(pb.ErrorReason_FILE_EXISTS, "%v", err)
	case errors.Is(err, files.ErrLimit):
		return apiError(pb.ErrorReason_LIMIT_EXCEEDED, "%v", err)
	case errors.Is(err, files.ErrArchive):
		return apiError(pb.ErrorReason_ARCHIVE_INVALID, "%v", err)
	}
	if _, ok := status.FromError(err); ok {
		// Already a status, for example from the client stream.
		return err
	}
	return apiError(pb.ErrorReason_INTERNAL, "%v", err)
}

var fileTypes = map[files.Type]pb.FileType{
	files.TypeRegular:   pb.FileType_FILE_TYPE_REGULAR,
	files.TypeDirectory: pb.FileType_FILE_TYPE_DIRECTORY,
	files.TypeSymlink:   pb.FileType_FILE_TYPE_SYMLINK,
	files.TypeOther:     pb.FileType_FILE_TYPE_OTHER,
}

func toFileInfo(i files.Info) *pb.FileInfo {
	return &pb.FileInfo{
		Path: i.Path, Name: i.Name, Type: fileTypes[i.Type], Size: i.Size, Mode: i.Mode,
		ModifiedAt: timestamppb.New(i.ModTime), LinkTarget: i.LinkTarget,
	}
}

func toLimits(l *pb.ArchiveLimits) files.Limits {
	return files.Limits{StoredBytes: l.GetMaxStoredBytes(), ExpandedBytes: l.GetMaxExpandedBytes(), Entries: l.GetMaxEntries()}
}

// sendWriter turns writes into data messages of at most streamChunkBytes.
type sendWriter func([]byte) error

func (f sendWriter) Write(p []byte) (int, error) {
	for off := 0; off < len(p); off += streamChunkBytes {
		if err := f(p[off:min(off+streamChunkBytes, len(p))]); err != nil {
			return off, err
		}
	}
	return len(p), nil
}

// dataReader reads the data messages that follow a header.
type dataReader struct {
	recv func() ([]byte, bool, error)
	buf  []byte
	// wait is the time spent waiting for messages.
	wait time.Duration
}

func (d *dataReader) Read(p []byte) (int, error) {
	for len(d.buf) == 0 {
		t0 := time.Now()
		b, isData, err := d.recv()
		d.wait += time.Since(t0)
		if err != nil {
			return 0, err
		}
		if !isData {
			return 0, apiError(pb.ErrorReason_INVALID_ARGUMENT, "only the first message may be a header")
		}
		d.buf = b
	}
	n := copy(p, d.buf)
	d.buf = d.buf[n:]
	return n, nil
}

// ReadFile implements pb.SandboxdServer.
func (s *Server) ReadFile(r *pb.ReadFileRequest, stream pb.Sandboxd_ReadFileServer) error {
	return fileError(s.files.Read(stream.Context(), r.GetSessionId(), r.GetPath(), r.GetOffset(), r.GetLength(),
		func(i files.Info) error {
			return stream.Send(&pb.ReadFileResponse{Part: &pb.ReadFileResponse_Info{Info: toFileInfo(i)}})
		},
		func(b []byte) error {
			return stream.Send(&pb.ReadFileResponse{Part: &pb.ReadFileResponse_Data{Data: b}})
		}))
}

// WriteFile implements pb.SandboxdServer.
func (s *Server) WriteFile(stream pb.Sandboxd_WriteFileServer) error {
	first, err := stream.Recv()
	if err != nil {
		return err
	}
	h := first.GetHeader()
	if h == nil {
		return apiError(pb.ErrorReason_INVALID_ARGUMENT, "the first message must be the header")
	}
	data := &dataReader{recv: func() ([]byte, bool, error) {
		m, err := stream.Recv()
		if err != nil {
			return nil, false, err
		}
		_, isData := m.GetPart().(*pb.WriteFileRequest_Data)
		return m.GetData(), isData, nil
	}}
	info, sum, err := s.files.Write(stream.Context(), h.GetSessionId(), files.WriteSpec{
		Path: h.GetPath(), Size: h.GetSize(), SHA256: h.GetSha256(), Mode: h.GetMode(),
		Overwrite: h.GetOverwrite(), MakeParents: h.GetMakeParents(),
	}, data)
	if err != nil {
		return fileError(err)
	}
	return stream.SendAndClose(&pb.WriteFileResponse{Info: toFileInfo(info), Sha256: sum})
}

// UploadFile implements pb.SandboxdServer.
func (s *Server) UploadFile(stream pb.Sandboxd_UploadFileServer) error {
	first, err := stream.Recv()
	if err != nil {
		return err
	}
	h := first.GetHeader()
	if h == nil {
		return apiError(pb.ErrorReason_INVALID_ARGUMENT, "the first message must be the header")
	}
	data := &dataReader{recv: func() ([]byte, bool, error) {
		m, err := stream.Recv()
		if err != nil {
			return nil, false, err
		}
		_, isData := m.GetPart().(*pb.UploadFileRequest_Data)
		return m.GetData(), isData, nil
	}}
	info, sum, err := s.files.Upload(stream.Context(), h.GetSessionId(), files.UploadSpec{
		FileName: h.GetFileName(), Size: h.GetSize(), SHA256: h.GetSha256(), Directory: h.GetDirectory(),
	}, data)
	if err != nil {
		return fileError(err)
	}
	return stream.SendAndClose(&pb.UploadFileResponse{Info: toFileInfo(info), Sha256: sum})
}

// ListFiles implements pb.SandboxdServer.
func (s *Server) ListFiles(ctx context.Context, r *pb.ListFilesRequest) (*pb.ListFilesResponse, error) {
	ents, truncated, err := s.files.List(ctx, r.GetSessionId(), files.ListSpec{
		Path: r.GetPath(), Recursive: r.GetRecursive(), MaxDepth: int(r.GetMaxDepth()), Exclude: r.GetExcludeNames(),
		SkipHidden: r.GetSkipHidden(), MaxEntries: int(r.GetMaxEntries()),
	})
	if err != nil {
		return nil, fileError(err)
	}
	out := &pb.ListFilesResponse{Truncated: truncated, Entries: make([]*pb.FileInfo, 0, len(ents))}
	size := 0
	for _, e := range ents {
		fi := toFileInfo(e)
		// The entry's field tag and length prefix.
		n := proto.Size(fi)
		n += 1 + protowire.SizeVarint(uint64(n))
		if size+n > listMaxBytes {
			out.Truncated = true
			break
		}
		size += n
		out.Entries = append(out.Entries, fi)
	}
	return out, nil
}

// DeleteFile implements pb.SandboxdServer.
func (s *Server) DeleteFile(_ context.Context, r *pb.DeleteFileRequest) (*pb.DeleteFileResponse, error) {
	deleted, err := s.files.Delete(r.GetSessionId(), r.GetPath(), r.GetRecursive())
	if err != nil {
		return nil, fileError(err)
	}
	return &pb.DeleteFileResponse{Deleted: deleted}, nil
}

// ZipFiles implements pb.SandboxdServer.
func (s *Server) ZipFiles(r *pb.ZipFilesRequest, stream pb.Sandboxd_ZipFilesServer) error {
	bw := bufio.NewWriterSize(sendWriter(func(b []byte) error {
		return stream.Send(&pb.ZipFilesResponse{Part: &pb.ZipFilesResponse_Data{Data: b}})
	}), streamChunkBytes)
	sum, err := s.files.Zip(stream.Context(), r.GetSessionId(), files.ZipSpec{
		Path: r.GetPath(), Exclude: r.GetExcludeNames(), SkipHidden: r.GetSkipHidden(),
	}, bw)
	if err == nil {
		err = bw.Flush()
	}
	if err != nil {
		return fileError(err)
	}
	return stream.Send(&pb.ZipFilesResponse{Part: &pb.ZipFilesResponse_Summary{Summary: &pb.ZipSummary{
		Files: uint32(sum.Files), InputBytes: sum.InputBytes, ZipBytes: sum.ZipBytes, Skipped: uint32(sum.Skipped),
	}}})
}

// CaptureSession implements pb.SandboxdServer.
func (s *Server) CaptureSession(r *pb.CaptureSessionRequest, stream pb.Sandboxd_CaptureSessionServer) error {
	bw := bufio.NewWriterSize(sendWriter(func(b []byte) error {
		return stream.Send(&pb.CaptureSessionResponse{Part: &pb.CaptureSessionResponse_Data{Data: b}})
	}), streamChunkBytes)
	var exclude []string
	if len(r.GetExcludeNames()) > 0 {
		exclude = r.GetExcludeNames()
	}
	sum, err := s.files.Capture(stream.Context(), files.CaptureSpec{
		SessionID: r.GetSessionId(), Roots: r.GetRoots(), Exclude: exclude, Limits: toLimits(r.GetLimits()),
	}, bw)
	if err == nil {
		err = bw.Flush()
	}
	if err != nil {
		return fileError(err)
	}
	s.cfg.Log.Info("capture", "session_id", r.GetSessionId(), "stored_bytes", sum.StoredBytes, "files", sum.Files,
		"expanded_bytes", sum.ExpandedBytes, "excluded", sum.Excluded, "skipped", sum.Skipped)
	return stream.Send(&pb.CaptureSessionResponse{Part: &pb.CaptureSessionResponse_Summary{Summary: &pb.CaptureSummary{
		StoredBytes: sum.StoredBytes, Sha256: sum.SHA256, Files: sum.Files, Directories: sum.Directories,
		ExpandedBytes: sum.ExpandedBytes, Excluded: sum.Excluded, Skipped: sum.Skipped, Changed: sum.Changed, Roots: sum.Roots,
	}}})
}

// RestoreSession implements pb.SandboxdServer.
func (s *Server) RestoreSession(stream pb.Sandboxd_RestoreSessionServer) error {
	first, err := stream.Recv()
	if err != nil {
		return err
	}
	h := first.GetHeader()
	if h == nil {
		return apiError(pb.ErrorReason_INVALID_ARGUMENT, "the first message must be the header")
	}
	data := &dataReader{recv: func() ([]byte, bool, error) {
		m, err := stream.Recv()
		if err != nil {
			return nil, false, err
		}
		_, isData := m.GetPart().(*pb.RestoreSessionRequest_Data)
		return m.GetData(), isData, nil
	}}
	start := time.Now()
	sum, err := s.files.Restore(stream.Context(), files.RestoreSpec{
		SessionID: h.GetSessionId(), Size: h.GetSizeBytes(), SHA256: h.GetSha256(), Roots: h.GetRoots(),
		Limits: toLimits(h.GetLimits()),
	}, io.Reader(data))
	if err != nil {
		s.cfg.Log.Warn("restore failed", "session_id", h.GetSessionId(), "err", err)
		return fileError(err)
	}
	s.cfg.Log.Info("restore", "session_id", h.GetSessionId(), "files", sum.Files, "expanded_bytes", sum.ExpandedBytes,
		"roots", sum.Roots, "ms", time.Since(start).Milliseconds(), "recv_wait_ms", data.wait.Milliseconds())
	return stream.SendAndClose(&pb.RestoreSessionResponse{
		Files: sum.Files, Directories: sum.Directories, ExpandedBytes: sum.ExpandedBytes, Roots: sum.Roots,
	})
}
