// Package gittest provides git repository fixtures for tests that exercise
// release tagging and branch detection against a real origin.
package gittest

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// Git runs a git command in dir, failing the test on error.
func Git(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %s failed: %v\n%s", strings.Join(args, " "), err, out)
	}
	return strings.TrimSpace(string(out))
}

// Commit creates a file and commits it in dir, returning the commit SHA.
func Commit(t *testing.T, dir, filename string) string {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, filename), []byte(filename), 0644); err != nil {
		t.Fatal(err)
	}
	Git(t, dir, "add", filename)
	Git(t, dir, "commit", "-m", "add "+filename)
	return Git(t, dir, "rev-parse", "HEAD")
}

// TagExists reports whether the tag exists in the repository at dir.
func TagExists(dir, tag string) bool {
	cmd := exec.Command("git", "rev-parse", "-q", "--verify", "refs/tags/"+tag)
	cmd.Dir = dir
	return cmd.Run() == nil
}

// InitOriginAndWork creates a bare origin and a work clone wired to it, and
// returns both paths. The work clone is configured like a single-branch
// checkout of main so tests also pin that detection fetches release branches
// with an explicit refspec (a plain "git fetch origin <branch>" would only
// write FETCH_HEAD here and never create origin/release/vX.Y).
func InitOriginAndWork(t *testing.T) (origin, work string) {
	t.Helper()

	origin = t.TempDir()
	Git(t, origin, "init", "--bare", "-b", "main")

	work = t.TempDir()
	Git(t, work, "init", "-b", "main")
	Git(t, work, "config", "user.email", "test@test.com")
	Git(t, work, "config", "user.name", "Test")
	Git(t, work, "config", "commit.gpgsign", "false")
	Git(t, work, "remote", "add", "origin", origin)
	Git(t, work, "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main")

	return origin, work
}

// PublishMain pushes main to origin and force-updates the origin/main
// remote-tracking ref, which ancestry guards resolve.
func PublishMain(t *testing.T, work string) {
	t.Helper()
	Git(t, work, "push", "--quiet", "origin", "main")
	Git(t, work, "fetch", "--quiet", "--force", "origin", "+refs/heads/main:refs/remotes/origin/main")
}

// PublishReleaseBranch pushes a release branch cut at sha to origin, then
// deletes the local branch and its remote-tracking ref so the fixture looks
// like a clone that has never fetched the release branches; detection must
// create origin/* itself via fetch.
func PublishReleaseBranch(t *testing.T, work, branch, sha string) {
	t.Helper()
	Git(t, work, "branch", branch, sha)
	Git(t, work, "push", "--quiet", "origin", branch)
	Git(t, work, "branch", "-D", branch)
	Git(t, work, "update-ref", "-d", "refs/remotes/origin/"+branch)
}

// ReleaseBranchRepo describes the fixture built by SetupReleaseBranchRepo.
type ReleaseBranchRepo struct {
	Origin string
	Work   string
	// PreCutSHA is the v4.4 cut point, an ancestor of both release branches.
	PreCutSHA string
	// CutSHA is the v4.5 cut point, only on release/v4.5.
	CutSHA string
	// PostCutSHA is on neither release branch.
	PostCutSHA string
}

// SetupReleaseBranchRepo creates a bare origin holding main, release/v4.4, and
// release/v4.5, with a local work repo as the current directory. It returns the
// repo paths and three main-line commit SHAs bracketing the branch cuts.
func SetupReleaseBranchRepo(t *testing.T) ReleaseBranchRepo {
	t.Helper()

	origin, work := InitOriginAndWork(t)

	preCutSHA := Commit(t, work, "a.txt")
	cutSHA := Commit(t, work, "b.txt")
	postCutSHA := Commit(t, work, "c.txt")

	PublishMain(t, work)
	PublishReleaseBranch(t, work, "release/v4.4", preCutSHA)
	PublishReleaseBranch(t, work, "release/v4.5", cutSHA)

	// Tags named after the previous release must not influence detection
	// (tag-anchored detection was the original misrouting bug). Mirror the
	// incident topology: a stable v4.4 tag at the v4.4 cut point, plus a v4.4
	// pre-release tag minted on main after the v4.5 cut, which is the exact
	// shape that misrouted real cherry-picks to release/v4.4.
	Git(t, work, "tag", "v4.4.2", preCutSHA)
	Git(t, work, "tag", "v4.4.0-cloud.9", postCutSHA)

	// The functions under test run git in the process working directory.
	t.Chdir(work)

	return ReleaseBranchRepo{
		Origin:     origin,
		Work:       work,
		PreCutSHA:  preCutSHA,
		CutSHA:     cutSHA,
		PostCutSHA: postCutSHA,
	}
}

// SetupTwoBranchRepo creates an origin whose main holds four commits with
// branchA cut at the first and branchB at the third, chdirs into the work
// clone, and returns the SHA between the cuts and the SHA past both.
func SetupTwoBranchRepo(t *testing.T, branchA, branchB string) (betweenSHA, postSHA string) {
	t.Helper()

	_, work := InitOriginAndWork(t)
	cutA := Commit(t, work, "a.txt")
	betweenSHA = Commit(t, work, "b.txt")
	cutB := Commit(t, work, "c.txt")
	postSHA = Commit(t, work, "d.txt")

	PublishMain(t, work)
	PublishReleaseBranch(t, work, branchA, cutA)
	PublishReleaseBranch(t, work, branchB, cutB)

	t.Chdir(work)
	return betweenSHA, postSHA
}

// SetupShallowClone seeds an origin holding main and release/v4.5 at a single
// commit, makes a depth-1 clone the current directory, and returns the commit
// SHA. Ancestry cannot be answered truthfully in the clone.
func SetupShallowClone(t *testing.T) string {
	t.Helper()

	origin, seed := InitOriginAndWork(t)
	sha := Commit(t, seed, "a.txt")
	Git(t, seed, "branch", "release/v4.5")
	Git(t, seed, "push", "--quiet", "origin", "main", "release/v4.5")

	shallow := filepath.Join(t.TempDir(), "shallow")
	// Depth flags are ignored for plain local-path clones, hence file://.
	Git(t, t.TempDir(), "clone", "--quiet", "--depth", "1", "--no-single-branch", "file://"+origin, shallow)
	t.Chdir(shallow)

	return sha
}
