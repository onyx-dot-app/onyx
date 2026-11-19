package cmd

import (
	"strings"
	"testing"
	"unicode/utf8"
)

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

func TestBuildEditableBranchNameBoundsLastComponent(t *testing.T) {
	longComponent := strings.Repeat("界", 85)
	prInfo := &PRInfo{
		Number:      1234,
		HeadRefName: fixBranchPrefix + longComponent,
	}

	branch := buildEditableBranchName(prInfo)
	component := strings.TrimPrefix(branch, fixBranchPrefix)

	if len(component) > gitRefComponentMaxBytes {
		t.Errorf("component exceeds %d bytes: %d", gitRefComponentMaxBytes, len(component))
	}
	if !utf8.ValidString(component) {
		t.Errorf("branch component is not valid UTF-8: %q", component)
	}
	if !strings.HasSuffix(component, "-pr-1234-edits") {
		t.Errorf("branch component is missing edit suffix: %q", component)
	}
}

func TestBuildEditablePRTitleBoundsLength(t *testing.T) {
	prInfo := &PRInfo{
		Number: 1234,
		Title:  strings.Repeat("界", githubPRTitleMaxRunes),
	}

	title := buildEditablePRTitle(prInfo)

	if utf8.RuneCountInString(title) != githubPRTitleMaxRunes {
		t.Errorf(
			"expected %d-rune title, got %d",
			githubPRTitleMaxRunes,
			utf8.RuneCountInString(title),
		)
	}
	if !strings.HasSuffix(title, " [edit of #1234]") {
		t.Errorf("title is missing edit suffix: %q", title)
	}
}

func TestBuildRunCIPRMetadataForEditsBody(t *testing.T) {
	header := "> [!IMPORTANT]\n> This PR supersedes #1234. Merge this PR and close #1234 without merging."
	checked := "- [x] [Optional] " + cherryPickOptionText
	prose := "Use the checkbox if you want us to " + cherryPickOptionText
	tests := []struct {
		name string
		body string
		want string
	}{
		{"empty original body is omitted", "  \n", header + "\n\n" + cherryPickOption},
		{"checked option is kept, not added again", checked, header + "\n\n## Original PR description\n\n" + checked},
		{"option text in prose still adds the checkbox", prose, header + "\n\n## Original PR description\n\n" + prose + "\n\n" + cherryPickOption},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			prInfo := &PRInfo{Number: 1234, Title: "fix: example", Body: test.body, HeadRefName: "fix/example"}
			if got := buildRunCIPRMetadata(prInfo, true).Body; got != test.want {
				t.Errorf("expected body\n%q\ngot\n%q", test.want, got)
			}
		})
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
