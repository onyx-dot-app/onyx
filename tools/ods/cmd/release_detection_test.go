package cmd

import (
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestParseReleaseVersions_sortsNewestFirstIgnoringNonMatching(t *testing.T) {
	// Precondition.
	branchNames := []string{
		"release/v4.4",
		"release/v3.0-qa-f1df36e",
		"release/v4.10",
		"main",
		"release/v4.5",
		"release/v10.0",
	}

	// Under test.
	versions := parseReleaseVersions(branchNames)

	// Postcondition.
	got := make([]string, len(versions))
	for i, version := range versions {
		got[i] = version.String()
	}
	want := []string{"v10.0", "v4.10", "v4.5", "v4.4"}
	if !slices.Equal(got, want) {
		t.Errorf("expected %v, got %v", want, got)
	}
}

func TestParseReleaseVersions_emptyWhenNothingMatches(t *testing.T) {
	// Under test and postcondition.
	if versions := parseReleaseVersions([]string{"main", "hotfix/abc-v4.4"}); len(versions) != 0 {
		t.Errorf("expected no versions, got %v", versions)
	}
}

// gitIn runs a git command in dir, failing the test on error.
func gitIn(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %s failed: %v\n%s", strings.Join(args, " "), err, out)
	}
	return strings.TrimSpace(string(out))
}

// commitIn creates a file and commits it in dir, returning the commit SHA.
func commitIn(t *testing.T, dir, filename string) string {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, filename), []byte(filename), 0644); err != nil {
		t.Fatal(err)
	}
	gitIn(t, dir, "add", filename)
	gitIn(t, dir, "commit", "-m", "add "+filename)
	return gitIn(t, dir, "rev-parse", "HEAD")
}

// initOriginAndWork creates a bare origin and a work clone wired to it, and
// returns both paths. The work clone is configured like a single-branch
// checkout of main so tests also pin that detection fetches release branches
// with an explicit refspec (a plain "git fetch origin <branch>" would only
// write FETCH_HEAD here and never create origin/release/vX.Y).
func initOriginAndWork(t *testing.T) (origin, work string) {
	t.Helper()

	origin = t.TempDir()
	gitIn(t, origin, "init", "--bare", "-b", "main")

	work = t.TempDir()
	gitIn(t, work, "init", "-b", "main")
	gitIn(t, work, "config", "user.email", "test@test.com")
	gitIn(t, work, "config", "user.name", "Test")
	gitIn(t, work, "config", "commit.gpgsign", "false")
	gitIn(t, work, "remote", "add", "origin", origin)
	gitIn(t, work, "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main")

	return origin, work
}

// publishMain pushes main to origin and force-updates the origin/main
// remote-tracking ref, which ancestry guards resolve.
func publishMain(t *testing.T, work string) {
	t.Helper()
	gitIn(t, work, "push", "--quiet", "origin", "main")
	gitIn(t, work, "fetch", "--quiet", "--force", "origin", "+refs/heads/main:refs/remotes/origin/main")
}

// publishReleaseBranch pushes a release branch cut at sha to origin, then
// deletes the local branch and its remote-tracking ref so the fixture looks
// like a clone that has never fetched the release branches; detection must
// create origin/* itself via fetch.
func publishReleaseBranch(t *testing.T, work, branch, sha string) {
	t.Helper()
	gitIn(t, work, "branch", branch, sha)
	gitIn(t, work, "push", "--quiet", "origin", branch)
	gitIn(t, work, "branch", "-D", branch)
	gitIn(t, work, "update-ref", "-d", "refs/remotes/origin/"+branch)
}

// releaseBranchRepo describes the fixture built by setupReleaseBranchRepo.
type releaseBranchRepo struct {
	origin string
	work   string
	// preCutSHA is the v4.4 cut point, an ancestor of both release branches.
	preCutSHA string
	// cutSHA is the v4.5 cut point, only on release/v4.5.
	cutSHA string
	// postCutSHA is on neither release branch.
	postCutSHA string
}

// setupReleaseBranchRepo creates a bare origin holding main, release/v4.4, and
// release/v4.5, with a local work repo as the current directory. It returns the
// repo paths and three main-line commit SHAs bracketing the branch cuts.
func setupReleaseBranchRepo(t *testing.T) releaseBranchRepo {
	t.Helper()

	origin, work := initOriginAndWork(t)

	preCutSHA := commitIn(t, work, "a.txt")
	cutSHA := commitIn(t, work, "b.txt")
	postCutSHA := commitIn(t, work, "c.txt")

	publishMain(t, work)
	publishReleaseBranch(t, work, "release/v4.4", preCutSHA)
	publishReleaseBranch(t, work, "release/v4.5", cutSHA)

	// Tags named after the previous release must not influence detection
	// (tag-anchored detection was the original misrouting bug). Mirror the
	// incident topology: a stable v4.4 tag at the v4.4 cut point, plus a v4.4
	// pre-release tag minted on main after the v4.5 cut, which is the exact
	// shape that misrouted real cherry-picks to release/v4.4.
	gitIn(t, work, "tag", "v4.4.2", preCutSHA)
	gitIn(t, work, "tag", "v4.4.0-cloud.9", postCutSHA)

	// The functions under test run git in the process working directory.
	t.Chdir(work)

	return releaseBranchRepo{
		origin:     origin,
		work:       work,
		preCutSHA:  preCutSHA,
		cutSHA:     cutSHA,
		postCutSHA: postCutSHA,
	}
}

// setupShallowClone seeds an origin holding main and release/v4.5 at a single
// commit, makes a depth-1 clone the current directory, and returns the commit
// SHA. Ancestry cannot be answered truthfully in the clone.
func setupShallowClone(t *testing.T) string {
	t.Helper()

	origin, seed := initOriginAndWork(t)
	sha := commitIn(t, seed, "a.txt")
	gitIn(t, seed, "branch", "release/v4.5")
	gitIn(t, seed, "push", "--quiet", "origin", "main", "release/v4.5")

	shallow := filepath.Join(t.TempDir(), "shallow")
	// Depth flags are ignored for plain local-path clones, hence file://.
	gitIn(t, t.TempDir(), "clone", "--quiet", "--depth", "1", "--no-single-branch", "file://"+origin, shallow)
	t.Chdir(shallow)

	return sha
}

func TestFindTargetReleaseVersion_postCutCommitTargetsNewestBranch(t *testing.T) {
	// Precondition.
	repo := setupReleaseBranchRepo(t)

	// Under test.
	version, err := findTargetReleaseVersion(repo.postCutSHA)

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if version.String() != "v4.5" {
		t.Errorf("expected v4.5, got %s", version)
	}
}

func TestFindTargetReleaseVersion_preCutCommitFallsBackToOlderBranch(t *testing.T) {
	// Precondition.
	repo := setupReleaseBranchRepo(t)

	// Under test.
	version, err := findTargetReleaseVersion(repo.cutSHA)

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if version.String() != "v4.4" {
		t.Errorf("expected v4.4, got %s", version)
	}
}

func TestFindTargetReleaseVersion_commitOnAllBranchesErrors(t *testing.T) {
	// Precondition.
	repo := setupReleaseBranchRepo(t)

	// Under test.
	_, err := findTargetReleaseVersion(repo.preCutSHA)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "already contained in every release branch") {
		t.Errorf("expected already-contained error, got %v", err)
	}
}

func TestFindTargetReleaseVersion_shallowCloneErrors(t *testing.T) {
	// Precondition.
	sha := setupShallowClone(t)

	// Under test.
	_, err := findTargetReleaseVersion(sha)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "shallow clone") {
		t.Errorf("expected shallow-clone error, got %v", err)
	}
}
