package release

// Cloud tag state matrix. A "cut" is the commit where a release/vX.Y branch was
// created off main; the branch contains every main commit up to its cut and
// none after. The base version of a cloud tag is one minor past the newest
// release branch that does not contain the tagged commit. That places the tag
// above every release whose branch is missing the commit and below every
// release whose branch contains it.
//
// Base states (ComputeCloudTag; the fixture cuts release/v4.4, then
// release/v4.5, on a shared main line):
//
//	S1 commit after the v4.5 cut             -> v4.6.0-cloud.0                  TestComputeCloudTag_postCutCommitBumpsPastNewestBranch
//	S2 commit after the v4.4 cut, before v4.5's -> v4.5.0-cloud.0               TestComputeCloudTag_betweenCutsBumpsPastOlderBranch
//	S3 commit before every cut               -> error, hint --version           TestComputeCloudTag_commitOnAllBranchesErrors
//	S4 no release branches on origin         -> error, hint --version           TestComputeCloudTag_noReleaseBranchesErrors
//	S5 v4.5 never branched (v4.4, v4.6 cuts) -> between-cuts commit still v4.5.0 TestComputeCloudTag_skippedMinorStaysCutAnchored
//	S6 v4.10 and v5.0 cuts                   -> v4.11.0 / v5.1.0 (numeric bump) TestComputeCloudTag_doubleDigitMinorAndMajorBoundary
//	S7 commit not on origin/main             -> error                           TestComputeCloudTag_commitNotOnMainErrors
//	S8 shallow clone (even with --version)   -> error                           TestComputeCloudTag_shallowCloneErrors
//	S9 --version override                    -> override base, counter fresh    TestComputeCloudTag_versionOverride
//
// Counter states (existing tags vs a base; nextSequencedTag,
// TestNextSequencedTag_countersPerBase):
//
//	C1 no tags for the base                  -> cloud.0
//	C2 gaps in counters                      -> max+1, gaps not refilled
//	C3 counter 9 and 10 present             -> cloud.11 (numeric, not lexical)
//	C4 cloud tags only under other bases     -> cloud.0
//	C5 same-base beta and stable tags        -> ignored, cloud.0
//	C6 malformed cloud suffixes              -> ignored, cloud.0
//	C7 base that prefixes another base       -> no cross-base bleed, cloud.0

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestComputeCloudTag_postCutCommitBumpsPastNewestBranch(t *testing.T) {
	// Precondition: the fixture's v4.4.0-cloud.9 tag also pins that counters
	// under other bases do not bleed into a fresh base.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	tag, err := ComputeCloudTag(repo.PostCutSHA, "")

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.6.0-cloud.0" {
		t.Errorf("expected v4.6.0-cloud.0, got %s", tag)
	}
}

func TestComputeCloudTag_betweenCutsBumpsPastOlderBranch(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test: the v4.5 cut point is on release/v4.5 but not release/v4.4,
	// so its code ships in v4.5.0 and the tag must sort below v4.5.0.
	tag, err := ComputeCloudTag(repo.CutSHA, "")

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.5.0-cloud.0" {
		t.Errorf("expected v4.5.0-cloud.0, got %s", tag)
	}
}

func TestComputeCloudTag_commitOnAllBranchesErrors(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	_, err := ComputeCloudTag(repo.PreCutSHA, "")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "already contained in every release branch") {
		t.Errorf("expected already-contained error, got %v", err)
	}
	if err == nil || !strings.Contains(err.Error(), "--version") {
		t.Errorf("expected a --version hint, got %v", err)
	}
}

func TestComputeCloudTag_noReleaseBranchesErrors(t *testing.T) {
	// Precondition: an origin with main only.
	_, work := gittest.InitOriginAndWork(t)
	sha := gittest.Commit(t, work, "a.txt")
	gittest.PublishMain(t, work)
	t.Chdir(work)

	// Under test.
	_, err := ComputeCloudTag(sha, "")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "no release/vX.Y branches") {
		t.Errorf("expected no-release-branches error, got %v", err)
	}
	if err == nil || !strings.Contains(err.Error(), "--version") {
		t.Errorf("expected a --version hint, got %v", err)
	}
}

func TestComputeCloudTag_skippedMinorStaysCutAnchored(t *testing.T) {
	// Precondition: v4.5 was never branched; 4.5.0 will never ship.
	betweenSHA, postSHA := gittest.SetupTwoBranchRepo(t, "release/v4.4", "release/v4.6")

	// Under test and postcondition: the base is anchored to the branch cuts,
	// not to consecutive numbering. v4.5.0-cloud.N for the between commit is
	// sound: it sorts below v4.6.0, whose branch contains the commit.
	tag, err := ComputeCloudTag(betweenSHA, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.5.0-cloud.0" {
		t.Errorf("expected v4.5.0-cloud.0, got %s", tag)
	}
	tag, err = ComputeCloudTag(postSHA, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.7.0-cloud.0" {
		t.Errorf("expected v4.7.0-cloud.0, got %s", tag)
	}
}

func TestComputeCloudTag_doubleDigitMinorAndMajorBoundary(t *testing.T) {
	// Precondition.
	betweenSHA, postSHA := gittest.SetupTwoBranchRepo(t, "release/v4.10", "release/v5.0")

	// Under test and postcondition: v4.10 bumps numerically to v4.11.0, and a
	// commit past the v5.0 cut gets base v5.1.0 (major bumps are not guessed;
	// they arrive via the next branch cut or --version).
	tag, err := ComputeCloudTag(betweenSHA, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.11.0-cloud.0" {
		t.Errorf("expected v4.11.0-cloud.0, got %s", tag)
	}
	tag, err = ComputeCloudTag(postSHA, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v5.1.0-cloud.0" {
		t.Errorf("expected v5.1.0-cloud.0, got %s", tag)
	}
}

func TestComputeCloudTag_commitNotOnMainErrors(t *testing.T) {
	// Precondition: a commit on a feature branch only.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "checkout", "--quiet", "-b", "feature", repo.PreCutSHA)
	featureSHA := gittest.Commit(t, repo.Work, "f.txt")
	gittest.Git(t, repo.Work, "checkout", "--quiet", "main")

	// Under test.
	_, err := ComputeCloudTag(featureSHA, "")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not on origin/main") {
		t.Errorf("expected not-on-main error, got %v", err)
	}
}

func TestComputeCloudTag_shallowCloneErrors(t *testing.T) {
	// Precondition.
	sha := gittest.SetupShallowClone(t)

	// Under test: the override skips release-branch detection, so this pins
	// computeCloudBase's own shallow guard, not FindTargetVersion's.
	_, err := ComputeCloudTag(sha, "5.0.0")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "shallow clone") {
		t.Errorf("expected shallow-clone error, got %v", err)
	}
}

func TestComputeCloudTag_versionOverride(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	tag, err := ComputeCloudTag(repo.PostCutSHA, "5.0.0")

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v5.0.0-cloud.0" {
		t.Errorf("expected v5.0.0-cloud.0, got %s", tag)
	}
}

func TestNextSequencedTag_countersPerBase(t *testing.T) {
	// Precondition: one repo holding every counter state side by side.
	_, work := gittest.InitOriginAndWork(t)
	sha := gittest.Commit(t, work, "a.txt")
	for _, tag := range []string{
		"v4.6.0-cloud.0", "v4.6.0-cloud.5", // Gap between counters.
		"v4.7.0-cloud.9", "v4.7.0-cloud.10", // Numeric vs lexical ordering.
		"v4.9.0-beta.1", "v4.9.0", // Same-base non-cloud tags.
		"v4.10.0-cloud.5",                                         // Base that v4.1.0 prefixes.
		"v4.12.0-cloud", "v4.12.0-cloud.abc", "v4.12.0-cloud.1.2", "v4.12.0-cloud.007", // Malformed suffixes.
	} {
		gittest.Git(t, work, "tag", tag, sha)
	}
	t.Chdir(work)

	// Under test and postcondition.
	cases := []struct {
		base string
		want string
	}{
		{"v4.6.0", "v4.6.0-cloud.6"},
		{"v4.7.0", "v4.7.0-cloud.11"},
		{"v4.8.0", "v4.8.0-cloud.0"},
		{"v4.9.0", "v4.9.0-cloud.0"},
		{"v4.10.0", "v4.10.0-cloud.6"},
		{"v4.12.0", "v4.12.0-cloud.0"},
		{"v4.1.0", "v4.1.0-cloud.0"},
	}
	for _, tc := range cases {
		t.Run(tc.base, func(t *testing.T) {
			tag, err := nextSequencedTag(tc.base+"-cloud.", "")
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if tag != tc.want {
				t.Errorf("expected %s, got %s", tc.want, tag)
			}
		})
	}
}
