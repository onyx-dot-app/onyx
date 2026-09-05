package release

// Beta tag state matrix (ComputeBetaTag). Beta tags are cut on a release
// branch: the target is the newest release/vX.Y branch on origin (or the
// override's branch), the base is one patch past the highest stable vX.Y.*
// tag, and the counter continues per base. The fixture
// (gittest.SetupReleaseBranchRepo) cuts release/v4.4 at PreCutSHA (which
// carries the v4.4.2 tag) and release/v4.5 at CutSHA, so the newest branch is
// release/v4.5 with tip CutSHA.
//
//	B1 fresh branch, no vX.Y.* tags        -> vX.Y.0-beta.0 at the branch tip   TestComputeBetaTag_freshBranchFirstBeta
//	B2 existing betas for the base         -> counter continues                 TestComputeBetaTag_counterContinues
//	B3 stable patch already shipped        -> base bumps to the next patch      TestComputeBetaTag_baseBumpsPastStablePatch
//	B4 stable tag only on origin           -> fetched, base still bumps         TestComputeBetaTag_fetchesRemoteOnlyStableTags
//	B5 --version override                  -> override base, counter fresh      TestComputeBetaTag_versionOverride
//	B6 override base already released      -> error                             TestComputeBetaTag_releasedBaseErrors
//	B7 ref not on the release branch       -> error                             TestComputeBetaTag_refNotOnBranchErrors
//	B8 no release branches on origin       -> error, hint --version             TestComputeBetaTag_noReleaseBranchesErrors
//	B9 shallow clone (even with --version) -> error                             TestComputeBetaTag_shallowCloneErrors
//	B10 predecessor beta not an ancestor   -> error                             TestComputeBetaTag_predecessorNotAncestorErrors
//	B11 origin unreachable                 -> error, no stale-state fallback    TestComputeBetaTag_fetchFailureErrors
//
// New branch cuts (ComputeNewBetaBranch) take the next minor after the newest
// branch and cut it from origin/main, whose tip is PostCutSHA.
//
//	N1 newest branch release/v4.5          -> release/v4.6 at the main tip,
//	                                          v4.6.0-beta.0                     TestComputeNewBetaBranch_cutsNextMinorFromMain
//	N2 ref not on main                     -> error                             TestComputeNewBetaBranch_refNotOnMainErrors
//	N3 another minor branch cut meanwhile  -> the cut follows the newest one     TestComputeNewBetaBranch_followsTheNewestBranch
//	N4 next minor base already released    -> error                             TestComputeNewBetaBranch_releasedBaseErrors
//	N5 shallow clone                       -> error                             TestComputeNewBetaBranch_shallowCloneErrors

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestComputeBetaTag_freshBranchFirstBeta(t *testing.T) {
	// Precondition: no v4.5.* tags exist; the fixture's v4.4.* tags pin that
	// other minors do not bleed into the base or counter.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test: empty ref defaults to the branch tip.
	tag, sha, err := ComputeBetaTag("", "")

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.5.0-beta.0" {
		t.Errorf("expected v4.5.0-beta.0, got %s", tag)
	}
	if sha != repo.CutSHA {
		t.Errorf("expected the release/v4.5 tip %s, got %s", repo.CutSHA, sha)
	}
}

func TestComputeBetaTag_counterContinues(t *testing.T) {
	// Precondition: beta.0 already exists at the branch tip.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-beta.0", repo.CutSHA)

	// Under test.
	tag, _, err := ComputeBetaTag("", "")

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.5.0-beta.1" {
		t.Errorf("expected v4.5.0-beta.1, got %s", tag)
	}
}

func TestComputeBetaTag_baseBumpsPastStablePatch(t *testing.T) {
	// Precondition: v4.5.0 has shipped, so the next beta previews v4.5.1.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0", repo.CutSHA)

	// Under test.
	tag, _, err := ComputeBetaTag("", "")

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.5.1-beta.0" {
		t.Errorf("expected v4.5.1-beta.0, got %s", tag)
	}
}

func TestComputeBetaTag_fetchesRemoteOnlyStableTags(t *testing.T) {
	// Precondition: a stable tag another developer pushed but this clone never
	// fetched. Computing from local tags alone would mint a beta of the
	// already-released v4.5.0, which origin would accept (the tag itself is
	// new) and only CI's check would reject.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0", repo.CutSHA)
	gittest.Git(t, repo.Work, "push", "--quiet", "origin", "v4.5.0")
	gittest.Git(t, repo.Work, "tag", "-d", "v4.5.0")

	// Under test.
	tag, _, err := ComputeBetaTag("", "")

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.5.1-beta.0" {
		t.Errorf("expected v4.5.1-beta.0, got %s", tag)
	}
}

func TestComputeBetaTag_versionOverride(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test: the override skips patch detection but still anchors to the
	// override's release branch.
	tag, sha, err := ComputeBetaTag("", "4.5.9")

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.5.9-beta.0" {
		t.Errorf("expected v4.5.9-beta.0, got %s", tag)
	}
	if sha != repo.CutSHA {
		t.Errorf("expected the release/v4.5 tip %s, got %s", repo.CutSHA, sha)
	}
}

func TestComputeBetaTag_releasedBaseErrors(t *testing.T) {
	// Precondition: the fixture's v4.4.2 stable tag has already shipped.
	gittest.SetupReleaseBranchRepo(t)

	// Under test.
	_, _, err := ComputeBetaTag("", "4.4.2")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "already been released") {
		t.Errorf("expected an already-released error, got %v", err)
	}
}

func TestComputeBetaTag_refNotOnBranchErrors(t *testing.T) {
	// Precondition: the post-cut commit is on main only, not release/v4.5.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	_, _, err := ComputeBetaTag(repo.PostCutSHA, "")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not on origin/release/v4.5") {
		t.Errorf("expected a not-on-branch error, got %v", err)
	}
}

func TestComputeBetaTag_noReleaseBranchesErrors(t *testing.T) {
	// Precondition: an origin with main only.
	_, work := gittest.InitOriginAndWork(t)
	gittest.Commit(t, work, "a.txt")
	gittest.PublishMain(t, work)
	t.Chdir(work)

	// Under test.
	_, _, err := ComputeBetaTag("", "")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "no release/vX.Y branches") {
		t.Errorf("expected no-release-branches error, got %v", err)
	}
	if err == nil || !strings.Contains(err.Error(), "--version") {
		t.Errorf("expected a --version hint, got %v", err)
	}
}

func TestComputeBetaTag_shallowCloneErrors(t *testing.T) {
	// Precondition.
	gittest.SetupShallowClone(t)

	// Under test: the override skips branch detection, so this pins
	// ComputeBetaTag's own shallow guard.
	_, _, err := ComputeBetaTag("", "4.5.0")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "shallow clone") {
		t.Errorf("expected shallow-clone error, got %v", err)
	}
}

func TestComputeBetaTag_predecessorNotAncestorErrors(t *testing.T) {
	// Precondition: beta.0 sits at the branch tip, but --ref points at an
	// older on-branch commit; beta.1 there would fail CI's ancestry check.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-beta.0", repo.CutSHA)

	// Under test.
	_, _, err := ComputeBetaTag(repo.PreCutSHA, "")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not an ancestor") {
		t.Errorf("expected a predecessor-not-ancestor error, got %v", err)
	}
}

func TestComputeBetaTag_fetchFailureErrors(t *testing.T) {
	// Precondition: an unreachable origin. Unlike a cloud cut (where origin
	// rejects a colliding counter push), a beta cut must not fall back to
	// local state: a stale view could mint a beta of a released base.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "remote", "set-url", "origin", t.TempDir())

	// Under test: the override skips branch detection, pinning the fetches.
	_, _, err := ComputeBetaTag("", "4.5.0")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "failed to fetch") {
		t.Errorf("expected a fetch failure error, got %v", err)
	}
}

func TestComputeNewBetaBranch_cutsNextMinorFromMain(t *testing.T) {
	// Precondition: the newest branch is release/v4.5 and main's tip is
	// PostCutSHA, which no release branch contains.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test: an empty ref defaults to the main tip.
	branch, tag, sha, err := ComputeNewBetaBranch("")

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if branch != "release/v4.6" {
		t.Errorf("expected release/v4.6, got %s", branch)
	}
	if tag != "v4.6.0-beta.0" {
		t.Errorf("expected v4.6.0-beta.0, got %s", tag)
	}
	if sha != repo.PostCutSHA {
		t.Errorf("expected the main tip %s, got %s", repo.PostCutSHA, sha)
	}
}

func TestComputeNewBetaBranch_refNotOnMainErrors(t *testing.T) {
	// Precondition: a commit that was never pushed to main.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "checkout", "--quiet", "-b", "side", repo.PreCutSHA)
	sideSHA := gittest.Commit(t, repo.Work, "side.txt")
	gittest.Git(t, repo.Work, "checkout", "--quiet", "main")

	// Under test.
	_, _, _, err := ComputeNewBetaBranch(sideSHA)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not on origin/main") {
		t.Errorf("expected a not-on-main error, got %v", err)
	}
}

func TestComputeNewBetaBranch_followsTheNewestBranch(t *testing.T) {
	// Precondition: release/v4.6 was cut already, so the next minor after the
	// newest branch is release/v4.7 and this cut is a no-op.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.PublishReleaseBranch(t, repo.Work, "release/v4.6", repo.PostCutSHA)

	// Under test.
	branch, _, _, err := ComputeNewBetaBranch("")

	// Postcondition: the newest branch moved on, so v4.7 is cut instead.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if branch != "release/v4.7" {
		t.Errorf("expected release/v4.7, got %s", branch)
	}
}

func TestComputeNewBetaBranch_releasedBaseErrors(t *testing.T) {
	// Precondition: v4.6.0 shipped without its release branch. A beta of it
	// would move the "beta" Docker tags backwards.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.6.0", repo.PostCutSHA)
	gittest.Git(t, repo.Work, "push", "--quiet", "origin", "v4.6.0")
	gittest.Git(t, repo.Work, "tag", "-d", "v4.6.0")

	// Under test.
	_, _, _, err := ComputeNewBetaBranch("")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "already been released") {
		t.Errorf("expected an already-released error, got %v", err)
	}
}

func TestComputeNewBetaBranch_shallowCloneErrors(t *testing.T) {
	// Precondition.
	gittest.SetupShallowClone(t)

	// Under test.
	_, _, _, err := ComputeNewBetaBranch("")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "shallow clone") {
		t.Errorf("expected shallow-clone error, got %v", err)
	}
}
