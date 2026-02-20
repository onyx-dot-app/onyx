package cmd

import "testing"

func TestParseLatestReleaseVersion(t *testing.T) {
	t.Parallel()

	input := `
abc123	refs/heads/release/v2.9
def456	refs/heads/release/v2.10
ghi789	refs/heads/release/v2.10-jira-hotfix
jkl012	refs/heads/release/v2.12
mno345	refs/heads/release/v.test.fake
`

	got, err := parseLatestReleaseVersion(input)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if got != "v2.12" {
		t.Fatalf("expected v2.12, got %s", got)
	}
}

func TestParseLatestReleaseVersionErrorsWhenNoStableReleaseBranches(t *testing.T) {
	t.Parallel()

	input := `
abc123	refs/heads/release/v2.10-jira-hotfix
def456	refs/heads/release/v.test.fake
`

	_, err := parseLatestReleaseVersion(input)
	if err == nil {
		t.Fatal("expected error, got nil")
	}
}
