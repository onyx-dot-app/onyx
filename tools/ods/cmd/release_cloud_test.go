package cmd

// Cloud tag state matrix. A "cut" is the commit where a release/vX.Y branch was
// created off main; the branch contains every main commit up to its cut and
// none after. The base version of a cloud tag is one minor past the newest
// release branch that does not contain the tagged commit. That places the tag
// above every release whose branch is missing the commit and below every
// release whose branch contains it.
//
// Base states (computeCloudTag; the fixture cuts release/v4.4, then
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
// Counter states (existing tags vs a base; nextCloudTag, TestNextCloudTag_countersPerBase):
//
//	C1 no tags for the base                  -> cloud.0
//	C2 gaps in counters                      -> max+1, gaps not refilled
//	C3 counter 9 and 10 present             -> cloud.11 (numeric, not lexical)
//	C4 cloud tags only under other bases     -> cloud.0
//	C5 same-base beta and stable tags        -> ignored, cloud.0
//	C6 malformed cloud suffixes              -> ignored, cloud.0
//	C7 base that prefixes another base       -> no cross-base bleed, cloud.0
//
// Command states (releaseCloud):
//
//	E1 dry run                               -> prints tag, creates nothing     TestReleaseCloud_dryRunCreatesNothing
//	E2 real run                              -> tag on origin at origin/main    TestReleaseCloud_tagsOriginMainHead
//	E3 push rejected by origin               -> local tag rolled back           TestReleaseCloud_pushFailureRollsBackLocalTag
//	E4 counter tag only on origin            -> fetched, counter continues      TestReleaseCloud_fetchesRemoteOnlyCounterTags
//	E5 --version with leading zeroes         -> rejected before any git work    TestReleaseCloud_rejectsLeadingZeroVersion

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// tagExistsIn reports whether the tag exists in the repository at dir.
func tagExistsIn(dir, tag string) bool {
	cmd := exec.Command("git", "rev-parse", "-q", "--verify", "refs/tags/"+tag)
	cmd.Dir = dir
	return cmd.Run() == nil
}

// setupTwoBranchRepo creates an origin whose main holds four commits with
// branchA cut at the first and branchB at the third, chdirs into the work
// clone, and returns the SHA between the cuts and the SHA past both.
func setupTwoBranchRepo(t *testing.T, branchA, branchB string) (betweenSHA, postSHA string) {
	t.Helper()

	_, work := initOriginAndWork(t)
	cutA := commitIn(t, work, "a.txt")
	betweenSHA = commitIn(t, work, "b.txt")
	cutB := commitIn(t, work, "c.txt")
	postSHA = commitIn(t, work, "d.txt")

	publishMain(t, work)
	publishReleaseBranch(t, work, branchA, cutA)
	publishReleaseBranch(t, work, branchB, cutB)

	t.Chdir(work)
	return betweenSHA, postSHA
}

func TestComputeCloudTag_postCutCommitBumpsPastNewestBranch(t *testing.T) {
	// Precondition: the fixture's v4.4.0-cloud.9 tag also pins that counters
	// under other bases do not bleed into a fresh base.
	repo := setupReleaseBranchRepo(t)

	// Under test.
	tag, err := computeCloudTag(repo.postCutSHA, "")

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
	repo := setupReleaseBranchRepo(t)

	// Under test: the v4.5 cut point is on release/v4.5 but not release/v4.4,
	// so its code ships in v4.5.0 and the tag must sort below v4.5.0.
	tag, err := computeCloudTag(repo.cutSHA, "")

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
	repo := setupReleaseBranchRepo(t)

	// Under test.
	_, err := computeCloudTag(repo.preCutSHA, "")

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
	_, work := initOriginAndWork(t)
	sha := commitIn(t, work, "a.txt")
	publishMain(t, work)
	t.Chdir(work)

	// Under test.
	_, err := computeCloudTag(sha, "")

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
	betweenSHA, postSHA := setupTwoBranchRepo(t, "release/v4.4", "release/v4.6")

	// Under test and postcondition: the base is anchored to the branch cuts,
	// not to consecutive numbering. v4.5.0-cloud.N for the between commit is
	// sound: it sorts below v4.6.0, whose branch contains the commit.
	tag, err := computeCloudTag(betweenSHA, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.5.0-cloud.0" {
		t.Errorf("expected v4.5.0-cloud.0, got %s", tag)
	}
	tag, err = computeCloudTag(postSHA, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.7.0-cloud.0" {
		t.Errorf("expected v4.7.0-cloud.0, got %s", tag)
	}
}

func TestComputeCloudTag_doubleDigitMinorAndMajorBoundary(t *testing.T) {
	// Precondition.
	betweenSHA, postSHA := setupTwoBranchRepo(t, "release/v4.10", "release/v5.0")

	// Under test and postcondition: v4.10 bumps numerically to v4.11.0, and a
	// commit past the v5.0 cut gets base v5.1.0 (major bumps are not guessed;
	// they arrive via the next branch cut or --version).
	tag, err := computeCloudTag(betweenSHA, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.11.0-cloud.0" {
		t.Errorf("expected v4.11.0-cloud.0, got %s", tag)
	}
	tag, err = computeCloudTag(postSHA, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v5.1.0-cloud.0" {
		t.Errorf("expected v5.1.0-cloud.0, got %s", tag)
	}
}

func TestComputeCloudTag_commitNotOnMainErrors(t *testing.T) {
	// Precondition: a commit on a feature branch only.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "checkout", "--quiet", "-b", "feature", repo.preCutSHA)
	featureSHA := commitIn(t, repo.work, "f.txt")
	gitIn(t, repo.work, "checkout", "--quiet", "main")

	// Under test.
	_, err := computeCloudTag(featureSHA, "")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "not on origin/main") {
		t.Errorf("expected not-on-main error, got %v", err)
	}
}

func TestComputeCloudTag_shallowCloneErrors(t *testing.T) {
	// Precondition.
	sha := setupShallowClone(t)

	// Under test: the override skips release-branch detection, so this pins
	// computeCloudTag's own shallow guard, not findTargetReleaseVersion's.
	_, err := computeCloudTag(sha, "5.0.0")

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "shallow clone") {
		t.Errorf("expected shallow-clone error, got %v", err)
	}
}

func TestComputeCloudTag_versionOverride(t *testing.T) {
	// Precondition.
	repo := setupReleaseBranchRepo(t)

	// Under test.
	tag, err := computeCloudTag(repo.postCutSHA, "5.0.0")

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v5.0.0-cloud.0" {
		t.Errorf("expected v5.0.0-cloud.0, got %s", tag)
	}
}

func TestNextCloudTag_countersPerBase(t *testing.T) {
	// Precondition: one repo holding every counter state side by side.
	_, work := initOriginAndWork(t)
	sha := commitIn(t, work, "a.txt")
	for _, tag := range []string{
		"v4.6.0-cloud.0", "v4.6.0-cloud.5", // Gap between counters.
		"v4.7.0-cloud.9", "v4.7.0-cloud.10", // Numeric vs lexical ordering.
		"v4.9.0-beta.1", "v4.9.0", // Same-base non-cloud tags.
		"v4.10.0-cloud.5",                                         // Base that v4.1.0 prefixes.
		"v4.12.0-cloud", "v4.12.0-cloud.abc", "v4.12.0-cloud.1.2", // Malformed suffixes.
	} {
		gitIn(t, work, "tag", tag, sha)
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
			tag, err := nextCloudTag(tc.base)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if tag != tc.want {
				t.Errorf("expected %s, got %s", tc.want, tag)
			}
		})
	}
}

func TestReleaseCloud_dryRunCreatesNothing(t *testing.T) {
	// Precondition.
	repo := setupReleaseBranchRepo(t)

	// Under test.
	err := releaseCloud(&ReleaseCloudOptions{Ref: "origin/main", DryRun: true, Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tagExistsIn(repo.work, "v4.6.0-cloud.0") || tagExistsIn(repo.origin, "v4.6.0-cloud.0") {
		t.Error("dry run must not create the tag")
	}
}

func TestReleaseCloud_tagsOriginMainHead(t *testing.T) {
	// Precondition.
	repo := setupReleaseBranchRepo(t)

	// Under test.
	err := releaseCloud(&ReleaseCloudOptions{Ref: "origin/main", Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	taggedSHA := gitIn(t, repo.origin, "rev-parse", "refs/tags/v4.6.0-cloud.0^{commit}")
	if taggedSHA != repo.postCutSHA {
		t.Errorf("expected origin tag at %s, got %s", repo.postCutSHA, taggedSHA)
	}
}

func TestReleaseCloud_fetchesRemoteOnlyCounterTags(t *testing.T) {
	// Precondition: a counter tag another developer pushed but this clone never
	// fetched. Computing from local tags alone would mint a colliding
	// v4.6.0-cloud.3.
	repo := setupReleaseBranchRepo(t)
	gitIn(t, repo.work, "tag", "v4.6.0-cloud.3", repo.postCutSHA)
	gitIn(t, repo.work, "push", "--quiet", "origin", "v4.6.0-cloud.3")
	gitIn(t, repo.work, "tag", "-d", "v4.6.0-cloud.3")

	// Under test.
	err := releaseCloud(&ReleaseCloudOptions{Ref: "origin/main", Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !tagExistsIn(repo.origin, "v4.6.0-cloud.4") {
		t.Error("expected v4.6.0-cloud.4 on origin")
	}
}

func TestReleaseCloud_rejectsLeadingZeroVersion(t *testing.T) {
	// Precondition: SemVer 2.0.0 item 2 forbids leading zeroes in numeric
	// identifiers; such an override must never become a tag.
	setupReleaseBranchRepo(t)

	// Under test and postcondition.
	for _, version := range []string{"04.6.0", "4.06.0", "4.6.00"} {
		err := releaseCloud(&ReleaseCloudOptions{Ref: "origin/main", Version: version, DryRun: true, Yes: true})
		if err == nil || !strings.Contains(err.Error(), "--version must be X.Y.Z") {
			t.Errorf("expected validation error for %q, got %v", version, err)
		}
	}
}

func TestReleaseCloud_pushFailureRollsBackLocalTag(t *testing.T) {
	// Precondition: origin rejects every push.
	repo := setupReleaseBranchRepo(t)
	hook := filepath.Join(repo.origin, "hooks", "pre-receive")
	if err := os.WriteFile(hook, []byte("#!/bin/sh\nexit 1\n"), 0755); err != nil {
		t.Fatal(err)
	}

	// Under test.
	err := releaseCloud(&ReleaseCloudOptions{Ref: "origin/main", Yes: true})

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "failed to push") {
		t.Errorf("expected push failure, got %v", err)
	}
	if tagExistsIn(repo.work, "v4.6.0-cloud.0") {
		t.Error("local tag must be rolled back after a failed push")
	}
}
