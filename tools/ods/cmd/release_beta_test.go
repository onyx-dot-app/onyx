package cmd

// Command states for releaseBeta. Tag computation and validation are tested
// in internal/release; these tests pin the command-level flow. The fixture's
// newest release branch is release/v4.5 with tip CutSHA, so the computed tag
// is v4.5.0-beta.0.
//
//	E1 dry run                               -> prints tag, creates nothing,
//	                                            returns no pushed tag           TestReleaseBeta_dryRunCreatesNothing
//	E2 real run                              -> tag on origin at the release
//	                                            branch tip, tag name returned   TestReleaseBeta_tagsReleaseBranchTip
//	E3 push rejected by origin               -> local tag rolled back,
//	                                            returns no pushed tag           TestReleaseBeta_pushFailureRollsBackLocalTag
//	E4 counter tag only on origin            -> fetched, counter continues,
//	                                            tag name returned               TestReleaseBeta_fetchesRemoteOnlyCounterTags
//	E5 --version with leading zeroes         -> rejected before any git work    TestReleaseBeta_rejectsLeadingZeroVersion
//	E6 origin moves during the prompt        -> recompute mismatch aborts       TestReleaseBeta_staleStateAbortsBeforePush
//	                                            before any tag or push          (tests the guard directly; the
//	                                                                            prompt itself is interactive)

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/release"
)

func TestReleaseBeta_dryRunCreatesNothing(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	tag, err := releaseBeta(&ReleaseBetaOptions{DryRun: true, Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "" {
		t.Errorf("dry run must return no pushed tag, got %q", tag)
	}
	if gittest.TagExists(repo.Work, "v4.5.0-beta.0") || gittest.TagExists(repo.Origin, "v4.5.0-beta.0") {
		t.Error("dry run must not create the tag")
	}
}

func TestReleaseBeta_tagsReleaseBranchTip(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	tag, err := releaseBeta(&ReleaseBetaOptions{Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.5.0-beta.0" {
		t.Errorf("expected pushed tag v4.5.0-beta.0, got %q", tag)
	}
	taggedSHA := gittest.Git(t, repo.Origin, "rev-parse", "refs/tags/v4.5.0-beta.0^{commit}")
	if taggedSHA != repo.CutSHA {
		t.Errorf("expected origin tag at %s, got %s", repo.CutSHA, taggedSHA)
	}
}

func TestReleaseBeta_fetchesRemoteOnlyCounterTags(t *testing.T) {
	// Precondition.
	// A counter tag another developer pushed but this clone never fetched.
	// Computing from local tags alone would mint a colliding v4.5.0-beta.3.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "tag", "v4.5.0-beta.3", repo.CutSHA)
	gittest.Git(t, repo.Work, "push", "--quiet", "origin", "v4.5.0-beta.3")
	gittest.Git(t, repo.Work, "tag", "-d", "v4.5.0-beta.3")

	// Under test.
	tag, err := releaseBeta(&ReleaseBetaOptions{Yes: true})

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if tag != "v4.5.0-beta.4" {
		t.Errorf("expected pushed tag v4.5.0-beta.4, got %q", tag)
	}
	if !gittest.TagExists(repo.Origin, "v4.5.0-beta.4") {
		t.Error("expected v4.5.0-beta.4 on origin")
	}
}

func TestReleaseBeta_rejectsLeadingZeroVersion(t *testing.T) {
	// Precondition.
	// SemVer 2.0.0 item 2 forbids leading zeroes in numeric identifiers; such
	// an override must never become a tag.
	gittest.SetupReleaseBranchRepo(t)

	// Under test and postcondition.
	for _, version := range []string{"04.5.0", "4.05.0", "4.5.00"} {
		_, err := releaseBeta(&ReleaseBetaOptions{Version: version, DryRun: true, Yes: true})
		if err == nil || !strings.Contains(err.Error(), "--version must be X.Y.Z") {
			t.Errorf("expected validation error for %q, got %v", version, err)
		}
	}
}

func TestReleaseBeta_staleStateAbortsBeforePush(t *testing.T) {
	// Precondition: the tag computed before the confirmation prompt.
	repo := gittest.SetupReleaseBranchRepo(t)
	tag, sha, err := release.ComputeBetaTag("", "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// An unchanged origin passes.
	if err := verifyBetaStateUnchanged(tag, sha, &ReleaseBetaOptions{}); err != nil {
		t.Errorf("expected the unchanged state to pass, got %v", err)
	}

	// Another release process ships the stable base while the prompt waits.
	// Origin would accept the beta push (the tag name is new), and
	// deployment.yml's image jobs would move the "beta" Docker tags backwards
	// even though its tag check fails; the guard must abort instead.
	gittest.Git(t, repo.Work, "tag", "v4.5.0", repo.CutSHA)
	gittest.Git(t, repo.Work, "push", "--quiet", "origin", "v4.5.0")
	gittest.Git(t, repo.Work, "tag", "-d", "v4.5.0")

	// Under test.
	err = verifyBetaStateUnchanged(tag, sha, &ReleaseBetaOptions{})

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "origin changed while waiting") {
		t.Errorf("expected an origin-changed error, got %v", err)
	}
}

func TestReleaseBeta_pushFailureRollsBackLocalTag(t *testing.T) {
	// Precondition.
	// Origin rejects every push.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.RejectPushes(t, repo.Origin)

	// Under test.
	tag, err := releaseBeta(&ReleaseBetaOptions{Yes: true})

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "failed to push") {
		t.Errorf("expected push failure, got %v", err)
	}
	if tag != "" {
		t.Errorf("failed push must return no pushed tag, got %q", tag)
	}
	if gittest.TagExists(repo.Work, "v4.5.0-beta.0") {
		t.Error("local tag must be rolled back after a failed push")
	}
}
