package cmd

// Release tag check state matrix (checkReleaseTag; `ods release --check`).
// The fixture (setupReleaseBranchRepo) cuts release/v4.4 at preCutSHA (which
// carries the v4.4.2 tag) and release/v4.5 at cutSHA.
//
// Cloud tag states:
//
//	K1 tag just cut by releaseCloud          -> valid                          TestCheckReleaseTag_freshCloudTagPasses
//	K2 base disagrees with release branches  -> error naming both bases        TestCheckReleaseTag_wrongCloudBaseErrors
//	K3 counter skipped (cloud.1 without .0)  -> out-of-sequence error          TestCheckReleaseTag_skippedCounterErrors
//	K4 counter superseded by a newer tag     -> out-of-sequence error          TestCheckReleaseTag_supersededCounterErrors
//	K5 cloud tag discovered from a plain ref -> valid                          TestCheckReleaseTag_discoversCloudTagAtRef
//
// Stable tag states:
//
//	T1 next patch on its branch              -> valid                          TestCheckReleaseTag_nextStablePatchPasses
//	T2 first patch of a fresh minor          -> valid                          TestCheckReleaseTag_firstStablePatchPasses
//	T3 tag commit not on the release branch  -> error                          TestCheckReleaseTag_offBranchStableErrors
//	T4 no release/vX.Y branch on origin      -> error                          TestCheckReleaseTag_missingBranchErrors
//	T5 patch out of sequence (skip or stale) -> error                          TestCheckReleaseTag_stableOutOfSequenceErrors
//	T6 predecessor not an ancestor           -> error                          TestCheckReleaseTag_predecessorNotAncestorErrors
//
// Tag resolution states:
//
//	R1 ref with no release tag               -> error                          TestCheckReleaseTag_noReleaseTagAtRefErrors
//	R2 ref with several release tags         -> error, no guessing             TestCheckReleaseTag_ambiguousRefErrors

import (
	"strings"
	"testing"
)

func TestCheckReleaseTag_freshCloudTagPasses(t *testing.T) {
	// Precondition: a tag cut by `ods release cloud` itself.
	setupReleaseBranchRepo(t)
	if err := releaseCloud(&ReleaseCloudOptions{Ref: "origin/main", Yes: true}); err != nil {
		t.Fatalf("failed to cut the tag: %v", err)
	}

	// Under test and postcondition.
	if err := checkReleaseTag("v4.6.0-cloud.0"); err != nil {
		t.Errorf("expected the fresh tag to pass the check, got %v", err)
	}
}

func TestCheckReleaseTag_wrongCloudBaseErrors(t *testing.T) {
	// Precondition: the branches derive base v4.6.0 for the post-cut commit.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "tag", "v4.5.0-cloud.0", repo.postCutSHA)

	// Under test.
	err := checkReleaseTag("v4.5.0-cloud.0")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "expected base") || !strings.Contains(err.Error(), "v4.6.0") {
		t.Errorf("expected a wrong-base error naming v4.6.0, got %v", err)
	}
}

func TestCheckReleaseTag_skippedCounterErrors(t *testing.T) {
	// Precondition: cloud.1 exists without cloud.0.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "tag", "v4.6.0-cloud.1", repo.postCutSHA)

	// Under test.
	err := checkReleaseTag("v4.6.0-cloud.1")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "out of sequence") || !strings.Contains(err.Error(), "v4.6.0-cloud.0") {
		t.Errorf("expected an out-of-sequence error naming v4.6.0-cloud.0, got %v", err)
	}
}

func TestCheckReleaseTag_supersededCounterErrors(t *testing.T) {
	// Precondition: a newer counter already exists for the base.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "tag", "v4.6.0-cloud.0", repo.postCutSHA)
	gitIn(t, repo.work, "tag", "v4.6.0-cloud.1", repo.postCutSHA)

	// Under test.
	err := checkReleaseTag("v4.6.0-cloud.0")

	// Postcondition: without the checked tag, cloud.1 makes cloud.2 the next.
	if err == nil || !strings.Contains(err.Error(), "out of sequence") || !strings.Contains(err.Error(), "v4.6.0-cloud.2") {
		t.Errorf("expected an out-of-sequence error naming v4.6.0-cloud.2, got %v", err)
	}
}

func TestCheckReleaseTag_discoversCloudTagAtRef(t *testing.T) {
	// Precondition: exactly one release tag points at the between-cuts commit,
	// whose derived base is v4.5.0.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "tag", "v4.5.0-cloud.0", repo.cutSHA)

	// Under test: a plain commit-ish, not the tag name.
	err := checkReleaseTag(repo.cutSHA)

	// Postcondition.
	if err != nil {
		t.Errorf("expected the discovered tag to pass the check, got %v", err)
	}
}

func TestCheckReleaseTag_nextStablePatchPasses(t *testing.T) {
	// Precondition: v4.4.2 is the highest v4.4.* tag, at the release/v4.4 tip.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "tag", "v4.4.3", repo.preCutSHA)

	// Under test and postcondition.
	if err := checkReleaseTag("v4.4.3"); err != nil {
		t.Errorf("expected the next patch to pass the check, got %v", err)
	}
}

func TestCheckReleaseTag_firstStablePatchPasses(t *testing.T) {
	// Precondition: no v4.5.* tags exist yet.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "tag", "v4.5.0", repo.cutSHA)

	// Under test and postcondition.
	if err := checkReleaseTag("v4.5.0"); err != nil {
		t.Errorf("expected the first patch to pass the check, got %v", err)
	}
}

func TestCheckReleaseTag_offBranchStableErrors(t *testing.T) {
	// Precondition: the post-cut commit is on main only, not release/v4.4.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "tag", "v4.4.3", repo.postCutSHA)

	// Under test.
	err := checkReleaseTag("v4.4.3")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not on origin/release/v4.4") {
		t.Errorf("expected an off-branch error, got %v", err)
	}
}

func TestCheckReleaseTag_missingBranchErrors(t *testing.T) {
	// Precondition: origin has no release/v9.9 branch.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "tag", "v9.9.0", repo.preCutSHA)

	// Under test.
	err := checkReleaseTag("v9.9.0")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "release/v9.9") {
		t.Errorf("expected a missing-branch error, got %v", err)
	}
}

func TestCheckReleaseTag_stableOutOfSequenceErrors(t *testing.T) {
	// Precondition: the fixture's v4.4.2 has no v4.4.0 or v4.4.1 below it.
	repo := setupReleaseBranchRepo(t)

	// Under test and postcondition: without v4.4.2 itself the sequence starts
	// at v4.4.0, so the tag is out of sequence.
	err := checkReleaseTag("v4.4.2")
	if err == nil || !strings.Contains(err.Error(), "out of sequence") || !strings.Contains(err.Error(), "v4.4.0") {
		t.Errorf("expected an out-of-sequence error naming v4.4.0, got %v", err)
	}

	// A skipped patch fails the same way: v4.4.2 makes v4.4.3 the next tag.
	gitIn(t, repo.work, "tag", "v4.4.4", repo.preCutSHA)
	err = checkReleaseTag("v4.4.4")
	if err == nil || !strings.Contains(err.Error(), "out of sequence") || !strings.Contains(err.Error(), "v4.4.3") {
		t.Errorf("expected an out-of-sequence error naming v4.4.3, got %v", err)
	}
}

func TestCheckReleaseTag_predecessorNotAncestorErrors(t *testing.T) {
	// Precondition: v1.0.0 sits at the branch tip, v1.0.1 at an older commit,
	// so both are on the branch and in sequence but ordered backwards.
	_, work := initOriginAndWork(t)
	olderSHA := commitIn(t, work, "a.txt")
	tipSHA := commitIn(t, work, "b.txt")
	publishMain(t, work)
	publishReleaseBranch(t, work, "release/v1.0", tipSHA)
	gitIn(t, work, "tag", "v1.0.0", tipSHA)
	gitIn(t, work, "tag", "v1.0.1", olderSHA)
	t.Chdir(work)

	// Under test.
	err := checkReleaseTag("v1.0.1")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not an ancestor") {
		t.Errorf("expected a predecessor-not-ancestor error, got %v", err)
	}
}

func TestCheckReleaseTag_noReleaseTagAtRefErrors(t *testing.T) {
	// Precondition: no tags point at the between-cuts commit.
	repo := setupReleaseBranchRepo(t)

	// Under test.
	err := checkReleaseTag(repo.cutSHA)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "no cloud") {
		t.Errorf("expected a no-release-tag error, got %v", err)
	}
}

func TestCheckReleaseTag_ambiguousRefErrors(t *testing.T) {
	// Precondition: the fixture's v4.4.0-cloud.9 already points at the
	// post-cut commit; add a second release tag there.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "tag", "v4.6.0-cloud.0", repo.postCutSHA)

	// Under test.
	err := checkReleaseTag(repo.postCutSHA)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "multiple release tags") {
		t.Errorf("expected a multiple-release-tags error, got %v", err)
	}
}
