package coverage

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/s3"
)

// fakeObjects is an in-memory stand-in for the bucket, keyed by s3 URL.
type fakeObjects struct {
	contents map[string][]byte
	// fetchErr, when set, is what every fetch returns instead.
	fetchErr error
}

func newFakeObjects() *fakeObjects {
	return &fakeObjects{contents: map[string][]byte{}}
}

func (f *fakeObjects) fetch(s3url, destPath string) error {
	if f.fetchErr != nil {
		return f.fetchErr
	}
	data, ok := f.contents[s3url]
	if !ok {
		return fmt.Errorf("%w: no such object", s3.ErrObjectUnavailable)
	}
	return os.WriteFile(destPath, data, 0644)
}

func (f *fakeObjects) put(srcPath, s3url string) error {
	data, err := os.ReadFile(srcPath)
	if err != nil {
		return err
	}
	f.contents[s3url] = data
	return nil
}

func newFakeStore(objects *fakeObjects) *S3SnapshotStore {
	return &S3SnapshotStore{
		Bucket:      "onyx-artifacts",
		Module:      "tools/ods",
		FetchObject: objects.fetch,
		PutObject:   objects.put,
	}
}

func writeObject(t *testing.T, objects *fakeObjects, store *S3SnapshotStore, commit string, snapshot *Snapshot) {
	t.Helper()
	data, err := snapshot.Encode()
	if err != nil {
		t.Fatalf("failed to encode the snapshot: %v", err)
	}
	objects.contents[store.ObjectURL(commit)] = data
}

func TestS3SnapshotStore_fetchReadsTheObject(t *testing.T) {
	objects := newFakeObjects()
	store := newFakeStore(objects)
	want := NewSnapshot(profileOf(map[string][2]int{"cmd": {2, 3}}), testCommit, "tools/ods")
	writeObject(t, objects, store, testCommit, want)

	got, err := store.Fetch(testCommit)
	if err != nil {
		t.Fatalf("failed to fetch the snapshot: %v", err)
	}
	if got.Commit != want.Commit || got.Packages["cmd"] != want.Packages["cmd"] {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

// An object the caller cannot read is "unavailable", and the caller falls
// back to the floors.
func TestS3SnapshotStore_unreadableObjectIsUnavailable(t *testing.T) {
	store := newFakeStore(newFakeObjects())

	_, err := store.Fetch(testCommit)

	if !errors.Is(err, ErrSnapshotUnavailable) {
		t.Fatalf("expected an unavailable snapshot, got %v", err)
	}
	if !strings.Contains(err.Error(), store.ObjectURL(testCommit)) {
		t.Fatalf("expected the object url named, got %v", err)
	}
}

// A download that fails for another reason, such as a network error, must
// stop the caller rather than look like a missing snapshot.
func TestS3SnapshotStore_otherFetchFailureIsAHardError(t *testing.T) {
	objects := newFakeObjects()
	objects.fetchErr = errors.New("dial tcp: no route to host")
	store := newFakeStore(objects)

	_, err := store.Fetch(testCommit)

	if err == nil || errors.Is(err, ErrSnapshotUnavailable) {
		t.Fatalf("expected a hard error, got %v", err)
	}
	if !errors.Is(err, objects.fetchErr) {
		t.Fatalf("expected the download error kept, got %v", err)
	}
}

// A fetched object that names another commit or module means the bucket is
// wrong. That must fail loudly rather than fall back to the floors.
func TestS3SnapshotStore_fetchRejectsAMismatchedSnapshot(t *testing.T) {
	otherCommit := strings.Repeat("b", 40)
	cases := map[string]*Snapshot{
		"commit mismatch": NewSnapshot(profileOf(map[string][2]int{"cmd": {2, 3}}), otherCommit, "tools/ods"),
		"module mismatch": NewSnapshot(profileOf(map[string][2]int{"cmd": {2, 3}}), testCommit, "cli"),
	}
	for name, snapshot := range cases {
		objects := newFakeObjects()
		store := newFakeStore(objects)
		writeObject(t, objects, store, testCommit, snapshot)

		_, err := store.Fetch(testCommit)

		if err == nil {
			t.Errorf("%s: expected an error", name)
			continue
		}
		if errors.Is(err, ErrSnapshotUnavailable) {
			t.Errorf("%s: expected a hard error, got %v", name, err)
		}
	}
}

func TestS3SnapshotStore_publishWritesTheCommitKey(t *testing.T) {
	objects := newFakeObjects()
	store := newFakeStore(objects)
	snapshot := NewSnapshot(profileOf(map[string][2]int{"cmd": {2, 3}}), testCommit, "tools/ods")

	if err := store.Publish(snapshot); err != nil {
		t.Fatalf("failed to publish the snapshot: %v", err)
	}

	data, ok := objects.contents[store.ObjectURL(testCommit)]
	if !ok {
		t.Fatalf("expected an object at %s, got %v", store.ObjectURL(testCommit), objects.contents)
	}
	parsed, err := ParseSnapshot(data)
	if err != nil {
		t.Fatalf("failed to parse the uploaded snapshot: %v", err)
	}
	if parsed.Packages["cmd"] != snapshot.Packages["cmd"] {
		t.Fatalf("got %+v, want %+v", parsed.Packages, snapshot.Packages)
	}
}

func TestS3SnapshotStore_publishRefusesAnotherModule(t *testing.T) {
	store := newFakeStore(newFakeObjects())
	snapshot := NewSnapshot(profileOf(map[string][2]int{"cmd": {2, 3}}), testCommit, "cli")

	if err := store.Publish(snapshot); err == nil {
		t.Fatalf("expected the module mismatch rejected")
	}
}

// A store without its transfer functions cannot work. That is a wiring
// mistake, so it fails rather than looking like a missing snapshot.
func TestS3SnapshotStore_requiresTransferFunctions(t *testing.T) {
	store := &S3SnapshotStore{Bucket: "onyx-artifacts", Module: "tools/ods"}

	if _, err := store.Fetch(testCommit); err == nil || errors.Is(err, ErrSnapshotUnavailable) {
		t.Fatalf("expected a hard error without a fetch function, got %v", err)
	}
	if err := store.Publish(snapshotAt(testCommit)); err == nil {
		t.Fatalf("expected a hard error without a put function")
	}
}
