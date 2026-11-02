package cmd

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

func TestInstallSkill_regularScriptsFileIsALegacySource(t *testing.T) {
	_, repoRoot := skillEnv(t)
	source := t.TempDir()
	skillWriteSource(t, source)
	deployWriteFile(t, filepath.Join(source, "scripts"), "legacy helper")

	if _, err := skillRun(t, "--source", source, "--no-pull"); err != nil {
		t.Fatalf("legacy source: %v", err)
	}
	if got := skillReadFile(t, filepath.Join(repoRoot, projectSkillsDir, "review", "SKILL.md")); got != "review" {
		t.Fatalf("expected the legacy skill, got %q", got)
	}
}

func TestInstallSkill_nestedSourceChecksOwningCheckout(t *testing.T) {
	for _, removed := range []bool{false, true} {
		name := "untracked"
		if removed {
			name = "tracked-but-removed"
		}
		t.Run(name, func(t *testing.T) {
			_, repoRoot := skillEnv(t)
			checkout := t.TempDir()
			gittest.Git(t, checkout, "init", "--quiet")
			source := filepath.Join(checkout, agentContextDir)
			skillWriteSource(t, source)
			setup := filepath.Join(checkout, "scripts", "setup_agents.py")
			deployWriteFile(t, setup, "# workspace setup\n")
			if removed {
				gittest.Git(t, checkout, "add", "-A")
				if err := os.Remove(setup); err != nil {
					t.Fatal(err)
				}
			}
			before := skillTreeContents(t, repoRoot)

			_, err := skillRun(t, "--source", source, "--no-pull", "--agent", "claude-code,codex,cursor")
			if err == nil || !strings.Contains(err.Error(), "workspace setup") || !strings.Contains(err.Error(), setup) {
				t.Fatalf("expected setup instruction for the checkout, got %v", err)
			}
			if !reflect.DeepEqual(before, skillTreeContents(t, repoRoot)) {
				t.Fatal("changed integrations for a workspace source")
			}
		})
	}
}

func TestInstallSkill_sparseCloneChecksSetupOutsideSparsePaths(t *testing.T) {
	home, repoRoot := skillEnv(t)
	remote := t.TempDir()
	gittest.Git(t, remote, "init", "--quiet", "-b", "main")
	skillWriteSource(t, filepath.Join(remote, agentContextDir))
	deployWriteFile(t, filepath.Join(remote, "scripts", "setup_agents.py"), "# workspace setup\n")
	gittest.Git(t, remote, "add", "-A")
	gittest.Git(t, remote, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "workspace source")
	t.Setenv("ODS_TEST_SKILL_REMOTE", remote)
	skillFakeGit(t,
		"  exec \"$ODS_TEST_REAL_GIT\" clone --depth 1 --filter=blob:none --sparse \"file://$ODS_TEST_SKILL_REMOTE\" \"$dest\"\n",
		"",
	)
	before := skillTreeContents(t, repoRoot)

	_, err := skillRun(t, "--clone", "--agent", "claude-code,codex,cursor")
	if err == nil || !strings.Contains(err.Error(), "workspace setup") {
		t.Fatalf("expected setup instruction for the sparse source, got %v", err)
	}
	source := filepath.Join(home, defaultSkillSource)
	if _, err := os.Stat(filepath.Join(source, "scripts")); !os.IsNotExist(err) {
		t.Fatalf("setup inspection must not expand the sparse checkout: %v", err)
	}
	if !reflect.DeepEqual(before, skillTreeContents(t, repoRoot)) {
		t.Fatal("sparse workspace source changed integrations")
	}
}

func TestInstallSkill_workspaceMigrationPreservesExistingTargets(t *testing.T) {
	for _, scenario := range []struct {
		name    string
		current bool
		nested  bool
	}{
		{name: "current-root", current: true},
		{name: "incoming-root"},
		{name: "incoming-nested", nested: true},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			home, repoRoot := skillEnv(t)
			remote := t.TempDir()
			gittest.Git(t, remote, "init", "--quiet", "-b", "main")
			skillWriteSource(t, filepath.Join(remote, agentContextDir))
			gittest.Git(t, remote, "add", "-A")
			gittest.Git(t, remote, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "legacy skills")
			source := filepath.Join(t.TempDir(), "source")
			gittest.Git(t, t.TempDir(), "clone", "-q", remote, source)
			if _, err := skillRun(t, "--source", source, "--no-pull", "--agent", "claude-code,codex,cursor"); err != nil {
				t.Fatal(err)
			}
			beforeHead := gittest.Git(t, source, "rev-parse", "HEAD")
			beforeRepo := skillTreeContents(t, repoRoot)
			beforeHome := skillTreeContents(t, home)
			if err := os.RemoveAll(filepath.Join(remote, agentContextDir)); err != nil {
				t.Fatal(err)
			}
			setupRoot := remote
			if scenario.current {
				setupRoot = source
			} else if scenario.nested {
				setupRoot = filepath.Join(remote, agentContextDir)
			}
			deployWriteFile(t, filepath.Join(setupRoot, "scripts", "setup_agents.py"), "# workspace setup\n")
			gittest.Git(t, remote, "add", "-A")
			gittest.Git(t, remote, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "remove legacy skills")

			_, err := skillRun(t, "--source", source, "--agent", "claude-code,codex,cursor")
			if err == nil || !strings.Contains(err.Error(), "workspace setup") {
				t.Fatalf("expected setup instruction before updating the source, got %v", err)
			}
			if got := gittest.Git(t, source, "rev-parse", "HEAD"); got != beforeHead {
				t.Fatalf("changed source HEAD from %s to %s", beforeHead, got)
			}
			if got := skillReadFile(t, filepath.Join(source, agentContextDir, "enforced", "style", "SKILL.md")); got != "style" {
				t.Fatalf("changed existing instruction import target: %q", got)
			}
			if got := skillReadFile(t, filepath.Join(repoRoot, projectSkillsDir, "review", "SKILL.md")); got != "review" {
				t.Fatalf("changed existing linked skill target: %q", got)
			}
			if !reflect.DeepEqual(beforeRepo, skillTreeContents(t, repoRoot)) ||
				!reflect.DeepEqual(beforeHome, skillTreeContents(t, home)) {
				t.Fatal("changed existing integrations or linked skill contents")
			}
		})
	}
}

func TestInstallSkill_brokenSourceIndexIsAnInspectionError(t *testing.T) {
	_, repoRoot := skillEnv(t)
	source := t.TempDir()
	gittest.Git(t, source, "init", "--quiet")
	skillWriteSource(t, source)
	deployWriteFile(t, filepath.Join(source, ".git", "index"), "invalid index")
	before := skillTreeContents(t, repoRoot)

	_, err := skillRun(t, "--source", source, "--no-pull")
	if err == nil || !strings.Contains(err.Error(), "could not inspect source setup entries") {
		t.Fatalf("expected Git metadata inspection failure, got %v", err)
	}
	if !reflect.DeepEqual(before, skillTreeContents(t, repoRoot)) {
		t.Fatal("source inspection failure changed integrations")
	}
}

func TestInstallSkill_pullUsesConfiguredUpstream(t *testing.T) {
	_, repoRoot := skillEnv(t)
	source := pullFixture(t)
	gittest.Git(t, source, "remote", "rename", "origin", "skills")

	if _, err := skillRun(t, "--source", source); err != nil {
		t.Fatalf("configured upstream: %v", err)
	}
	if got := skillReadFile(t, filepath.Join(repoRoot, projectSkillsDir, "fresh", "SKILL.md")); got != "fresh" {
		t.Fatalf("expected the configured upstream skill, got %q", got)
	}
}
