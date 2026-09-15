package coverage

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/s3"
)

// ErrSnapshotUnavailable means the store has no readable snapshot for a commit.
var ErrSnapshotUnavailable = errors.New("coverage snapshot unavailable")

// SnapshotStore holds one coverage snapshot per commit.
type SnapshotStore interface {
	// Fetch returns the snapshot for a commit. An error wrapping
	// ErrSnapshotUnavailable means none could be read, which a caller walking
	// the history treats as "try the next commit". Any other error is a real
	// problem and must stop the caller.
	Fetch(commit string) (*Snapshot, error)
	// Publish records a snapshot for its own commit.
	Publish(snapshot *Snapshot) error
}

// S3SnapshotStore keeps one snapshot per commit in an S3 bucket.
type S3SnapshotStore struct {
	Bucket string
	// Module is the module directory the snapshots describe, e.g. "tools/ods".
	Module string
	// FetchObject downloads s3url to destPath. An error wrapping
	// s3.ErrObjectUnavailable means the object cannot be read as the caller
	// stands, which a missing snapshot and a fork PR without credentials both
	// look like. Any other error is a real problem.
	FetchObject func(s3url, destPath string) error
	// PutObject uploads srcPath to s3url.
	PutObject func(srcPath, s3url string) error
}

// ObjectURL is where the snapshot of a commit lives.
func (s *S3SnapshotStore) ObjectURL(commit string) string {
	return "s3://" + s.Bucket + "/" + SnapshotObjectKey(s.Module, commit)
}

// Fetch downloads the snapshot of a commit. An object the caller cannot read
// is ErrSnapshotUnavailable. Any other download failure is a hard error, and
// so is a downloaded file that does not parse, or names another commit or
// module: the bucket is then wrong and a comparison against it would be
// misleading.
func (s *S3SnapshotStore) Fetch(commit string) (*Snapshot, error) {
	if s.FetchObject == nil {
		return nil, fmt.Errorf("snapshot store for %s has no fetch function", s.Module)
	}

	dir, err := os.MkdirTemp("", "ods-coverage-snapshot-")
	if err != nil {
		return nil, fmt.Errorf("create snapshot download directory: %w", err)
	}
	defer func() { _ = os.RemoveAll(dir) }()

	url := s.ObjectURL(commit)
	destPath := filepath.Join(dir, "snapshot.yaml")
	if err := s.FetchObject(url, destPath); err != nil {
		if errors.Is(err, s3.ErrObjectUnavailable) {
			return nil, fmt.Errorf("%w: %s: %v", ErrSnapshotUnavailable, url, err)
		}
		return nil, fmt.Errorf("fetch %s: %w", url, err)
	}

	snapshot, err := LoadSnapshotFile(destPath)
	if err != nil {
		return nil, err
	}
	if snapshot.Commit != commit || snapshot.Module != s.Module {
		return nil, fmt.Errorf("%s holds the snapshot of %s for module %s, expected %s for module %s",
			url, snapshot.Commit, snapshot.Module, commit, s.Module)
	}
	return snapshot, nil
}

// Publish uploads a snapshot under the key of its own commit.
func (s *S3SnapshotStore) Publish(snapshot *Snapshot) error {
	if s.PutObject == nil {
		return fmt.Errorf("snapshot store for %s has no put function", s.Module)
	}
	if snapshot.Module != s.Module {
		return fmt.Errorf("snapshot describes module %s, expected %s", snapshot.Module, s.Module)
	}

	dir, err := os.MkdirTemp("", "ods-coverage-snapshot-")
	if err != nil {
		return fmt.Errorf("create snapshot upload directory: %w", err)
	}
	defer func() { _ = os.RemoveAll(dir) }()

	srcPath := filepath.Join(dir, "snapshot.yaml")
	if err := snapshot.SaveFile(srcPath); err != nil {
		return err
	}
	return s.PutObject(srcPath, s.ObjectURL(snapshot.Commit))
}

// NewS3SnapshotStore builds the store the command uses. The fetch is the quiet
// variant because most probes of the ancestor walk miss, and a missing
// snapshot is expected, not a problem to report.
func NewS3SnapshotStore(bucket, module string) *S3SnapshotStore {
	return &S3SnapshotStore{
		Bucket:      bucket,
		Module:      module,
		FetchObject: s3.FetchToFileQuiet,
		PutObject:   s3.PutFile,
	}
}
