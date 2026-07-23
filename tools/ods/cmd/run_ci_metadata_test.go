package cmd

import (
	"strings"
	"testing"
)

func TestBuildRunCIPRMetadataForEdits(t *testing.T) {
	prInfo := &PRInfo{
		Number:      1234,
		Title:       "feat: add useful feature",
		Body:        "Contributor-provided context.",
		HeadRefName: "feat/useful-feature",
	}

	metadata := buildRunCIPRMetadata(prInfo, true)

	if metadata.Branch != "feat/useful-feature-pr-1234-edits" {
		t.Errorf("unexpected branch: %s", metadata.Branch)
	}
	if metadata.Title != "feat: add useful feature [edit of #1234]" {
		t.Errorf("unexpected title: %s", metadata.Title)
	}
	expectedBodyParts := []string{
		"This PR supersedes #1234.",
		"Merge this PR and close #1234 without merging.",
		"## Original PR description",
		prInfo.Body,
		cherryPickOption,
		linearCheckOverride,
	}
	for _, expected := range expectedBodyParts {
		if !strings.Contains(metadata.Body, expected) {
			t.Errorf("expected body to contain %q, got:\n%s", expected, metadata.Body)
		}
	}
}

func TestBuildEditableBranchName(t *testing.T) {
	tests := []struct {
		name           string
		originalBranch string
		expectedBranch string
	}{
		{
			name:           "preserves expected prefix",
			originalBranch: "refactor/simplify-indexing",
			expectedBranch: "refactor/simplify-indexing-pr-1234-edits",
		},
		{
			name:           "defaults to chore prefix",
			originalBranch: "simplify-indexing",
			expectedBranch: "chore/simplify-indexing-pr-1234-edits",
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			prInfo := &PRInfo{Number: 1234, HeadRefName: test.originalBranch}
			if branch := buildEditableBranchName(prInfo); branch != test.expectedBranch {
				t.Errorf("expected branch %q, got %q", test.expectedBranch, branch)
			}
		})
	}
}

func TestBuildRunCIPRMetadataForEditsPreservesCherryPickSelection(t *testing.T) {
	originalOption := "- [x] [Optional] " + cherryPickOptionText
	prInfo := &PRInfo{
		Number:      1234,
		Title:       "fix: example",
		Body:        originalOption,
		HeadRefName: "fix/example",
	}

	metadata := buildRunCIPRMetadata(prInfo, true)

	if strings.Count(metadata.Body, cherryPickOptionText) != 1 {
		t.Errorf("expected original cherry-pick option exactly once, got:\n%s", metadata.Body)
	}
	if !strings.Contains(metadata.Body, originalOption) {
		t.Errorf("expected checked cherry-pick option to be preserved, got:\n%s", metadata.Body)
	}
}

func TestBuildRunCIPRMetadataForEditsOmitsEmptyOriginalBody(t *testing.T) {
	metadata := buildRunCIPRMetadata(
		&PRInfo{Number: 1234, Title: "fix: example", HeadRefName: "fix/example"},
		true,
	)

	if strings.Contains(metadata.Body, "Original PR description") {
		t.Errorf("empty original description should be omitted, got:\n%s", metadata.Body)
	}
}

func TestBuildRunCIPRMetadataForCI(t *testing.T) {
	metadata := buildRunCIPRMetadata(&PRInfo{Number: 1234}, false)

	if metadata.Branch != "run-ci/1234" {
		t.Errorf("unexpected branch: %s", metadata.Branch)
	}
	if metadata.Title != "chore: [Running GitHub actions for #1234]" {
		t.Errorf("unexpected title: %s", metadata.Title)
	}
	if !strings.Contains(metadata.Body, "closed (not merged)") {
		t.Errorf("CI-only PR body should say not to merge it, got:\n%s", metadata.Body)
	}
}

func TestRunCIRejectsForEditsWithRerun(t *testing.T) {
	command := NewRunCICommand()
	if err := command.ParseFlags([]string{"--for-edits", "--rerun"}); err != nil {
		t.Fatalf("failed to parse flags: %v", err)
	}

	err := command.Args(command, []string{"1234"})
	if err == nil || !strings.Contains(err.Error(), "would discard edits") {
		t.Fatalf("expected incompatible flags error, got: %v", err)
	}
}
