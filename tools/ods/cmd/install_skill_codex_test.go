package cmd

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func gitRepo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	gitCmd := exec.Command("git", "init", "-q")
	gitCmd.Dir = dir
	if err := gitCmd.Run(); err != nil {
		t.Skipf("git unavailable: %v", err)
	}
	return dir
}

func TestInstallCodexSkillsCompilesEnforcedAndExcludesTheFile(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	source := t.TempDir()
	repoRoot := gitRepo(t)
	writeSkill(t, source, "enforced", "rule-a", "first", "Do A.")
	writeSkill(t, source, "enforced", "rule-b", "second", "Do B.")
	writeSkill(t, source, "skills", "on-demand", "db work", "Use sessions.")

	skills, err := discoverLLMContextSkills(source)
	if err != nil {
		t.Fatal(err)
	}
	if err := installCodexSkills(discardCmd(), skills, repoRoot); err != nil {
		t.Fatal(err)
	}

	compiled, err := os.ReadFile(filepath.Join(repoRoot, agentsLocalFile))
	if err != nil {
		t.Fatal(err)
	}
	content := string(compiled)
	if !strings.Contains(content, "## rule-a\n\nDo A.") ||
		!strings.Contains(content, "## rule-b\n\nDo B.") {
		t.Fatalf("enforced skills missing from compiled file:\n%s", content)
	}
	if strings.Contains(content, "Use sessions.") {
		t.Fatalf("on-demand skill leaked into the always-on file:\n%s", content)
	}

	exclude, err := os.ReadFile(filepath.Join(repoRoot, ".git", "info", "exclude"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(exclude), agentsLocalFile) {
		t.Fatalf("%s missing from git exclude:\n%s", agentsLocalFile, exclude)
	}

	// A rerun must not duplicate the exclude entry.
	if err := installCodexSkills(discardCmd(), skills, repoRoot); err != nil {
		t.Fatal(err)
	}
	exclude, _ = os.ReadFile(filepath.Join(repoRoot, ".git", "info", "exclude"))
	if strings.Count(string(exclude), agentsLocalFile) != 1 {
		t.Fatalf("exclude entry duplicated:\n%s", exclude)
	}
}

func TestInstallCodexSkillsWritesPromptsAndRemovesStaleOnes(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	source := t.TempDir()
	repoRoot := gitRepo(t)
	writeSkill(t, source, "skills", "on-demand", "db work", "Use sessions.")

	promptsDir := filepath.Join(home, codexPromptsDir)
	if err := os.MkdirAll(promptsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	stale := filepath.Join(promptsDir, "removed-skill.md")
	if err := os.WriteFile(stale, []byte(generatedRuleMarker+"\nold"), 0o644); err != nil {
		t.Fatal(err)
	}
	handWritten := filepath.Join(promptsDir, "my-prompt.md")
	if err := os.WriteFile(handWritten, []byte("mine"), 0o644); err != nil {
		t.Fatal(err)
	}

	skills, err := discoverLLMContextSkills(source)
	if err != nil {
		t.Fatal(err)
	}
	if err := installCodexSkills(discardCmd(), skills, repoRoot); err != nil {
		t.Fatal(err)
	}

	prompt, err := os.ReadFile(filepath.Join(promptsDir, "on-demand.md"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(prompt), "Use sessions.") {
		t.Fatalf("prompt body missing:\n%s", prompt)
	}
	// The skill's frontmatter must not ride into the prompt.
	if strings.Contains(string(prompt), "description:") {
		t.Fatalf("frontmatter leaked into the prompt:\n%s", prompt)
	}
	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Fatalf("stale generated prompt should be removed: %v", err)
	}
	if _, err := os.Stat(handWritten); err != nil {
		t.Fatalf("hand-written prompt must survive: %v", err)
	}
	// No enforced skills, so no compiled file is written.
	if _, err := os.Stat(filepath.Join(repoRoot, agentsLocalFile)); !os.IsNotExist(err) {
		t.Fatalf("compiled file should not exist without enforced skills: %v", err)
	}
}
