package cmd

import (
	"bytes"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// skillEnv isolates HOME and makes a fresh git repo the working
// directory. It returns the home and repo root paths.
func skillEnv(t *testing.T) (home, repoRoot string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("symlink and shell fixtures are POSIX-only")
	}
	home = t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv(agentContextEnv, "")
	repoRoot = t.TempDir()
	gittest.Git(t, repoRoot, "init", "--quiet")
	t.Chdir(repoRoot)
	// Resolve symlinks (e.g. macOS /var -> /private/var) to match git's output.
	resolved, err := filepath.EvalSymlinks(repoRoot)
	if err != nil {
		t.Fatal(err)
	}
	return home, resolved
}

// skillWriteSource creates a skills root (the agent-context/ directory of
// onyx-infra, or an old onyx-llm-context checkout) with one enforced skill,
// one enforced directory without a SKILL.md, and one manual skill with a
// nested file.
func skillWriteSource(t *testing.T, source string) {
	t.Helper()
	deployWriteFile(t, filepath.Join(source, "enforced", "style", "SKILL.md"), "style")
	deployWriteFile(t, filepath.Join(source, "enforced", "draft", "notes.md"), "no skill file")
	deployWriteFile(t, filepath.Join(source, "enforced", "README.md"), "not a skill")
	deployWriteFile(t, filepath.Join(source, "skills", "review", "SKILL.md"), "review")
	deployWriteFile(t, filepath.Join(source, "skills", "review", "refs", "checklist.md"), "checklist")
	deployWriteFile(t, filepath.Join(source, "skills", "README.md"), "not a skill")
}

func skillRun(t *testing.T, args ...string) (string, error) {
	t.Helper()
	cmd := NewInstallSkillCommand()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetErr(&out)
	cmd.SetArgs(args)
	err := cmd.Execute()
	return out.String(), err
}

func skillReadFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestInstallSkill_linksManualSkillsAndImportsEnforcedOnes(t *testing.T) {
	_, repoRoot := skillEnv(t)
	source := filepath.Join(t.TempDir(), "onyx-infra")
	skillWriteSource(t, source)
	// A stale copy from an earlier --copy install must be replaced by a link.
	deployWriteFile(t, filepath.Join(repoRoot, projectSkillsDir, "review", "stale.md"), "stale")

	out, err := skillRun(t, "--source", source)
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	claudeMD := filepath.Join(repoRoot, ".claude", "CLAUDE.md")
	wantImports := "@" + filepath.Join(source, "enforced", "style", "SKILL.md") + "\n"
	if got := skillReadFile(t, claudeMD); got != wantImports {
		t.Fatalf("expected CLAUDE.md %q, got %q", wantImports, got)
	}
	link := filepath.Join(repoRoot, projectSkillsDir, "review")
	target, err := os.Readlink(link)
	if err != nil {
		t.Fatalf("expected %s to be a symlink: %v", link, err)
	}
	if filepath.IsAbs(target) {
		t.Fatalf("expected a relative link target, got %q", target)
	}
	if got := skillReadFile(t, filepath.Join(link, "refs", "checklist.md")); got != "checklist" {
		t.Fatalf("expected the link to reach the source skill, got %q", got)
	}
	if _, err := os.Lstat(filepath.Join(repoRoot, projectSkillsDir, "README.md")); !os.IsNotExist(err) {
		t.Fatalf("expected files outside skill directories to be skipped, got %v", err)
	}
	for _, want := range []string{"Installed " + claudeMD, "Linked  " + link + " -> " + target} {
		if !strings.Contains(out, want) {
			t.Fatalf("expected output to contain %q, got %q", want, out)
		}
	}

	// A second run leaves CLAUDE.md alone and re-creates the link.
	out, err = skillRun(t, "--source", source)
	if err != nil {
		t.Fatalf("second install-skill: %v", err)
	}
	if !strings.Contains(out, "Up to date "+claudeMD) || !strings.Contains(out, "Linked  "+link) {
		t.Fatalf("expected up-to-date CLAUDE.md and a re-linked skill, got %q", out)
	}
	if _, err := os.Readlink(link); err != nil {
		t.Fatalf("expected %s to stay a symlink: %v", link, err)
	}
}

func TestInstallSkill_installsIntoTheSharedSkillsDirWithoutDirtyingTheTree(t *testing.T) {
	_, repoRoot := skillEnv(t)
	// The Onyx layout: committed skills in .agents/skills, with .claude/skills
	// as a symlink to it.
	deployWriteFile(t, filepath.Join(repoRoot, ".agents", "skills", "review", "SKILL.md"), "committed")
	if err := os.MkdirAll(filepath.Join(repoRoot, ".claude"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("../.agents/skills", filepath.Join(repoRoot, ".claude", "skills")); err != nil {
		t.Fatal(err)
	}
	gittest.Git(t, repoRoot, "add", "-A")
	gittest.Git(t, repoRoot, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "skills")
	source := filepath.Join(t.TempDir(), "onyx-infra")
	skillWriteSource(t, source)
	deployWriteFile(t, filepath.Join(source, "skills", "fresh", "SKILL.md"), "fresh")

	out, err := skillRun(t, "--source", source, "--agent", "claude-code", "--agent", "codex")
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	if got := skillReadFile(t, filepath.Join(repoRoot, ".agents", "skills", "review", "SKILL.md")); got != "committed" {
		t.Fatalf("a committed skill must not be replaced, got %q", got)
	}
	if !strings.Contains(out, `skipping skill "review"`) {
		t.Fatalf("expected a warning about the committed skill, got %q", out)
	}
	if got := skillReadFile(t, filepath.Join(repoRoot, ".claude", "skills", "fresh", "SKILL.md")); got != "fresh" {
		t.Fatalf("expected the skill to be reachable through .claude/skills, got %q", got)
	}
	if n := strings.Count(out, "Linked  "); n != 1 {
		t.Fatalf("expected the shared directory to be filled once, got %d links in %q", n, out)
	}
	if status := gittest.Git(t, repoRoot, "status", "--porcelain", "--", ".agents"); status != "" {
		t.Fatalf("expected installed skills to stay out of git status, got %q", status)
	}
}

func TestLinkManualSkills_protectsCommittedSkillsInAChosenDirectory(t *testing.T) {
	_, repoRoot := skillEnv(t)
	chosen := filepath.Join(repoRoot, "my-skills")
	deployWriteFile(t, filepath.Join(chosen, "review", "SKILL.md"), "committed")
	gittest.Git(t, repoRoot, "add", "-A")
	gittest.Git(t, repoRoot, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "skills")
	source := filepath.Join(t.TempDir(), "onyx-infra")
	skillWriteSource(t, source)
	deployWriteFile(t, filepath.Join(source, "skills", "fresh", "SKILL.md"), "fresh")
	// .agents/skills is missing, so the user is asked and picks another directory.
	ui := &installUI{
		interactive: true,
		out:         io.Discard,
		confirm:     func(string) bool { return false },
		readString:  func(string) string { return chosen },
	}
	var stderr bytes.Buffer
	cmd := NewInstallSkillCommand()
	cmd.SetOut(io.Discard)
	cmd.SetErr(&stderr)

	// --copy leaves real files behind, the case an exclusion has to cover.
	if err := linkManualSkills(cmd, ui, discover(t, source), repoRoot, true); err != nil {
		t.Fatalf("linkManualSkills: %v", err)
	}

	if got := skillReadFile(t, filepath.Join(chosen, "review", "SKILL.md")); got != "committed" {
		t.Fatalf("a committed skill in the chosen directory must not be replaced, got %q", got)
	}
	if !strings.Contains(stderr.String(), `skipping skill "review"`) {
		t.Fatalf("expected a warning about the committed skill, got %q", stderr.String())
	}
	if got := skillReadFile(t, filepath.Join(chosen, "fresh", "SKILL.md")); got != "fresh" {
		t.Fatalf("expected the skill in the chosen directory, got %q", got)
	}
	if status := gittest.Git(t, repoRoot, "status", "--porcelain"); status != "" {
		t.Fatalf("expected the chosen directory to stay out of git status, got %q", status)
	}
	if _, err := os.Stat(filepath.Join(repoRoot, ".agents")); !os.IsNotExist(err) {
		t.Fatalf("expected the default directory not to be created, got %v", err)
	}
}

func TestInstallSkill_failingGitLsFilesStopsBeforeChangingAnything(t *testing.T) {
	_, repoRoot := skillEnv(t)
	realGit, err := exec.LookPath("git")
	if err != nil {
		t.Skip("git is not installed")
	}
	dir := t.TempDir()
	t.Setenv("ODS_TEST_REAL_GIT", realGit)
	deployWriteFile(t, filepath.Join(dir, "git"),
		"#!/bin/sh\nif [ \"$1\" = ls-files ]; then echo 'fatal: index file corrupt' >&2; exit 128; fi\n"+
			"exec \"$ODS_TEST_REAL_GIT\" \"$@\"\n")
	if err := os.Chmod(filepath.Join(dir, "git"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	skillsDir := filepath.Join(repoRoot, ".agents", "skills")
	deployWriteFile(t, filepath.Join(skillsDir, "review", "SKILL.md"), "committed")
	source := filepath.Join(t.TempDir(), "onyx-infra")
	skillWriteSource(t, source)

	_, err = skillRun(t, "--source", source, "--no-pull", "--agent", "codex")

	if err == nil || !strings.Contains(err.Error(), "could not check whether .agents/skills/review is committed") {
		t.Fatalf("expected the git failure to be reported, got %v", err)
	}
	if got := skillReadFile(t, filepath.Join(skillsDir, "review", "SKILL.md")); got != "committed" {
		t.Fatalf("the existing skill must be untouched, got %q", got)
	}
	if exclude, err := os.ReadFile(filepath.Join(repoRoot, ".git", "info", "exclude")); err == nil &&
		strings.Contains(string(exclude), ".agents/skills") {
		t.Fatalf("expected no exclusion to be written, got %q", exclude)
	}
}

func TestInstallSkill_copyModeCopiesSkillTrees(t *testing.T) {
	_, repoRoot := skillEnv(t)
	source := filepath.Join(t.TempDir(), "onyx-infra")
	skillWriteSource(t, source)

	out, err := skillRun(t, "--source", source, "--copy")
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	dst := filepath.Join(repoRoot, projectSkillsDir, "review")
	info, err := os.Lstat(dst)
	if err != nil {
		t.Fatal(err)
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		t.Fatalf("expected a real directory at %s, got mode %v", dst, info.Mode())
	}
	for rel, want := range map[string]string{"SKILL.md": "review", filepath.Join("refs", "checklist.md"): "checklist"} {
		if got := skillReadFile(t, filepath.Join(dst, rel)); got != want {
			t.Fatalf("expected %s to contain %q, got %q", rel, want, got)
		}
	}
	if !strings.Contains(out, "Copied  "+dst) {
		t.Fatalf("expected copy output, got %q", out)
	}
}

func TestInstallSkill_sourceWithoutSkillsInstallsNothing(t *testing.T) {
	home, repoRoot := skillEnv(t)
	source := t.TempDir()
	// An enforced directory without any SKILL.md must not create CLAUDE.md.
	deployWriteFile(t, filepath.Join(source, "enforced", "draft", "notes.md"), "draft")

	out, err := skillRun(t, "--source", source)
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}
	if out != "" {
		t.Fatalf("expected no output, got %q", out)
	}
	for _, path := range []string{filepath.Join(repoRoot, ".claude"), filepath.Join(home, ".claude")} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("expected %s not to exist, got %v", path, err)
		}
	}
}

// skillContextCheckout writes an onyx-agent-context checkout at dir: its
// AGENTS.md entry file and the given manual skills.
func skillContextCheckout(t *testing.T, dir string, skills ...string) {
	t.Helper()
	deployWriteFile(t, filepath.Join(dir, agentContextEntryFile), "entry")
	for _, name := range skills {
		deployWriteFile(t, filepath.Join(dir, "skills", name, "SKILL.md"), name)
	}
}

func TestInstallSkill_missingSourceRequiresClone(t *testing.T) {
	_, repoRoot := skillEnv(t)

	_, err := skillRun(t)

	wantSource := filepath.Join(filepath.Dir(repoRoot), agentContextRepoName)
	if err == nil || !strings.Contains(err.Error(), agentContextRepoName+" checkout not found at "+wantSource) || !strings.Contains(err.Error(), "--clone") {
		t.Fatalf("expected a hint to use --clone for %s, got %v", wantSource, err)
	}
}

func TestInstallSkill_findsTheContextNextToTheMainCheckoutFromAWorktree(t *testing.T) {
	_, repoRoot := skillEnv(t)
	gittest.Git(t, repoRoot, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
	worktree := filepath.Join(t.TempDir(), "feature")
	gittest.Git(t, repoRoot, "worktree", "add", "-q", worktree)
	t.Chdir(worktree)
	skillContextCheckout(t, filepath.Join(filepath.Dir(repoRoot), agentContextRepoName), "review")

	if _, err := skillRun(t, "--no-pull"); err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	if got := skillReadFile(t, filepath.Join(worktree, projectSkillsDir, "review", "SKILL.md")); got != "review" {
		t.Fatalf("expected the sibling checkout's skill in the worktree, got %q", got)
	}
}

func TestInstallSkill_envVarPathWinsOverTheSibling(t *testing.T) {
	_, repoRoot := skillEnv(t)
	skillContextCheckout(t, filepath.Join(filepath.Dir(repoRoot), agentContextRepoName), "sibling")
	explicit := filepath.Join(t.TempDir(), "my-context")
	skillContextCheckout(t, explicit, "explicit")
	t.Setenv(agentContextEnv, explicit)

	if _, err := skillRun(t, "--no-pull"); err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	if _, err := os.Lstat(filepath.Join(repoRoot, projectSkillsDir, "explicit")); err != nil {
		t.Fatalf("expected the $%s checkout to be installed: %v", agentContextEnv, err)
	}
	if _, err := os.Lstat(filepath.Join(repoRoot, projectSkillsDir, "sibling")); !os.IsNotExist(err) {
		t.Fatalf("expected the sibling checkout to be ignored, got %v", err)
	}
}

func TestInstallSkill_fallsBackToTheCheckoutInsideTheRepo(t *testing.T) {
	_, repoRoot := skillEnv(t)
	skillContextCheckout(t, filepath.Join(repoRoot, inRepoAgentContextDir), "review")
	// A sibling folder without the entry file is not the context.
	deployWriteFile(t, filepath.Join(filepath.Dir(repoRoot), agentContextRepoName, "README.md"), "not it")

	if _, err := skillRun(t, "--no-pull"); err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	if got := skillReadFile(t, filepath.Join(repoRoot, projectSkillsDir, "review", "SKILL.md")); got != "review" {
		t.Fatalf("expected the in-repo checkout to be installed, got %q", got)
	}
}

func TestCloneDestination_staysInsideTheCheckoutWhenItsFolderIsNotKept(t *testing.T) {
	// The devcontainer mounts the checkout at /workspace; / does not survive a rebuild.
	if got, want := cloneDestination("/workspace"), filepath.Join("/workspace", inRepoAgentContextDir); got != want {
		t.Fatalf("expected %s, got %s", want, got)
	}

	if os.Geteuid() == 0 {
		t.Skip("root ignores folder permissions")
	}
	parent := t.TempDir()
	mainRoot := filepath.Join(parent, "onyx")
	if err := os.Mkdir(mainRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	if got, want := cloneDestination(mainRoot), filepath.Join(parent, agentContextRepoName); got != want {
		t.Fatalf("expected %s, got %s", want, got)
	}
	if err := os.Chmod(parent, 0o555); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(parent, 0o755) })
	if got, want := cloneDestination(mainRoot), filepath.Join(mainRoot, inRepoAgentContextDir); got != want {
		t.Fatalf("expected %s, got %s", want, got)
	}
}

func TestInstallSkill_expandsHomeInTheEnvVarPath(t *testing.T) {
	home, repoRoot := skillEnv(t)
	skillContextCheckout(t, filepath.Join(home, "my-context"), "review")
	t.Setenv(agentContextEnv, "~/my-context")

	if _, err := skillRun(t, "--no-pull"); err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	if _, err := os.Lstat(filepath.Join(repoRoot, projectSkillsDir, "review")); err != nil {
		t.Fatalf("expected the ~/ path to be installed: %v", err)
	}
}

func TestInstallSkill_switchingFromAnOlderCheckoutRemovesItsLinks(t *testing.T) {
	home, repoRoot := skillEnv(t)
	skillWriteSource(t, filepath.Join(home, ".claude", "skills", "onyx-infra", agentContextDir))
	if _, err := skillRun(t, "--no-pull"); err != nil {
		t.Fatalf("install from the older checkout: %v", err)
	}
	if _, err := os.Lstat(filepath.Join(repoRoot, projectSkillsDir, "review")); err != nil {
		t.Fatalf("expected the older checkout's skill to be linked: %v", err)
	}

	skillContextCheckout(t, filepath.Join(filepath.Dir(repoRoot), agentContextRepoName), "fresh")
	if _, err := skillRun(t, "--no-pull"); err != nil {
		t.Fatalf("install from the new checkout: %v", err)
	}

	if _, err := os.Lstat(filepath.Join(repoRoot, projectSkillsDir, "review")); !os.IsNotExist(err) {
		t.Fatalf("expected the older checkout's link to be removed, got %v", err)
	}
	if _, err := os.Lstat(filepath.Join(repoRoot, projectSkillsDir, "fresh")); err != nil {
		t.Fatalf("expected the new checkout's skill to be linked: %v", err)
	}
}

// skillFakeGit puts a git wrapper first on PATH that records clone calls and
// runs the given script for them (the destination directory is "$dest");
// every other git call goes to the real git.
func skillFakeGit(t *testing.T, cloneScript string) string {
	t.Helper()
	realGit, err := exec.LookPath("git")
	if err != nil {
		t.Skip("git is not installed")
	}
	dir := t.TempDir()
	record := filepath.Join(dir, "git-calls")
	t.Setenv("ODS_TEST_REAL_GIT", realGit)
	script := "#!/bin/sh\n" +
		"for dest; do :; done\n" +
		"if [ \"$1\" = clone ]; then\n" +
		"  printf '%s\\n' \"$@\" >> \"${0%/*}/git-calls\"\n" +
		cloneScript +
		"fi\n" +
		"exec \"$ODS_TEST_REAL_GIT\" \"$@\"\n"
	deployWriteFile(t, filepath.Join(dir, "git"), script)
	if err := os.Chmod(filepath.Join(dir, "git"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	return record
}

func TestInstallSkill_cloneFetchesTheRepoNextToTheMainCheckout(t *testing.T) {
	_, repoRoot := skillEnv(t)
	record := skillFakeGit(t,
		"  mkdir -p \"$dest/skills/review\" && echo review > \"$dest/skills/review/SKILL.md\" && echo entry > \"$dest/AGENTS.md\"\n  exit 0\n",
	)

	out, err := skillRun(t, "--clone")
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	source := filepath.Join(filepath.Dir(repoRoot), agentContextRepoName)
	if got, want := skillReadFile(t, record), "clone\n"+agentContextCloneURL+"\n"+source+"\n"; got != want {
		t.Fatalf("expected git args %q, got %q", want, got)
	}
	if got := skillReadFile(t, filepath.Join(repoRoot, projectSkillsDir, "review", "SKILL.md")); got != "review\n" {
		t.Fatalf("expected the cloned skill to be installed, got %q", got)
	}
	if !strings.Contains(out, "Cloning "+agentContextCloneURL) || !strings.Contains(out, source) {
		t.Fatalf("expected clone output, got %q", out)
	}
}

func TestInstallSkill_cloneReplacesAnOlderCheckout(t *testing.T) {
	home, repoRoot := skillEnv(t)
	skillWriteSource(t, filepath.Join(home, ".claude", "skills", "onyx-infra", agentContextDir))
	record := skillFakeGit(t,
		"  mkdir -p \"$dest/skills/fresh\" && echo fresh > \"$dest/skills/fresh/SKILL.md\" && echo entry > \"$dest/AGENTS.md\"\n  exit 0\n",
	)

	if _, err := skillRun(t, "--clone"); err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	source := filepath.Join(filepath.Dir(repoRoot), agentContextRepoName)
	if got := skillReadFile(t, record); !strings.Contains(got, source) {
		t.Fatalf("expected a clone to %s, got %q", source, got)
	}
	if _, err := os.Lstat(filepath.Join(repoRoot, projectSkillsDir, "fresh")); err != nil {
		t.Fatalf("expected the new checkout to be installed: %v", err)
	}
}

func TestInstallSkill_cloneFailureStopsTheInstall(t *testing.T) {
	_, repoRoot := skillEnv(t)
	skillFakeGit(t, "  echo 'fatal: unable to access' >&2\n  exit 128\n")

	out, err := skillRun(t, "--clone")

	if err == nil || !strings.Contains(err.Error(), "git clone failed") {
		t.Fatalf("expected clone failure, got %v", err)
	}
	if !strings.Contains(err.Error(), "private repo") || !strings.Contains(err.Error(), "gh auth login") {
		t.Fatalf("expected an access hint, got %v", err)
	}
	if !strings.Contains(out, "fatal: unable to access") {
		t.Fatalf("expected git's error output to be forwarded, got %q", out)
	}
	if _, err := os.Stat(filepath.Join(repoRoot, projectSkillsDir)); !os.IsNotExist(err) {
		t.Fatalf("expected nothing installed, got %v", err)
	}
}

// TestCloneAgentContext_clonesTheRepo runs the real git against a local repo.
func TestCloneAgentContext_clonesTheRepo(t *testing.T) {
	skillEnv(t)
	remote := t.TempDir()
	gittest.Git(t, remote, "init", "--quiet", "-b", "main")
	skillContextCheckout(t, remote, "review")
	gittest.Git(t, remote, "add", "-A")
	gittest.Git(t, remote, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")

	dest := filepath.Join(t.TempDir(), agentContextRepoName)
	cmd := NewInstallSkillCommand()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetErr(&out)
	if err := cloneAgentContext(cmd, "file://"+remote, dest); err != nil {
		t.Fatalf("clone: %v\n%s", err, out.String())
	}

	skills, err := discoverAgentContextSkills(dest)
	if err != nil || len(skills) != 1 || skills[0].Name != "review" {
		t.Fatalf("expected to discover the review skill, got %v, %v", skills, err)
	}
}

func TestInstallSkill_readsSkillsFromTheAgentContextDirectory(t *testing.T) {
	_, repoRoot := skillEnv(t)
	checkout := filepath.Join(t.TempDir(), "onyx-infra")
	skillWriteSource(t, filepath.Join(checkout, "agent-context"))
	deployWriteFile(t, filepath.Join(checkout, "skills", "decoy", "SKILL.md"), "decoy")

	if _, err := skillRun(t, "--source", checkout, "--no-pull"); err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	link := filepath.Join(repoRoot, projectSkillsDir, "review")
	if got := skillReadFile(t, filepath.Join(link, "SKILL.md")); got != "review" {
		t.Fatalf("expected the agent-context skill, got %q", got)
	}
	if _, err := os.Lstat(filepath.Join(repoRoot, projectSkillsDir, "decoy")); !os.IsNotExist(err) {
		t.Fatalf("expected only agent-context/ to be read, got %v", err)
	}
}

func TestInstallSkill_sourceWithoutSkillsIsAnError(t *testing.T) {
	skillEnv(t)
	checkout := filepath.Join(t.TempDir(), "onyx-infra")
	deployWriteFile(t, filepath.Join(checkout, "README.md"), "an onyx-infra without agent-context/")

	_, err := skillRun(t, "--source", checkout, "--no-pull")

	if err == nil || !strings.Contains(err.Error(), "no skills/, enforced/, or agent-context/ directory found") {
		t.Fatalf("expected a missing skills error, got %v", err)
	}
}

func TestInstallSkill_fallsBackToTheOldDefaultCheckout(t *testing.T) {
	home, repoRoot := skillEnv(t)
	skillWriteSource(t, filepath.Join(home, ".claude", "skills", "onyx-llm-context"))

	out, err := skillRun(t, "--no-pull")
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	if got := skillReadFile(t, filepath.Join(repoRoot, projectSkillsDir, "review", "SKILL.md")); got != "review" {
		t.Fatalf("expected the old checkout to be installed, got %q", got)
	}
	if !strings.Contains(out, "older checkout") || !strings.Contains(out, "--clone") {
		t.Fatalf("expected a warning about the old checkout, got %q", out)
	}
}

func TestInstallSkill_refusesSymlinkedDestinations(t *testing.T) {
	cases := []struct {
		name    string
		agent   string
		dest    string
		content string
	}{
		{name: "claude CLAUDE.md", agent: "claude-code", dest: claudeMDFile, content: "original"},
		{name: "codex dangling .agents-local.md", agent: "codex", dest: agentsLocalFile},
		{name: "cursor rule with marker", agent: "cursor", dest: ".cursor/rules/style.mdc", content: generatedRuleMarker},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, repoRoot := skillEnv(t)
			source := filepath.Join(t.TempDir(), "onyx-infra")
			skillWriteSource(t, source)
			target := filepath.Join(t.TempDir(), "target")
			if c.content != "" {
				deployWriteFile(t, target, c.content)
			}
			link := filepath.Join(repoRoot, filepath.FromSlash(c.dest))
			if err := os.MkdirAll(filepath.Dir(link), 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(target, link); err != nil {
				t.Fatal(err)
			}

			if _, err := skillRun(t, "--source", source, "--agent", c.agent); err == nil {
				t.Fatal("expected install-skill to refuse the symlinked destination")
			}

			got, err := os.ReadFile(target)
			switch {
			case c.content == "" && !os.IsNotExist(err):
				t.Fatalf("dangling link target was created: %v", err)
			case c.content != "" && string(got) != c.content:
				t.Fatalf("link target was overwritten: %q", got)
			}
		})
	}
}
