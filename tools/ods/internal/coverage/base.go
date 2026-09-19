package coverage

import (
	"errors"
	"fmt"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/git"
)

// DefaultBaseWalkLimit bounds how many first-parent ancestors of the base are
// probed for a snapshot. A commit that landed without publishing leaves a gap,
// and the walk closes it without probing the whole history.
const DefaultBaseWalkLimit = 25

// CommitHistory is the git access LocateBaseSnapshot needs.
type CommitHistory interface {
	// ResolveCommit turns a revision into a full SHA.
	ResolveCommit(rev string) (string, error)
	// IsShallow reports whether the clone has a truncated history.
	IsShallow() (bool, error)
	// FetchWithDepth fetches a revision with a bounded history and returns its
	// full SHA.
	FetchWithDepth(rev string, depth int) (string, error)
	// MergeBaseWithHead returns the merge base of a revision and HEAD. A
	// missing merge base is not an error.
	MergeBaseWithHead(rev string) (sha string, found bool, err error)
	// FirstParentAncestors returns rev and its first-parent ancestors, newest
	// first, at most limit of them.
	FirstParentAncestors(rev string, limit int) ([]string, error)
}

// BaseMatch is the snapshot chosen for a requested base.
type BaseMatch struct {
	// Requested is the revision as the caller gave it.
	Requested string
	// Base is the resolved base commit: the merge base with HEAD, or the
	// revision itself.
	Base string
	// Commit is the commit whose snapshot was found.
	Commit string
	// Distance is the number of first-parent steps from Base to Commit. Zero
	// is an exact match.
	Distance int
	Snapshot *Snapshot
}

// ErrBaseSnapshotUnavailable means no snapshot could be found for the base.
// The caller falls back to the committed floors.
var ErrBaseSnapshotUnavailable = errors.New("no coverage snapshot for the base")

// LocateBaseSnapshot finds the snapshot to report a run against.
//
// It resolves rev, fetching it with a bounded depth when it does not resolve
// or the clone is shallow. The base is the merge base with HEAD when there is
// one, and rev itself otherwise: in CI, HEAD is a shallow boundary and the
// given SHA is already the base. It then walks the base and its first-parent
// ancestors, newest first, and takes the first commit with a snapshot.
func LocateBaseSnapshot(rev string, history CommitHistory, store SnapshotStore, limit int) (*BaseMatch, error) {
	shallow, err := history.IsShallow()
	if err != nil {
		return nil, err
	}

	// A shallow clone holds too little history to walk, so the base is fetched
	// with a bounded depth even when the revision resolves. That fetch names
	// the resolved SHA: a remote-tracking ref such as origin/main resolves
	// here, but the remote does not serve it under that name.
	sha, err := history.ResolveCommit(rev)
	switch {
	case err != nil:
		sha, err = history.FetchWithDepth(rev, limit)
	case shallow:
		sha, err = history.FetchWithDepth(sha, limit)
	}
	if err != nil {
		return nil, fmt.Errorf("%w: cannot fetch %s: %v", ErrBaseSnapshotUnavailable, rev, err)
	}

	base, found, err := history.MergeBaseWithHead(sha)
	if err != nil {
		return nil, err
	}
	if !found {
		base = sha
	}

	ancestors, err := history.FirstParentAncestors(base, limit)
	if err != nil {
		return nil, err
	}

	for distance, commit := range ancestors {
		snapshot, err := store.Fetch(commit)
		if errors.Is(err, ErrSnapshotUnavailable) {
			continue
		}
		if err != nil {
			return nil, err
		}
		return &BaseMatch{
			Requested: rev,
			Base:      base,
			Commit:    commit,
			Distance:  distance,
			Snapshot:  snapshot,
		}, nil
	}

	return nil, fmt.Errorf("%w: %s (base %s), %d commits probed",
		ErrBaseSnapshotUnavailable, rev, ShortCommit(base), len(ancestors))
}

// GitCommitHistory answers LocateBaseSnapshot from the git repository of the
// working directory.
type GitCommitHistory struct{}

// ResolveCommit turns a revision into a full SHA.
func (GitCommitHistory) ResolveCommit(rev string) (string, error) {
	return git.ResolveCommit(rev)
}

// IsShallow reports whether the clone has a truncated history.
func (GitCommitHistory) IsShallow() (bool, error) {
	return git.IsShallowRepository()
}

// FetchWithDepth fetches a revision with a bounded history.
func (GitCommitHistory) FetchWithDepth(rev string, depth int) (string, error) {
	return git.FetchCommitWithDepth(rev, depth)
}

// MergeBaseWithHead returns the merge base of a revision and HEAD.
func (GitCommitHistory) MergeBaseWithHead(rev string) (string, bool, error) {
	return git.MergeBase(rev, "HEAD")
}

// FirstParentAncestors returns rev and its first-parent ancestors, newest
// first.
func (GitCommitHistory) FirstParentAncestors(rev string, limit int) ([]string, error) {
	return git.FirstParentRevList(rev, limit)
}
