package release

// Release tag check state matrix (CheckTag; `ods release --check`). The
// fixture (gittest.SetupReleaseBranchRepo) cuts release/v4.4 at PreCutSHA
// (which carries the v4.4.2 tag) and release/v4.5 at CutSHA.
//
// Cloud tag states:
//
//	K1 tag just cut by `ods release cloud`   -> valid                          TestCheckTag_freshCloudTagPasses
//	K2 base disagrees with release branches  -> error naming both bases        TestCheckTag_wrongCloudBaseErrors
//	K3 counter skipped (cloud.1 without .0)  -> out-of-sequence error          TestCheckTag_skippedCounterErrors
//	K4 counter superseded by a newer tag     -> out-of-sequence error          TestCheckTag_supersededCounterErrors
//	K5 cloud tag discovered from a plain ref -> valid                          TestCheckTag_discoversCloudTagAtRef
//
// Stable tag states:
//
//	T1 next patch on its branch              -> valid                          TestCheckTag_nextStablePatchPasses
//	T2 first patch of a fresh minor          -> valid                          TestCheckTag_firstStablePatchPasses
//	T3 tag commit not on the release branch  -> error                          TestCheckTag_offBranchStableErrors
//	T4 no release/vX.Y branch on origin      -> error                          TestCheckTag_missingBranchErrors
//	T5 patch out of sequence (skip or stale) -> error                          TestCheckTag_stableOutOfSequenceErrors
//	T6 predecessor not an ancestor           -> error                          TestCheckTag_predecessorNotAncestorErrors
//	T7 tag fetch from origin fails           -> error, no local fallback       TestCheckTag_fetchFailureErrors
//
// Beta tag states:
//
//	B1 first beta on its branch              -> valid                          TestCheckTag_firstBetaPasses
//	B2 next beta, predecessor an ancestor    -> valid                          TestCheckTag_nextBetaPasses
//	B3 tag commit not on the release branch  -> error                          TestCheckTag_offBranchBetaErrors
//	B4 counter skipped (beta.1 without .0)   -> out-of-sequence error          TestCheckTag_skippedBetaCounterErrors
//	B5 base already released as stable       -> error                          TestCheckTag_betaAfterStableErrors
//	B6 predecessor beta not an ancestor      -> error                          TestCheckTag_betaPredecessorNotAncestorErrors
//	B7 legacy bare -beta form                -> not a release tag, error       TestCheckTag_bareBetaFormErrors
//
// Tag resolution states:
//
//	R1 ref with no release tag               -> error                          TestCheckTag_noReleaseTagAtRefErrors
//	R2 ref with several release tags         -> error, no guessing             TestCheckTag_ambiguousRefErrors

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestCheckTag_freshCloudTagPasses(t *testing.T) {
	// Precondition: the tag `ods release cloud` would cut for the post-cut
	// commit, pushed to origin.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.6.0-cloud.0", repo.PostCutSHA)
	gittest.Git(t, repo.Work, "push", "--quiet", "origin", "v4.6.0-cloud.0")

	// Under test and postcondition.
	if err := CheckTag("v4.6.0-cloud.0"); err != nil {
		t.Errorf("expected the fresh tag to pass the check, got %v", err)
	}
}

func TestCheckTag_wrongCloudBaseErrors(t *testing.T) {
	// Precondition: the branches derive base v4.6.0 for the post-cut commit.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-cloud.0", repo.PostCutSHA)

	// Under test.
	err := CheckTag("v4.5.0-cloud.0")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "expected base") || !strings.Contains(err.Error(), "v4.6.0") {
		t.Errorf("expected a wrong-base error naming v4.6.0, got %v", err)
	}
}

func TestCheckTag_skippedCounterErrors(t *testing.T) {
	// Precondition: cloud.1 exists without cloud.0.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.6.0-cloud.1", repo.PostCutSHA)

	// Under test.
	err := CheckTag("v4.6.0-cloud.1")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "out of sequence") || !strings.Contains(err.Error(), "v4.6.0-cloud.0") {
		t.Errorf("expected an out-of-sequence error naming v4.6.0-cloud.0, got %v", err)
	}
}

func TestCheckTag_supersededCounterErrors(t *testing.T) {
	// Precondition: a newer counter already exists for the base.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.6.0-cloud.0", repo.PostCutSHA)
	gittest.Git(t, repo.Work, "tag", "v4.6.0-cloud.1", repo.PostCutSHA)

	// Under test.
	err := CheckTag("v4.6.0-cloud.0")

	// Postcondition: without the checked tag, cloud.1 makes cloud.2 the next.
	if err == nil || !strings.Contains(err.Error(), "out of sequence") || !strings.Contains(err.Error(), "v4.6.0-cloud.2") {
		t.Errorf("expected an out-of-sequence error naming v4.6.0-cloud.2, got %v", err)
	}
}

func TestCheckTag_discoversCloudTagAtRef(t *testing.T) {
	// Precondition: exactly one release tag points at the between-cuts commit,
	// whose derived base is v4.5.0.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-cloud.0", repo.CutSHA)

	// Under test: a plain commit-ish, not the tag name.
	err := CheckTag(repo.CutSHA)

	// Postcondition.
	if err != nil {
		t.Errorf("expected the discovered tag to pass the check, got %v", err)
	}
}

func TestCheckTag_nextStablePatchPasses(t *testing.T) {
	// Precondition: v4.4.2 is the highest v4.4.* tag, at the release/v4.4 tip.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.4.3", repo.PreCutSHA)

	// Under test and postcondition.
	if err := CheckTag("v4.4.3"); err != nil {
		t.Errorf("expected the next patch to pass the check, got %v", err)
	}
}

func TestCheckTag_firstStablePatchPasses(t *testing.T) {
	// Precondition: no v4.5.* tags exist yet.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0", repo.CutSHA)

	// Under test and postcondition.
	if err := CheckTag("v4.5.0"); err != nil {
		t.Errorf("expected the first patch to pass the check, got %v", err)
	}
}

func TestCheckTag_offBranchStableErrors(t *testing.T) {
	// Precondition: the post-cut commit is on main only, not release/v4.4.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.4.3", repo.PostCutSHA)

	// Under test.
	err := CheckTag("v4.4.3")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not on origin/release/v4.4") {
		t.Errorf("expected an off-branch error, got %v", err)
	}
}

func TestCheckTag_missingBranchErrors(t *testing.T) {
	// Precondition: origin has no release/v9.9 branch.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v9.9.0", repo.PreCutSHA)

	// Under test.
	err := CheckTag("v9.9.0")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "release/v9.9") {
		t.Errorf("expected a missing-branch error, got %v", err)
	}
}

func TestCheckTag_stableOutOfSequenceErrors(t *testing.T) {
	// Precondition: the fixture's v4.4.2 has no v4.4.0 or v4.4.1 below it.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test and postcondition: without v4.4.2 itself the sequence starts
	// at v4.4.0, so the tag is out of sequence.
	err := CheckTag("v4.4.2")
	if err == nil || !strings.Contains(err.Error(), "out of sequence") || !strings.Contains(err.Error(), "v4.4.0") {
		t.Errorf("expected an out-of-sequence error naming v4.4.0, got %v", err)
	}

	// A skipped patch fails the same way: v4.4.2 makes v4.4.3 the next tag.
	gittest.Git(t, repo.Work, "tag", "v4.4.4", repo.PreCutSHA)
	err = CheckTag("v4.4.4")
	if err == nil || !strings.Contains(err.Error(), "out of sequence") || !strings.Contains(err.Error(), "v4.4.3") {
		t.Errorf("expected an out-of-sequence error naming v4.4.3, got %v", err)
	}
}

func TestCheckTag_predecessorNotAncestorErrors(t *testing.T) {
	// Precondition: v1.0.0 sits at the branch tip, v1.0.1 at an older commit,
	// so both are on the branch and in sequence but ordered backwards.
	_, work := gittest.InitOriginAndWork(t)
	olderSHA := gittest.Commit(t, work, "a.txt")
	tipSHA := gittest.Commit(t, work, "b.txt")
	gittest.PublishMain(t, work)
	gittest.PublishReleaseBranch(t, work, "release/v1.0", tipSHA)
	gittest.Git(t, work, "tag", "v1.0.0", tipSHA)
	gittest.Git(t, work, "tag", "v1.0.1", olderSHA)
	t.Chdir(work)

	// Under test.
	err := CheckTag("v1.0.1")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not an ancestor") {
		t.Errorf("expected a predecessor-not-ancestor error, got %v", err)
	}
}

func TestCheckTag_fetchFailureErrors(t *testing.T) {
	// Precondition: a tag that would pass the check, but an unreachable
	// origin. Unlike a cut, a check must not fall back to local tags: a stale
	// view could pass an out-of-sequence tag.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.4.3", repo.PreCutSHA)
	gittest.Git(t, repo.Work, "remote", "set-url", "origin", t.TempDir())

	// Under test.
	err := CheckTag("v4.4.3")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "failed to fetch") {
		t.Errorf("expected a fetch failure error, got %v", err)
	}
}

func TestCheckTag_firstBetaPasses(t *testing.T) {
	// Precondition: v4.5.0 has not shipped and has no betas yet.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-beta.0", repo.CutSHA)

	// Under test and postcondition.
	if err := CheckTag("v4.5.0-beta.0"); err != nil {
		t.Errorf("expected the first beta to pass the check, got %v", err)
	}
}

func TestCheckTag_nextBetaPasses(t *testing.T) {
	// Precondition: beta.0 is an ancestor of (here: at) the beta.1 commit.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-beta.0", repo.CutSHA)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-beta.1", repo.CutSHA)

	// Under test and postcondition.
	if err := CheckTag("v4.5.0-beta.1"); err != nil {
		t.Errorf("expected the next beta to pass the check, got %v", err)
	}
}

func TestCheckTag_offBranchBetaErrors(t *testing.T) {
	// Precondition: the post-cut commit is on main only, not release/v4.5.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-beta.0", repo.PostCutSHA)

	// Under test.
	err := CheckTag("v4.5.0-beta.0")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not on origin/release/v4.5") {
		t.Errorf("expected an off-branch error, got %v", err)
	}
}

func TestCheckTag_skippedBetaCounterErrors(t *testing.T) {
	// Precondition: beta.1 exists without beta.0.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-beta.1", repo.CutSHA)

	// Under test.
	err := CheckTag("v4.5.0-beta.1")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "out of sequence") || !strings.Contains(err.Error(), "v4.5.0-beta.0") {
		t.Errorf("expected an out-of-sequence error naming v4.5.0-beta.0, got %v", err)
	}
}

func TestCheckTag_betaAfterStableErrors(t *testing.T) {
	// Precondition: the fixture's v4.4.2 stable tag has already shipped.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.4.2-beta.0", repo.PreCutSHA)

	// Under test.
	err := CheckTag("v4.4.2-beta.0")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "already been released") {
		t.Errorf("expected an already-released error, got %v", err)
	}
}

func TestCheckTag_betaPredecessorNotAncestorErrors(t *testing.T) {
	// Precondition: beta.0 sits at the branch tip, beta.1 at an older commit,
	// so both are on the branch and in sequence but ordered backwards.
	_, work := gittest.InitOriginAndWork(t)
	olderSHA := gittest.Commit(t, work, "a.txt")
	tipSHA := gittest.Commit(t, work, "b.txt")
	gittest.PublishMain(t, work)
	gittest.PublishReleaseBranch(t, work, "release/v1.0", tipSHA)
	gittest.Git(t, work, "tag", "v1.0.0-beta.0", tipSHA)
	gittest.Git(t, work, "tag", "v1.0.0-beta.1", olderSHA)
	t.Chdir(work)

	// Under test.
	err := CheckTag("v1.0.0-beta.1")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not an ancestor") {
		t.Errorf("expected a predecessor-not-ancestor error, got %v", err)
	}
}

func TestCheckTag_bareBetaFormErrors(t *testing.T) {
	// Precondition: the legacy counterless form, last used by v3.2.0-beta.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-beta", repo.CutSHA)

	// Under test.
	err := CheckTag("v4.5.0-beta")

	// Postcondition: the bare form is not a release tag; new betas must carry
	// a counter.
	if err == nil || !strings.Contains(err.Error(), "no cloud") {
		t.Errorf("expected a no-release-tag error, got %v", err)
	}
}

func TestCheckTag_noReleaseTagAtRefErrors(t *testing.T) {
	// Precondition: no tags point at the between-cuts commit.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	err := CheckTag(repo.CutSHA)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "no cloud") {
		t.Errorf("expected a no-release-tag error, got %v", err)
	}
}

func TestCheckTag_ambiguousRefErrors(t *testing.T) {
	// Precondition: the fixture's v4.4.0-cloud.9 already points at the
	// post-cut commit; add a second release tag there.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.6.0-cloud.0", repo.PostCutSHA)

	// Under test.
	err := CheckTag(repo.PostCutSHA)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "multiple release tags") {
		t.Errorf("expected a multiple-release-tags error, got %v", err)
	}
}
