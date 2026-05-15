package cmd

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/embedded"
	"github.com/onyx-dot-app/onyx/cli/internal/testutil"
)

func TestInstallSkillCmd_BasicInstall(t *testing.T) {
	tmpDir := t.TempDir()

	origDir, err := os.Getwd()
	if err != nil {
		t.Fatalf("failed to get working directory: %v", err)
	}
	if err := os.Chdir(tmpDir); err != nil {
		t.Fatalf("failed to chdir: %v", err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(origDir); err != nil {
			t.Logf("warning: failed to restore working directory: %v", err)
		}
	})

	ios, out, _ := testutil.TestIOStreams()
	cmd := newInstallSkillCmd(ios)
	cmd.SilenceErrors = true
	cmd.SilenceUsage = true
	if err := cmd.Execute(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	canonicalPath := filepath.Join(tmpDir, ".agents", "skills", "onyx-cli", "SKILL.md")
	content, err := os.ReadFile(canonicalPath)
	if err != nil {
		t.Fatalf("expected canonical file at %s, got error: %v", canonicalPath, err)
	}
	if string(content) != embedded.SkillMD {
		t.Fatalf("canonical file content does not match embedded SKILL.md")
	}

	output := out.String()
	if !strings.Contains(output, "Installed") {
		t.Errorf("expected 'Installed' in output, got: %s", output)
	}
}

func TestInstallSkillCmd_GlobalInstall(t *testing.T) {
	tmpHome := t.TempDir()
	t.Setenv("HOME", tmpHome)

	ios, out, _ := testutil.TestIOStreams()
	cmd := newInstallSkillCmd(ios)
	cmd.SetArgs([]string{"--global"})
	cmd.SilenceErrors = true
	cmd.SilenceUsage = true
	if err := cmd.Execute(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	canonicalPath := filepath.Join(tmpHome, ".agents", "skills", "onyx-cli", "SKILL.md")
	content, err := os.ReadFile(canonicalPath)
	if err != nil {
		t.Fatalf("expected canonical file at %s, got error: %v", canonicalPath, err)
	}
	if string(content) != embedded.SkillMD {
		t.Fatalf("canonical file content does not match embedded SKILL.md")
	}

	output := out.String()
	if !strings.Contains(output, "Installed") {
		t.Errorf("expected 'Installed' in output, got: %s", output)
	}
}

func TestInstallSkillCmd_UpToDate(t *testing.T) {
	tmpDir := t.TempDir()

	origDir, err := os.Getwd()
	if err != nil {
		t.Fatalf("failed to get working directory: %v", err)
	}
	if err := os.Chdir(tmpDir); err != nil {
		t.Fatalf("failed to chdir: %v", err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(origDir); err != nil {
			t.Logf("warning: failed to restore working directory: %v", err)
		}
	})

	// First install.
	ios1, _, _ := testutil.TestIOStreams()
	cmd1 := newInstallSkillCmd(ios1)
	cmd1.SilenceErrors = true
	cmd1.SilenceUsage = true
	if err := cmd1.Execute(); err != nil {
		t.Fatalf("first install failed: %v", err)
	}

	// Second install should report "Up to date".
	ios2, out2, _ := testutil.TestIOStreams()
	cmd2 := newInstallSkillCmd(ios2)
	cmd2.SilenceErrors = true
	cmd2.SilenceUsage = true
	if err := cmd2.Execute(); err != nil {
		t.Fatalf("second install failed: %v", err)
	}

	output := out2.String()
	if !strings.Contains(output, "Up to date") {
		t.Errorf("expected 'Up to date' in output, got: %s", output)
	}
}

func TestInstallSkillCmd_CopyMode(t *testing.T) {
	tmpDir := t.TempDir()

	origDir, err := os.Getwd()
	if err != nil {
		t.Fatalf("failed to get working directory: %v", err)
	}
	if err := os.Chdir(tmpDir); err != nil {
		t.Fatalf("failed to chdir: %v", err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(origDir); err != nil {
			t.Logf("warning: failed to restore working directory: %v", err)
		}
	})

	ios, out, _ := testutil.TestIOStreams()
	cmd := newInstallSkillCmd(ios)
	cmd.SetArgs([]string{"--copy"})
	cmd.SilenceErrors = true
	cmd.SilenceUsage = true
	if err := cmd.Execute(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify canonical copy exists.
	canonicalPath := filepath.Join(tmpDir, ".agents", "skills", "onyx-cli", "SKILL.md")
	content, err := os.ReadFile(canonicalPath)
	if err != nil {
		t.Fatalf("expected canonical file at %s, got error: %v", canonicalPath, err)
	}
	if string(content) != embedded.SkillMD {
		t.Fatalf("canonical file content does not match embedded SKILL.md")
	}

	// Verify claude-code agent copy exists and is a real file, not a symlink.
	claudePath := filepath.Join(tmpDir, ".claude", "skills", "onyx-cli", "SKILL.md")
	info, err := os.Lstat(claudePath)
	if err != nil {
		t.Fatalf("expected claude-code copy at %s, got error: %v", claudePath, err)
	}
	if info.Mode()&os.ModeSymlink != 0 {
		t.Fatalf("expected regular file for --copy mode, got symlink at %s", claudePath)
	}
	claudeContent, err := os.ReadFile(claudePath)
	if err != nil {
		t.Fatalf("failed to read claude-code copy: %v", err)
	}
	if string(claudeContent) != embedded.SkillMD {
		t.Fatalf("claude-code copy content does not match embedded SKILL.md")
	}

	output := out.String()
	if !strings.Contains(output, "Copied") {
		t.Errorf("expected 'Copied' in output, got: %s", output)
	}
}
