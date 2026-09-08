package coverage

import (
	"errors"
	"fmt"
	"strings"
	"testing"
)

// fakeCommitHistory answers the git questions LocateBaseSnapshot asks and
// records what it was asked.
type fakeCommitHistory struct {
	shallow bool
	// resolved maps a revision to its sha. A revision that is absent does not
	// resolve.
	resolved map[string]string
	// fetched maps a revision to the sha a depth-limited fetch yields. A
	// revision that is absent cannot be fetched.
	fetched map[string]string
	// mergeBase maps a sha to its merge base with HEAD. A sha that is absent
	// has no merge base.
	mergeBase map[string]string
	// ancestors maps a sha to itself plus its first-parent ancestors.
	ancestors map[string][]string

	fetchCalls []string
}

func (f *fakeCommitHistory) IsShallow() (bool, error) { return f.shallow, nil }

func (f *fakeCommitHistory) ResolveCommit(rev string) (string, error) {
	if sha, ok := f.resolved[rev]; ok {
		return sha, nil
	}
	return "", fmt.Errorf("unknown revision %s", rev)
}

func (f *fakeCommitHistory) FetchWithDepth(rev string, depth int) (string, error) {
	f.fetchCalls = append(f.fetchCalls, fmt.Sprintf("%s@%d", rev, depth))
	if sha, ok := f.fetched[rev]; ok {
		return sha, nil
	}
	return "", fmt.Errorf("cannot fetch %s", rev)
}

func (f *fakeCommitHistory) MergeBaseWithHead(rev string) (string, bool, error) {
	sha, ok := f.mergeBase[rev]
	return sha, ok, nil
}

func (f *fakeCommitHistory) FirstParentAncestors(rev string, limit int) ([]string, error) {
	commits := f.ancestors[rev]
	if len(commits) > limit {
		commits = commits[:limit]
	}
	return commits, nil
}

// fakeSnapshotStore holds the snapshots of a few commits and records probes.
type fakeSnapshotStore struct {
	snapshots map[string]*Snapshot
	// failures maps a commit to the error its probe returns instead.
	failures map[string]error
	probes   []string
}

func (f *fakeSnapshotStore) Fetch(commit string) (*Snapshot, error) {
	f.probes = append(f.probes, commit)
	if err, ok := f.failures[commit]; ok {
		return nil, err
	}
	if snapshot, ok := f.snapshots[commit]; ok {
		return snapshot, nil
	}
	return nil, fmt.Errorf("%w: %s", ErrSnapshotUnavailable, commit)
}

func (f *fakeSnapshotStore) Publish(snapshot *Snapshot) error { return nil }

// commitSha builds a distinct full object name for a test commit.
func commitSha(n int) string {
	return fmt.Sprintf("%d", n) + strings.Repeat("a", 39)
}

func snapshotAt(commit string) *Snapshot {
	return NewSnapshot(profileOf(map[string][2]int{"cmd": {2, 3}}), commit, "tools/ods")
}

func TestLocateBaseSnapshot_exactMatchNeedsNoFetch(t *testing.T) {
	base := commitSha(0)
	history := &fakeCommitHistory{
		resolved:  map[string]string{"origin/main": base},
		mergeBase: map[string]string{base: base},
		ancestors: map[string][]string{base: {base, commitSha(1)}},
	}
	store := &fakeSnapshotStore{snapshots: map[string]*Snapshot{base: snapshotAt(base)}}

	match, err := LocateBaseSnapshot("origin/main", history, store, DefaultBaseWalkLimit)

	if err != nil {
		t.Fatalf("failed to locate the base snapshot: %v", err)
	}
	if match.Distance != 0 || match.Commit != base || match.Base != base || match.Requested != "origin/main" {
		t.Fatalf("unexpected match: %+v", match)
	}
	if len(history.fetchCalls) != 0 {
		t.Fatalf("a full clone must not fetch, got %v", history.fetchCalls)
	}
}

func TestLocateBaseSnapshot_walksToAnOlderAncestor(t *testing.T) {
	base, older := commitSha(0), commitSha(2)
	history := &fakeCommitHistory{
		resolved:  map[string]string{"origin/main": base},
		mergeBase: map[string]string{base: base},
		ancestors: map[string][]string{base: {base, commitSha(1), older, commitSha(3)}},
	}
	store := &fakeSnapshotStore{snapshots: map[string]*Snapshot{older: snapshotAt(older)}}

	match, err := LocateBaseSnapshot("origin/main", history, store, DefaultBaseWalkLimit)

	if err != nil {
		t.Fatalf("failed to locate the base snapshot: %v", err)
	}
	if match.Distance != 2 || match.Commit != older {
		t.Fatalf("expected the third candidate at distance 2, got %+v", match)
	}
}

// The merge base is where the branch left the base, which is what a PR is
// measured against.
func TestLocateBaseSnapshot_prefersTheMergeBase(t *testing.T) {
	tip, forkPoint := commitSha(0), commitSha(5)
	history := &fakeCommitHistory{
		resolved:  map[string]string{"origin/main": tip},
		mergeBase: map[string]string{tip: forkPoint},
		ancestors: map[string][]string{forkPoint: {forkPoint}},
	}
	store := &fakeSnapshotStore{snapshots: map[string]*Snapshot{forkPoint: snapshotAt(forkPoint)}}

	match, err := LocateBaseSnapshot("origin/main", history, store, DefaultBaseWalkLimit)

	if err != nil {
		t.Fatalf("failed to locate the base snapshot: %v", err)
	}
	if match.Base != forkPoint || match.Commit != forkPoint {
		t.Fatalf("expected the merge base used, got %+v", match)
	}
}

// In CI, HEAD is a shallow boundary and no merge base exists. The given SHA is
// already the base.
func TestLocateBaseSnapshot_usesTheRevWhenNoMergeBaseExists(t *testing.T) {
	sha := commitSha(0)
	history := &fakeCommitHistory{
		resolved:  map[string]string{sha: sha},
		ancestors: map[string][]string{sha: {sha}},
	}
	store := &fakeSnapshotStore{snapshots: map[string]*Snapshot{sha: snapshotAt(sha)}}

	match, err := LocateBaseSnapshot(sha, history, store, DefaultBaseWalkLimit)

	if err != nil {
		t.Fatalf("failed to locate the base snapshot: %v", err)
	}
	if match.Base != sha {
		t.Fatalf("expected the rev used as the base, got %+v", match)
	}
}

// A shallow clone holds too little history to walk, even when the revision
// resolves, so the ancestors must be fetched first. The fetch names the
// resolved SHA: the remote does not serve a remote-tracking name.
func TestLocateBaseSnapshot_shallowCloneFetchesTheResolvedSHA(t *testing.T) {
	sha := commitSha(0)
	history := &fakeCommitHistory{
		shallow:   true,
		resolved:  map[string]string{"origin/main": sha},
		fetched:   map[string]string{sha: sha},
		ancestors: map[string][]string{sha: {sha}},
	}
	store := &fakeSnapshotStore{snapshots: map[string]*Snapshot{sha: snapshotAt(sha)}}

	if _, err := LocateBaseSnapshot("origin/main", history, store, DefaultBaseWalkLimit); err != nil {
		t.Fatalf("failed to locate the base snapshot: %v", err)
	}

	want := fmt.Sprintf("%s@%d", sha, DefaultBaseWalkLimit)
	if len(history.fetchCalls) != 1 || history.fetchCalls[0] != want {
		t.Fatalf("expected one fetch of %s, got %v", want, history.fetchCalls)
	}
}

func TestLocateBaseSnapshot_unresolvedRevIsFetched(t *testing.T) {
	sha := commitSha(0)
	history := &fakeCommitHistory{
		fetched:   map[string]string{"origin/main": sha},
		ancestors: map[string][]string{sha: {sha}},
	}
	store := &fakeSnapshotStore{snapshots: map[string]*Snapshot{sha: snapshotAt(sha)}}

	match, err := LocateBaseSnapshot("origin/main", history, store, DefaultBaseWalkLimit)

	if err != nil {
		t.Fatalf("failed to locate the base snapshot: %v", err)
	}
	if match.Commit != sha || len(history.fetchCalls) != 1 {
		t.Fatalf("expected the rev fetched, got %+v after %v", match, history.fetchCalls)
	}
}

func TestLocateBaseSnapshot_fetchFailureIsUnavailable(t *testing.T) {
	history := &fakeCommitHistory{}
	store := &fakeSnapshotStore{}

	_, err := LocateBaseSnapshot("nope", history, store, DefaultBaseWalkLimit)

	if !errors.Is(err, ErrBaseSnapshotUnavailable) {
		t.Fatalf("expected an unavailable base, got %v", err)
	}
}

func TestLocateBaseSnapshot_exhaustedWalkIsUnavailable(t *testing.T) {
	const limit = 3
	base := commitSha(0)
	history := &fakeCommitHistory{
		resolved:  map[string]string{base: base},
		mergeBase: map[string]string{base: base},
		ancestors: map[string][]string{base: {base, commitSha(1), commitSha(2), commitSha(3)}},
	}
	store := &fakeSnapshotStore{}

	_, err := LocateBaseSnapshot(base, history, store, limit)

	if !errors.Is(err, ErrBaseSnapshotUnavailable) {
		t.Fatalf("expected an unavailable base, got %v", err)
	}
	if len(store.probes) != limit {
		t.Fatalf("expected %d probes, got %v", limit, store.probes)
	}
}

// A snapshot that exists but cannot be trusted is a real problem, so the walk
// must stop rather than quietly compare against an older commit.
func TestLocateBaseSnapshot_hardStoreErrorStopsTheWalk(t *testing.T) {
	base := commitSha(0)
	broken := errors.New("snapshot is malformed")
	history := &fakeCommitHistory{
		resolved:  map[string]string{base: base},
		mergeBase: map[string]string{base: base},
		ancestors: map[string][]string{base: {base, commitSha(1)}},
	}
	store := &fakeSnapshotStore{
		failures:  map[string]error{base: broken},
		snapshots: map[string]*Snapshot{commitSha(1): snapshotAt(commitSha(1))},
	}

	_, err := LocateBaseSnapshot(base, history, store, DefaultBaseWalkLimit)

	if !errors.Is(err, broken) {
		t.Fatalf("expected the store error returned unchanged, got %v", err)
	}
	if len(store.probes) != 1 {
		t.Fatalf("expected the walk stopped after one probe, got %v", store.probes)
	}
}
