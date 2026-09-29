package cmd

import (
	"bytes"
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

// skillWriteSource creates an onyx-llm-context checkout with one enforced
// skill, one enforced directory without a SKILL.md, and one manual skill with
// a nested file.
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
	home, repoRoot := skillEnv(t)
	source := filepath.Join(t.TempDir(), "onyx-llm-context")
	skillWriteSource(t, source)
	// A stale copy from an earlier --copy install must be replaced by a link.
	deployWriteFile(t, filepath.Join(home, ".claude", "skills", "review", "stale.md"), "stale")

	out, err := skillRun(t, "--source", source)
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	claudeMD := filepath.Join(repoRoot, ".claude", "CLAUDE.md")
	wantImports := "@" + filepath.Join(source, "enforced", "style", "SKILL.md") + "\n"
	if got := skillReadFile(t, claudeMD); got != wantImports {
		t.Fatalf("expected CLAUDE.md %q, got %q", wantImports, got)
	}
	link := filepath.Join(home, ".claude", "skills", "review")
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
	if _, err := os.Lstat(filepath.Join(home, ".claude", "skills", "README.md")); !os.IsNotExist(err) {
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

func TestInstallSkill_copyModeCopiesSkillTrees(t *testing.T) {
	home, _ := skillEnv(t)
	source := filepath.Join(t.TempDir(), "onyx-llm-context")
	skillWriteSource(t, source)

	out, err := skillRun(t, "--source", source, "--copy")
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	dst := filepath.Join(home, ".claude", "skills", "review")
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

func TestInstallSkill_missingSourceRequiresClone(t *testing.T) {
	home, _ := skillEnv(t)

	_, err := skillRun(t)

	wantSource := filepath.Join(home, ".claude", "skills", "onyx-llm-context")
	if err == nil || !strings.Contains(err.Error(), "onyx-llm-context not found at "+wantSource) || !strings.Contains(err.Error(), "--clone") {
		t.Fatalf("expected a hint to use --clone for %s, got %v", wantSource, err)
	}
}

// skillFakeGit puts a git wrapper first on PATH that records clone calls and
// runs script for them; every other git call goes to the real git.
func skillFakeGit(t *testing.T, cloneScript string) string {
	t.Helper()
	realGit, err := exec.LookPath("git")
	if err != nil {
		t.Skip("git is not installed")
	}
	dir := t.TempDir()
	record := filepath.Join(dir, "clone-args")
	t.Setenv("ODS_TEST_REAL_GIT", realGit)
	script := "#!/bin/sh\n" +
		"if [ \"$1\" = clone ]; then\n" +
		"  printf '%s\\n' \"$@\" > \"${0%/*}/clone-args\"\n" +
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

func TestInstallSkill_cloneFetchesTheDefaultSource(t *testing.T) {
	home, _ := skillEnv(t)
	record := skillFakeGit(t, "  mkdir -p \"$3/skills/review\" && echo review > \"$3/skills/review/SKILL.md\"\n  exit 0\n")

	out, err := skillRun(t, "--clone")
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	source := filepath.Join(home, ".claude", "skills", "onyx-llm-context")
	wantArgs := "clone\n" + llmContextCloneURL + "\n" + source + "\n"
	if got := skillReadFile(t, record); got != wantArgs {
		t.Fatalf("expected git args %q, got %q", wantArgs, got)
	}
	if got := skillReadFile(t, filepath.Join(home, ".claude", "skills", "review", "SKILL.md")); got != "review\n" {
		t.Fatalf("expected the cloned skill to be installed, got %q", got)
	}
	if !strings.Contains(out, "Cloning "+llmContextCloneURL+" → "+source) {
		t.Fatalf("expected clone output, got %q", out)
	}
}

func TestInstallSkill_cloneFailureStopsTheInstall(t *testing.T) {
	home, _ := skillEnv(t)
	skillFakeGit(t, "  echo 'fatal: unable to access' >&2\n  exit 128\n")

	out, err := skillRun(t, "--clone")

	if err == nil || !strings.Contains(err.Error(), "git clone failed") {
		t.Fatalf("expected clone failure, got %v", err)
	}
	if !strings.Contains(out, "fatal: unable to access") {
		t.Fatalf("expected git's error output to be forwarded, got %q", out)
	}
	if _, err := os.Stat(filepath.Join(home, ".claude", "skills")); !os.IsNotExist(err) {
		t.Fatalf("expected nothing installed, got %v", err)
	}
}
