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

func TestParseVersions_skipsNumbersPastTheIntRange(t *testing.T) {
	// Under test.
	versions := parseVersions([]string{
		"release/v99999999999999999999.1",
		"release/v4.99999999999999999999",
		"release/v4.5",
	})

	// Postcondition.
	if len(versions) != 1 || versions[0].String() != "v4.5" {
		t.Errorf("expected only v4.5, got %v", versions)
	}
}

func TestIsBareVersion(t *testing.T) {
	for _, c := range []struct {
		in   string
		want bool
	}{
		{"4.5.0", true},
		{"0.0.0", true},
		{"v4.5.0", false},
		{"4.05.0", false},
		{"4.5", false},
		{"4.5.0-beta.1", false},
	} {
		if got := IsBareVersion(c.in); got != c.want {
			t.Errorf("expected IsBareVersion(%q) = %v, got %v", c.in, c.want, got)
		}
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

func TestFindTargetVersion_originUnreachableErrors(t *testing.T) {
	// Precondition.
	repo := gittest.SetupReleaseBranchRepo(t)
	gittest.Git(t, repo.Work, "remote", "set-url", "origin", t.TempDir())

	// Under test.
	_, err := FindTargetVersion(repo.PostCutSHA)

	// Postcondition.
	if err == nil || !strings.Contains(err.Error(), "git ls-remote failed") {
		t.Errorf("expected an ls-remote error, got %v", err)
	}
}

func TestFindTargetVersion_unknownCommitErrors(t *testing.T) {
	// Precondition: a SHA that names no object.
	gittest.SetupReleaseBranchRepo(t)

	// Under test.
	_, err := FindTargetVersion("0123456789abcdef0123456789abcdef01234567")

	// Postcondition: an unknown commit is an error, not "not contained".
	if err == nil || !strings.Contains(err.Error(), "merge-base --is-ancestor") {
		t.Errorf("expected an ancestry error, got %v", err)
	}
}
