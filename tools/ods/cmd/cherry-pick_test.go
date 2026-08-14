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

// setupReleaseBranchRepo creates a bare origin holding main, release/v4.4, and
// release/v4.5, with a local work repo as the current directory. It returns
// three main-line commit SHAs: the v4.4 cut point (ancestor of both release
// branches), the v4.5 cut point (only on release/v4.5), and a post-cut commit
// (on neither release branch).
func setupReleaseBranchRepo(t *testing.T) (preCutSHA, cutSHA, postCutSHA string) {
	t.Helper()

	origin := t.TempDir()
	gitIn(t, origin, "init", "--bare", "-b", "main")

	work := t.TempDir()
	gitIn(t, work, "init", "-b", "main")
	gitIn(t, work, "config", "user.email", "test@test.com")
	gitIn(t, work, "config", "user.name", "Test")
	gitIn(t, work, "config", "commit.gpgsign", "false")
	gitIn(t, work, "remote", "add", "origin", origin)
	// Narrow the fetch refspec to main only, like a single-branch clone, so the
	// tests also pin that detection fetches release branches with an explicit
	// refspec (a plain "git fetch origin <branch>" would only write FETCH_HEAD
	// here and never create origin/release/vX.Y).
	gitIn(t, work, "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main")

	preCutSHA = commitIn(t, work, "a.txt")
	gitIn(t, work, "branch", "release/v4.4", preCutSHA)
	cutSHA = commitIn(t, work, "b.txt")
	gitIn(t, work, "branch", "release/v4.5", cutSHA)
	postCutSHA = commitIn(t, work, "c.txt")

	gitIn(t, work, "push", "--quiet", "origin", "main", "release/v4.4", "release/v4.5")

	// Tags named after the previous release must not influence detection
	// (tag-anchored detection was the original misrouting bug). Mirror the
	// incident topology: a stable v4.4 tag at the v4.4 cut point, plus a v4.4
	// pre-release tag minted on main after the v4.5 cut, which is the exact
	// shape that misrouted real cherry-picks to release/v4.4.
	gitIn(t, work, "tag", "v4.4.2", preCutSHA)
	gitIn(t, work, "tag", "v4.4.0-cloud.9", postCutSHA)

	// Drop the local release branches and the remote-tracking refs the push
	// created, so the fixture looks like a clone that has never fetched the
	// release branches; detection must create origin/* itself via fetch.
	gitIn(t, work, "branch", "-D", "release/v4.4", "release/v4.5")
	gitIn(t, work, "update-ref", "-d", "refs/remotes/origin/release/v4.4")
	gitIn(t, work, "update-ref", "-d", "refs/remotes/origin/release/v4.5")

	// The functions under test run git in the process working directory.
	t.Chdir(work)

	return preCutSHA, cutSHA, postCutSHA
}

func TestFindTargetReleaseVersion_postCutCommitTargetsNewestBranch(t *testing.T) {
	// Precondition.
	_, _, postCutSHA := setupReleaseBranchRepo(t)

	// Under test.
	version, err := findTargetReleaseVersion(postCutSHA)

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if version != "v4.5" {
		t.Errorf("expected v4.5, got %s", version)
	}
}

func TestFindTargetReleaseVersion_preCutCommitFallsBackToOlderBranch(t *testing.T) {
	// Precondition.
	_, cutSHA, _ := setupReleaseBranchRepo(t)

	// Under test.
	version, err := findTargetReleaseVersion(cutSHA)

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if version != "v4.4" {
		t.Errorf("expected v4.4, got %s", version)
	}
}

func TestFindTargetReleaseVersion_commitOnAllBranchesErrors(t *testing.T) {
	// Precondition.
	preCutSHA, _, _ := setupReleaseBranchRepo(t)

	// Under test.
	_, err := findTargetReleaseVersion(preCutSHA)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "already contained in every release branch") {
		t.Errorf("expected already-contained error, got %v", err)
	}
}

func TestFindTargetReleaseVersion_shallowCloneErrors(t *testing.T) {
	// Precondition: a shallow clone, where ancestry cannot be answered.
	origin := t.TempDir()
	gitIn(t, origin, "init", "--bare", "-b", "main")
	seed := t.TempDir()
	gitIn(t, seed, "init", "-b", "main")
	gitIn(t, seed, "config", "user.email", "test@test.com")
	gitIn(t, seed, "config", "user.name", "Test")
	gitIn(t, seed, "config", "commit.gpgsign", "false")
	gitIn(t, seed, "remote", "add", "origin", origin)
	sha := commitIn(t, seed, "a.txt")
	gitIn(t, seed, "branch", "release/v4.5")
	gitIn(t, seed, "push", "--quiet", "origin", "main", "release/v4.5")
	shallow := filepath.Join(t.TempDir(), "shallow")
	// Depth flags are ignored for plain local-path clones, hence file://.
	gitIn(t, t.TempDir(), "clone", "--quiet", "--depth", "1", "--no-single-branch", "file://"+origin, shallow)
	t.Chdir(shallow)

	// Under test.
	_, err := findTargetReleaseVersion(sha)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "shallow clone") {
		t.Errorf("expected shallow-clone error, got %v", err)
	}
}
