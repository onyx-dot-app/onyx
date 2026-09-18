package coverage

import (
	"path/filepath"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// TestLocateBaseSnapshotInShallowClone pins that the walk works in a depth-1
// clone, where HEAD is a shallow boundary: the base must be fetched and its
// ancestors listed before any snapshot can be probed. CI names the base by
// SHA. A developer names it origin/main, which the clone resolves but the
// remote does not serve, so the fetch must name the resolved SHA.
func TestLocateBaseSnapshotInShallowClone(t *testing.T) {
	origin, work := gittest.InitOriginAndWork(t)
	// A local bare origin only serves an arbitrary SHA with this set.
	gittest.Git(t, origin, "config", "uploadpack.allowAnySHA1InWant", "true")
	gittest.Git(t, origin, "config", "commit.gpgsign", "false")

	gittest.Commit(t, work, "a.txt")
	recordedSHA := gittest.Commit(t, work, "b.txt")
	gittest.Commit(t, work, "c.txt")
	tipSHA := gittest.Commit(t, work, "d.txt")
	gittest.PublishMain(t, work)

	for name, rev := range map[string]string{"by sha": tipSHA, "by remote-tracking name": "origin/main"} {
		t.Run(name, func(t *testing.T) {
			clone := filepath.Join(t.TempDir(), "shallow")
			// Depth flags are ignored for plain local-path clones, hence file://.
			gittest.Git(t, t.TempDir(), "clone", "--quiet", "--depth", "1", "file://"+origin, clone)
			gittest.Git(t, clone, "config", "commit.gpgsign", "false")
			t.Chdir(clone)

			store := &fakeSnapshotStore{snapshots: map[string]*Snapshot{
				recordedSHA: {Commit: recordedSHA, Module: "tools/ods"},
			}}

			match, err := LocateBaseSnapshot(rev, GitCommitHistory{}, store, DefaultBaseWalkLimit)
			if err != nil {
				t.Fatalf("LocateBaseSnapshot(%s): %v", rev, err)
			}
			if match.Distance != 2 {
				t.Errorf("Distance = %d, want 2", match.Distance)
			}
			if match.Commit != recordedSHA {
				t.Errorf("Commit = %s, want %s", match.Commit, recordedSHA)
			}
			if match.Base != tipSHA {
				t.Errorf("Base = %s, want %s", match.Base, tipSHA)
			}
		})
	}
}
