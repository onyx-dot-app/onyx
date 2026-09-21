package cmd

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func gitRepo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	gittest.Git(t, dir, "init", "--quiet")
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
	if err := installCodexSkills(discardCmd(), testUI(), skills, repoRoot); err != nil {
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
	if err := installCodexSkills(discardCmd(), testUI(), skills, repoRoot); err != nil {
		t.Fatal(err)
	}
	exclude, err = os.ReadFile(filepath.Join(repoRoot, ".git", "info", "exclude"))
	if err != nil {
		t.Fatal(err)
	}
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
	if err := installCodexSkills(discardCmd(), testUI(), skills, repoRoot); err != nil {
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

func TestInstallCodexSkillsRemovesTheCompiledFileWhenEnforcedSkillsVanish(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	repoRoot := gitRepo(t)
	generated := filepath.Join(repoRoot, agentsLocalFile)
	deployWriteFile(t, generated, generatedRuleMarker+"\nold rules")

	if err := installCodexSkills(discardCmd(), testUI(), nil, repoRoot); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(generated); !os.IsNotExist(err) {
		t.Fatalf("stale compiled file should be removed: %v", err)
	}

	// A hand-written file of the same name survives the same rerun.
	deployWriteFile(t, generated, "my own local notes")
	if err := installCodexSkills(discardCmd(), testUI(), nil, repoRoot); err != nil {
		t.Fatal(err)
	}
	if got := skillReadFile(t, generated); got != "my own local notes" {
		t.Fatalf("hand-written file must survive: %q", got)
	}
}

func TestInstallCodexSkillsExcludesBeforeWriting(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	source := t.TempDir()
	writeSkill(t, source, "enforced", "rule-a", "first", "Do A.")
	// Not a git repo, so establishing the exclusion fails.
	repoRoot := t.TempDir()

	err := installCodexSkills(discardCmd(), testUI(), discover(t, source), repoRoot)

	if err == nil {
		t.Fatal("expected the failed exclusion to fail the install")
	}
	// The compiled file must not exist unignored: one git add away from a
	// public diff is exactly what the exclusion prevents.
	if _, statErr := os.Stat(filepath.Join(repoRoot, agentsLocalFile)); !os.IsNotExist(statErr) {
		t.Fatalf("compiled file must not be written before the exclusion: %v", statErr)
	}
}

func TestInstallCodexSkillsRemovesStalePromptsWhenSkillsVanish(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	repoRoot := gitRepo(t)
	stale := filepath.Join(home, codexPromptsDir, "removed-skill.md")
	deployWriteFile(t, stale, generatedRuleMarker+"\nold")

	if err := installCodexSkills(discardCmd(), testUI(), nil, repoRoot); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Fatalf("stale generated prompt should be removed: %v", err)
	}

	// Without a prompts directory, nothing is created.
	freshHome := t.TempDir()
	t.Setenv("HOME", freshHome)
	if err := installCodexSkills(discardCmd(), testUI(), nil, gitRepo(t)); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(freshHome, ".codex")); !os.IsNotExist(err) {
		t.Fatalf("expected no .codex directory, got %v", err)
	}
}

func TestInstallSkill_agentCodexEndToEnd(t *testing.T) {
	home, repoRoot := skillEnv(t)
	source := filepath.Join(t.TempDir(), "onyx-llm-context")
	skillWriteSource(t, source)

	out, err := skillRun(t, "--source", source, "--agent", "codex")
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	compiled := skillReadFile(t, filepath.Join(repoRoot, agentsLocalFile))
	if !strings.Contains(compiled, "## style") {
		t.Fatalf("enforced skill missing from the compiled file:\n%s", compiled)
	}
	if got := skillReadFile(t, filepath.Join(home, codexPromptsDir, "review.md")); !strings.Contains(got, "review") {
		t.Fatalf("prompt missing: %q", got)
	}
	if !strings.Contains(out, "Installed "+filepath.Join(repoRoot, agentsLocalFile)) {
		t.Fatalf("expected install output, got %q", out)
	}

	// A rerun reports both outputs as up to date.
	out, err = skillRun(t, "--source", source, "--agent", "codex")
	if err != nil {
		t.Fatalf("second install-skill: %v", err)
	}
	for _, want := range []string{
		"Up to date " + filepath.Join(repoRoot, agentsLocalFile),
		"Up to date " + filepath.Join(home, codexPromptsDir, "review.md"),
	} {
		if !strings.Contains(out, want) {
			t.Fatalf("expected %q, got %q", want, out)
		}
	}
}

func TestInstallCodexSkillsKeepsConflictingHandWrittenFiles(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	source := t.TempDir()
	repoRoot := gitRepo(t)
	writeSkill(t, source, "enforced", "rule-a", "first", "Do A.")
	writeSkill(t, source, "skills", "on-demand", "db work", "Use sessions.")
	// Both destinations already hold files the user wrote.
	deployWriteFile(t, filepath.Join(repoRoot, agentsLocalFile), "my local notes")
	prompt := filepath.Join(home, codexPromptsDir, "on-demand.md")
	deployWriteFile(t, prompt, "my own prompt")

	if err := installCodexSkills(discardCmd(), testUI(), discover(t, source), repoRoot); err != nil {
		t.Fatal(err)
	}

	if got := skillReadFile(t, filepath.Join(repoRoot, ".agents-local_old.md")); got != "my local notes" {
		t.Fatalf("hand-written local file was not preserved: %q", got)
	}
	if got := skillReadFile(t, filepath.Join(home, codexPromptsDir, "on-demand_old.md")); got != "my own prompt" {
		t.Fatalf("hand-written prompt was not preserved: %q", got)
	}
	if got := skillReadFile(t, prompt); !strings.Contains(got, "Use sessions.") {
		t.Fatalf("generated prompt was not installed: %q", got)
	}
}

func TestRemoveStaleAgentsLocalLeavesAHandWrittenFile(t *testing.T) {
	repoRoot := t.TempDir()
	dest := filepath.Join(repoRoot, agentsLocalFile)
	deployWriteFile(t, dest, "my own notes, no marker")

	if err := removeStaleAgentsLocal(discardCmd(), repoRoot); err != nil {
		t.Fatal(err)
	}
	if got := skillReadFile(t, dest); got != "my own notes, no marker" {
		t.Fatalf("hand-written file must survive: %q", got)
	}
	// A missing file is a no-op, not an error.
	if err := removeStaleAgentsLocal(discardCmd(), t.TempDir()); err != nil {
		t.Fatal(err)
	}
}

func TestExcludeAgentsLocalAppendsToAnExistingListWithoutTrailingNewline(t *testing.T) {
	repoRoot := gitRepo(t)
	excludePath := filepath.Join(repoRoot, ".git", "info", "exclude")
	deployWriteFile(t, excludePath, "*.tmp")

	if err := excludeAgentsLocal(repoRoot); err != nil {
		t.Fatal(err)
	}

	content := skillReadFile(t, excludePath)
	if !strings.Contains(content, "*.tmp\n"+agentsLocalFile+"\n") {
		t.Fatalf("expected the entry appended on its own line, got %q", content)
	}
}

func requireNonRoot(t *testing.T) {
	t.Helper()
	if os.Geteuid() == 0 {
		t.Skip("permission-denied paths cannot be exercised as root")
	}
}

func TestInstallSkill_claudeMDWriteFailureFailsTheInstall(t *testing.T) {
	_, repoRoot := skillEnv(t)
	source := filepath.Join(t.TempDir(), "onyx-llm-context")
	skillWriteSource(t, source)
	// .claude exists as a file, so creating the directory fails.
	deployWriteFile(t, filepath.Join(repoRoot, ".claude"), "in the way")

	if _, err := skillRun(t, "--source", source); err == nil ||
		!strings.Contains(err.Error(), ".claude") {
		t.Fatalf("expected the failed .claude write to fail the install, got %v", err)
	}
}

func TestResolveTargetDirFailsWhenTheChosenDirCannotBeCreated(t *testing.T) {
	blocked := filepath.Join(t.TempDir(), "file")
	deployWriteFile(t, blocked, "not a directory")
	ui := testUI()
	ui.interactive = true
	ui.confirm = func(string) bool { return false }
	ui.readString = func(string) string { return filepath.Join(blocked, "sub") }

	if _, err := ui.resolveTargetDir("Cursor rules", filepath.Join(t.TempDir(), "missing")); err == nil {
		t.Fatal("expected an uncreatable chosen directory to error")
	}
}

func TestInstallCodexSkillsFailsWhenTheCompiledFileCannotBeWritten(t *testing.T) {
	requireNonRoot(t)
	t.Setenv("HOME", t.TempDir())
	source := t.TempDir()
	repoRoot := gitRepo(t)
	writeSkill(t, source, "enforced", "rule-a", "first", "Do A.")
	if err := os.Chmod(repoRoot, 0o555); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(repoRoot, 0o755) })

	if err := installCodexSkills(discardCmd(), testUI(), discover(t, source), repoRoot); err == nil {
		t.Fatal("expected the unwritable repo root to fail the install")
	}
}

func TestRemoveStaleAgentsLocalFailsOnAnUnreadableFile(t *testing.T) {
	requireNonRoot(t)
	repoRoot := t.TempDir()
	dest := filepath.Join(repoRoot, agentsLocalFile)
	deployWriteFile(t, dest, "unreadable")
	if err := os.Chmod(dest, 0o000); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(dest, 0o644) })

	if err := removeStaleAgentsLocal(discardCmd(), repoRoot); err == nil {
		t.Fatal("expected an unreadable file to fail loudly")
	}
}
