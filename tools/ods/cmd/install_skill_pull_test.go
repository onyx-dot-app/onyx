package cmd

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/gittest"
)

// pullFixture builds a "remote" skills repo and a clone of it to install
// from, then lands one more skill on the remote only. Returns the clone.
func pullFixture(t *testing.T) (clone string) {
	t.Helper()
	remote := t.TempDir()
	gittest.Git(t, remote, "init", "--quiet", "-b", "main")
	deployWriteFile(t, filepath.Join(remote, "skills", "review", "SKILL.md"), "review")
	gittest.Git(t, remote, "add", "-A")
	gittest.Git(t, remote, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one skill")

	clone = filepath.Join(t.TempDir(), "onyx-llm-context")
	gittest.Git(t, t.TempDir(), "clone", "-q", remote, clone)

	deployWriteFile(t, filepath.Join(remote, "skills", "fresh", "SKILL.md"), "fresh")
	gittest.Git(t, remote, "add", "-A")
	gittest.Git(t, remote, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "another skill")
	return clone
}

func TestInstallSkill_pullsTheSourceByDefault(t *testing.T) {
	home, _ := skillEnv(t)
	clone := pullFixture(t)

	out, err := skillRun(t, "--source", clone)
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	if !strings.Contains(out, "Pulled  "+clone) {
		t.Fatalf("expected a pull line, got %q", out)
	}
	// The skill that only existed on the remote was installed.
	if _, err := os.Readlink(filepath.Join(home, ".claude", "skills", "fresh")); err != nil {
		t.Fatalf("expected the pulled skill to be installed: %v", err)
	}
}

func TestInstallSkill_noPullInstallsTheCheckoutAsItIs(t *testing.T) {
	home, _ := skillEnv(t)
	clone := pullFixture(t)

	out, err := skillRun(t, "--source", clone, "--no-pull")
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	if strings.Contains(out, "Pulled  ") {
		t.Fatalf("expected no pull, got %q", out)
	}
	if _, err := os.Lstat(filepath.Join(home, ".claude", "skills", "fresh")); !os.IsNotExist(err) {
		t.Fatalf("the remote-only skill must not be installed: %v", err)
	}
	if _, err := os.Readlink(filepath.Join(home, ".claude", "skills", "review")); err != nil {
		t.Fatalf("the local skill should still be installed: %v", err)
	}
}

func TestInstallSkill_failedPullWarnsAndInstallsTheLocalState(t *testing.T) {
	skillEnv(t)
	clone := pullFixture(t)
	// A local commit diverges the clone, so --ff-only cannot resolve it.
	deployWriteFile(t, filepath.Join(clone, "skills", "review", "SKILL.md"), "local edit")
	gittest.Git(t, clone, "add", "-A")
	gittest.Git(t, clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "local divergence")

	out, err := skillRun(t, "--source", clone)
	if err != nil {
		t.Fatalf("a failed pull must not fail the install: %v", err)
	}

	if !strings.Contains(out, "Warning: could not update "+clone) {
		t.Fatalf("expected a warning, got %q", out)
	}
	if !strings.Contains(out, "Linked") {
		t.Fatalf("expected the install to continue, got %q", out)
	}
}

func TestInstallSkill_plainDirectorySourceInstallsWithoutUpdateNoise(t *testing.T) {
	skillEnv(t)
	source := filepath.Join(t.TempDir(), "onyx-llm-context")
	skillWriteSource(t, source)

	out, err := skillRun(t, "--source", source)
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}
	// "Pulled  " and "Warning:" are the update lines; a bare "Pulled" would
	// also match temp paths carrying the test name.
	if strings.Contains(out, "Pulled  ") || strings.Contains(out, "Warning:") {
		t.Fatalf("a plain directory must install without update noise, got %q", out)
	}
}
