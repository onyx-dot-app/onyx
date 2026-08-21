package release

import (
	"slices"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestParseVersions_sortsNewestFirstIgnoringNonMatching(t *testing.T) {
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
	versions := parseVersions(branchNames)

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

func TestParseVersions_emptyWhenNothingMatches(t *testing.T) {
	// Under test and postcondition.
	if versions := parseVersions([]string{"main", "hotfix/abc-v4.4"}); len(versions) != 0 {
		t.Errorf("expected no versions, got %v", versions)
	}
}

func TestFindTargetVersion_postCutCommitTargetsNewestBranch(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	version, err := FindTargetVersion(repo.PostCutSHA)

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if version.String() != "v4.5" {
		t.Errorf("expected v4.5, got %s", version)
	}
}

func TestFindTargetVersion_preCutCommitFallsBackToOlderBranch(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	version, err := FindTargetVersion(repo.CutSHA)

	// Postcondition.
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if version.String() != "v4.4" {
		t.Errorf("expected v4.4, got %s", version)
	}
}

func TestFindTargetVersion_commitOnAllBranchesErrors(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)

	// Under test.
	_, err := FindTargetVersion(repo.PreCutSHA)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "already contained in every release branch") {
		t.Errorf("expected already-contained error, got %v", err)
	}
}

func TestFindTargetVersion_shallowCloneErrors(t *testing.T) {
	// Precondition.
	sha := gittest.SetupShallowClone(t)

	// Under test.
	_, err := FindTargetVersion(sha)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "shallow clone") {
		t.Errorf("expected shallow-clone error, got %v", err)
	}
}
