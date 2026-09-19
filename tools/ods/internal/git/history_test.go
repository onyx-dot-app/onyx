package git

import (
	"os"
	"path/filepath"
	"regexp"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

var fullSHAPattern = regexp.MustCompile(`^[0-9a-f]{40}$`)

func TestResolveCommit(t *testing.T) {
	repo := newTestRepo(t)

	sha, err := ResolveCommit("HEAD")
	if err != nil {
		t.Fatalf("ResolveCommit(HEAD) failed: %v", err)
	}
	if !fullSHAPattern.MatchString(sha) {
		t.Fatalf("ResolveCommit(HEAD) = %q, want a 40-hex SHA", sha)
	}
	if sha != repo.HEAD() {
		t.Fatalf("ResolveCommit(HEAD) = %q, want %q", sha, repo.HEAD())
	}

	if _, err := ResolveCommit("no-such-ref"); err == nil {
		t.Fatal("ResolveCommit(no-such-ref) succeeded, want an error")
	}
}

func TestMergeBase_findsTheCommonAncestor(t *testing.T) {
	repo := newTestRepo(t)
	ancestor := repo.HEAD()

	mainSHA := repo.Commit("on main", "main.txt", "main")
	repo.Git("checkout", "-b", "side", ancestor)
	sideSHA := repo.Commit("on side", "side.txt", "side")

	sha, found, err := MergeBase(mainSHA, sideSHA)
	if err != nil {
		t.Fatalf("MergeBase failed: %v", err)
	}
	if !found {
		t.Fatal("MergeBase found = false, want true")
	}
	if sha != ancestor {
		t.Fatalf("MergeBase = %q, want %q", sha, ancestor)
	}
}

func TestMergeBase_reportsUnrelatedHistoriesAsNotFound(t *testing.T) {
	repo := newTestRepo(t)
	mainSHA := repo.HEAD()

	repo.Git("checkout", "--orphan", "unrelated")
	repo.Git("rm", "-rf", ".")
	orphanSHA := repo.Commit("unrelated root", "other.txt", "other")

	sha, found, err := MergeBase(mainSHA, orphanSHA)
	if err != nil {
		t.Fatalf("MergeBase failed: %v", err)
	}
	if found {
		t.Fatalf("MergeBase found = true (%q), want false for unrelated histories", sha)
	}
}

func TestMergeBase_errorsOnAnUnknownRevision(t *testing.T) {
	repo := newTestRepo(t)

	if _, _, err := MergeBase(repo.HEAD(), "no-such-ref"); err == nil {
		t.Fatal("MergeBase with an unknown revision succeeded, want an error")
	}
}

func TestFirstParentRevList_followsFirstParentsNewestFirst(t *testing.T) {
	repo := newTestRepo(t)
	first := repo.HEAD()

	second := repo.Commit("second", "second.txt", "second")
	repo.Git("checkout", "-b", "side", first)
	sideSHA := repo.Commit("side", "side.txt", "side")
	repo.Git("checkout", "main")
	repo.Git("merge", "--no-ff", "-m", "merge side", "side")
	mergeSHA := repo.HEAD()

	shas, err := FirstParentRevList("HEAD", 10)
	if err != nil {
		t.Fatalf("FirstParentRevList failed: %v", err)
	}
	want := []string{mergeSHA, second, first}
	if len(shas) != len(want) {
		t.Fatalf("FirstParentRevList = %v, want %v", shas, want)
	}
	for i, sha := range want {
		if shas[i] != sha {
			t.Fatalf("FirstParentRevList[%d] = %q, want %q (got %v)", i, shas[i], sha, shas)
		}
	}
	for _, sha := range shas {
		if sha == sideSHA {
			t.Fatalf("FirstParentRevList included the second parent's commit %q", sideSHA)
		}
	}

	limited, err := FirstParentRevList("HEAD", 2)
	if err != nil {
		t.Fatalf("FirstParentRevList with a limit failed: %v", err)
	}
	if len(limited) != 2 || limited[0] != mergeSHA || limited[1] != second {
		t.Fatalf("FirstParentRevList(HEAD, 2) = %v, want %v", limited, want[:2])
	}

	if _, err := FirstParentRevList("HEAD", 0); err == nil {
		t.Fatal("FirstParentRevList with limit 0 succeeded, want an error")
	}
}

// TestFetchCommitWithDepth_inAShallowClone pins the CI shape: a depth-1 clone
// can reach an older commit only by fetching it with an explicit depth, and
// merge-base still fails there because HEAD is a shallow boundary.
func TestFetchCommitWithDepth_inAShallowClone(t *testing.T) {
	origin, work := gittest.InitOriginAndWork(t)
	// Fetching a commit that is not a branch tip needs the server's consent.
	// GitHub allows it; a bare local origin does not by default.
	gittest.Git(t, origin, "config", "uploadpack.allowAnySHA1InWant", "true")

	shas := []string{}
	for _, name := range []string{"a.txt", "b.txt", "c.txt", "d.txt", "e.txt"} {
		shas = append(shas, gittest.Commit(t, work, name))
	}
	gittest.PublishMain(t, work)

	shallow := filepath.Join(t.TempDir(), "shallow")
	// Depth flags are ignored for plain local-path clones, hence file://.
	gittest.Git(t, t.TempDir(), "clone", "--quiet", "--depth", "1", "file://"+origin, shallow)
	t.Chdir(shallow)

	olderSHA := shas[3]
	if _, err := ResolveCommit(olderSHA); err == nil {
		t.Fatalf("ResolveCommit(%s) succeeded before the fetch, want an error", olderSHA)
	}

	fetched, err := FetchCommitWithDepth(olderSHA, 3)
	if err != nil {
		t.Fatalf("FetchCommitWithDepth failed: %v", err)
	}
	if fetched != olderSHA {
		t.Fatalf("FetchCommitWithDepth = %q, want %q", fetched, olderSHA)
	}

	ancestors, err := FirstParentRevList(olderSHA, 3)
	if err != nil {
		t.Fatalf("FirstParentRevList failed: %v", err)
	}
	want := []string{shas[3], shas[2], shas[1]}
	if len(ancestors) != len(want) {
		t.Fatalf("FirstParentRevList = %v, want %v", ancestors, want)
	}
	for i, sha := range want {
		if ancestors[i] != sha {
			t.Fatalf("FirstParentRevList[%d] = %q, want %q", i, ancestors[i], sha)
		}
	}

	sha, found, err := MergeBase(olderSHA, "HEAD")
	if err != nil {
		t.Fatalf("MergeBase failed: %v", err)
	}
	if found {
		t.Fatalf("MergeBase found = true (%q); a shallow HEAD has no known ancestor", sha)
	}

	if _, err := FetchCommitWithDepth(olderSHA, 0); err == nil {
		t.Fatal("FetchCommitWithDepth with depth 0 succeeded, want an error")
	}

	// A remote-tracking name is fetched as the branch behind it.
	tip, err := FetchCommitWithDepth("origin/main", 1)
	if err != nil {
		t.Fatalf("FetchCommitWithDepth(origin/main) failed: %v", err)
	}
	if tip != shas[4] {
		t.Fatalf("FetchCommitWithDepth(origin/main) = %q, want %q", tip, shas[4])
	}
}

func TestWorkingTreeChanges_seesUntrackedFiles(t *testing.T) {
	_, work := gittest.InitOriginAndWork(t)
	gittest.Commit(t, work, "a.txt")
	t.Chdir(work)

	changes, err := WorkingTreeChanges()
	if err != nil {
		t.Fatalf("WorkingTreeChanges failed: %v", err)
	}
	if len(changes) != 0 {
		t.Fatalf("WorkingTreeChanges = %v right after a commit, want none", changes)
	}

	if err := os.WriteFile(filepath.Join(work, "untracked.txt"), []byte("x\n"), 0644); err != nil {
		t.Fatal(err)
	}
	changes, err = WorkingTreeChanges()
	if err != nil {
		t.Fatalf("WorkingTreeChanges failed: %v", err)
	}
	if len(changes) != 1 || changes[0] != "?? untracked.txt" {
		t.Fatalf("WorkingTreeChanges = %v, want [?? untracked.txt]", changes)
	}
	// The stash helper must keep ignoring untracked files.
	if HasUncommittedChanges() {
		t.Fatal("HasUncommittedChanges = true for an untracked file, want false")
	}
}
