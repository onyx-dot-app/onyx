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
	if err := installCodexSkills(discardCmd(), testUI(), skills, repoRoot, false); err != nil {
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
	if err := installCodexSkills(discardCmd(), testUI(), skills, repoRoot, false); err != nil {
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

func TestInstallCodexSkillsSymlinksNativeSkills(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	source := t.TempDir()
	repoRoot := gitRepo(t)
	writeSkill(t, source, "skills", "on-demand", "db work", "Use sessions.")

	skills := discover(t, source)
	if err := installCodexSkills(discardCmd(), testUI(), skills, repoRoot, false); err != nil {
		t.Fatal(err)
	}

	link := filepath.Join(home, agentsSkillsDir, "on-demand")
	target, err := os.Readlink(link)
	if err != nil {
		t.Fatalf("expected %s to be a symlink: %v", link, err)
	}
	if filepath.IsAbs(target) {
		t.Fatalf("expected a relative link target, got %q", target)
	}
	// Codex reads the SKILL.md format directly, frontmatter included.
	if got := skillReadFile(t, filepath.Join(link, "SKILL.md")); !strings.Contains(got, "description: db work") {
		t.Fatalf("expected the linked skill to keep its frontmatter, got %q", got)
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

	if err := installCodexSkills(discardCmd(), testUI(), nil, repoRoot, false); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(generated); !os.IsNotExist(err) {
		t.Fatalf("stale compiled file should be removed: %v", err)
	}

	// A hand-written file of the same name survives the same rerun.
	deployWriteFile(t, generated, "my own local notes")
	if err := installCodexSkills(discardCmd(), testUI(), nil, repoRoot, false); err != nil {
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

	err := installCodexSkills(discardCmd(), testUI(), discover(t, source), repoRoot, false)

	if err == nil {
		t.Fatal("expected the failed exclusion to fail the install")
	}
	// The compiled file must not exist unignored: one git add away from a
	// public diff is exactly what the exclusion prevents.
	if _, statErr := os.Stat(filepath.Join(repoRoot, agentsLocalFile)); !os.IsNotExist(statErr) {
		t.Fatalf("compiled file must not be written before the exclusion: %v", statErr)
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
		t.Fatalf("enforced skill missing from the compiled file: %q", compiled)
	}
	link := filepath.Join(home, agentsSkillsDir, "review")
	if _, err := os.Readlink(link); err != nil {
		t.Fatalf("expected the on-demand skill to be symlinked: %v", err)
	}
	if !strings.Contains(out, "Installed "+filepath.Join(repoRoot, agentsLocalFile)) ||
		!strings.Contains(out, "Linked  "+link) {
		t.Fatalf("expected install output, got %q", out)
	}

	// A rerun reports the compiled file as up to date and re-links the skill.
	out, err = skillRun(t, "--source", source, "--agent", "codex")
	if err != nil {
		t.Fatalf("second install-skill: %v", err)
	}
	if !strings.Contains(out, "Up to date "+filepath.Join(repoRoot, agentsLocalFile)) ||
		!strings.Contains(out, "Linked  "+link) {
		t.Fatalf("expected an up-to-date rerun, got %q", out)
	}
}

func TestInstallCodexSkillsKeepsAHandWrittenAgentsLocal(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	source := t.TempDir()
	repoRoot := gitRepo(t)
	writeSkill(t, source, "enforced", "rule-a", "first", "Do A.")
	deployWriteFile(t, filepath.Join(repoRoot, agentsLocalFile), "my local notes")

	if err := installCodexSkills(discardCmd(), testUI(), discover(t, source), repoRoot, false); err != nil {
		t.Fatal(err)
	}

	if got := skillReadFile(t, filepath.Join(repoRoot, ".agents-local_old.md")); got != "my local notes" {
		t.Fatalf("hand-written local file was not preserved: %q", got)
	}
	if got := skillReadFile(t, filepath.Join(repoRoot, agentsLocalFile)); !strings.Contains(got, "Do A.") {
		t.Fatalf("compiled file was not installed: %q", got)
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

	if err := installCodexSkills(discardCmd(), testUI(), discover(t, source), repoRoot, false); err == nil {
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

func TestLinkManualSkillsRemovesStaleLinksIntoTheSourceOnly(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	source := t.TempDir()
	repoRoot := gitRepo(t)
	writeSkill(t, source, "enforced", "rule-a", "first", "Do A.")
	writeSkill(t, source, "skills", "kept", "still here", "Body.")
	// A link into the source whose skill is gone, a link elsewhere, and a
	// real directory the user made themselves.
	skillsDir := filepath.Join(home, agentsSkillsDir)
	deployWriteFile(t, filepath.Join(source, "skills", "removed", "SKILL.md"), "old")
	staleTarget := filepath.Join(source, "skills", "removed")
	stale := filepath.Join(skillsDir, "removed")
	foreign := filepath.Join(skillsDir, "foreign")
	if err := os.MkdirAll(skillsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(staleTarget, stale); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(t.TempDir(), foreign); err != nil {
		t.Fatal(err)
	}
	handWritten := filepath.Join(skillsDir, "mine")
	deployWriteFile(t, filepath.Join(handWritten, "SKILL.md"), "hand-written")
	// The removed skill vanishes from the source after it was linked.
	if err := os.RemoveAll(staleTarget); err != nil {
		t.Fatal(err)
	}

	if err := installCodexSkills(discardCmd(), testUI(), discover(t, source), repoRoot, false); err != nil {
		t.Fatal(err)
	}

	if _, err := os.Lstat(stale); !os.IsNotExist(err) {
		t.Fatalf("stale link into the source should be removed: %v", err)
	}
	if _, err := os.Lstat(foreign); err != nil {
		t.Fatalf("a link to somewhere else must survive: %v", err)
	}
	if _, err := os.Stat(filepath.Join(handWritten, "SKILL.md")); err != nil {
		t.Fatalf("a hand-written directory must survive: %v", err)
	}
	if _, err := os.Readlink(filepath.Join(skillsDir, "kept")); err != nil {
		t.Fatalf("the current skill should be linked: %v", err)
	}

	// With the manual tier emptied, the kept link goes stale and is removed too.
	if err := os.RemoveAll(filepath.Join(source, "skills")); err != nil {
		t.Fatal(err)
	}
	if err := installCodexSkills(discardCmd(), testUI(), discover(t, source), repoRoot, false); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(filepath.Join(skillsDir, "kept")); !os.IsNotExist(err) {
		t.Fatalf("links of an emptied manual tier should be removed: %v", err)
	}
}
