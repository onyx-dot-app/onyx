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

func TestInstallSkillCmd_RefusesSymlinkedDestinations(t *testing.T) {
	cases := []struct {
		name  string
		args  []string
		plant func(t *testing.T, base, target string)
	}{
		{
			name: "canonical link to an existing file",
			plant: func(t *testing.T, base, target string) {
				writeTestFile(t, target, "original")
				linkTestFile(t, target, filepath.Join(base, ".agents", "skills", "onyx-cli", "SKILL.md"))
			},
		},
		{
			name: "dangling canonical link",
			plant: func(t *testing.T, base, target string) {
				linkTestFile(t, target, filepath.Join(base, ".agents", "skills", "onyx-cli", "SKILL.md"))
			},
		},
		{
			name: "link inside a real agent dir",
			plant: func(t *testing.T, base, target string) {
				writeTestFile(t, target, "original")
				linkTestFile(t, target, filepath.Join(base, ".claude", "skills", "onyx-cli", "SKILL.md"))
			},
		},
		{
			name: "link inside a real agent dir with --copy",
			args: []string{"--copy"},
			plant: func(t *testing.T, base, target string) {
				writeTestFile(t, target, "original")
				linkTestFile(t, target, filepath.Join(base, ".claude", "skills", "onyx-cli", "SKILL.md"))
			},
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			base := t.TempDir()
			t.Chdir(base)
			target := filepath.Join(t.TempDir(), "target")
			c.plant(t, base, target)

			ios, _, _ := testutil.TestIOStreams()
			cmd := newInstallSkillCmd(ios)
			cmd.SilenceErrors = true
			cmd.SilenceUsage = true
			cmd.SetArgs(c.args)
			if err := cmd.Execute(); err == nil {
				t.Fatal("expected install-skill to refuse the symlinked destination")
			}

			got, err := os.ReadFile(target)
			if err == nil && string(got) != "original" {
				t.Fatalf("link target was overwritten: %q", got)
			}
		})
	}
}

func TestInstallSkillCmd_CommittedAgentDirLink(t *testing.T) {
	for _, args := range [][]string{nil, {"--copy"}} {
		t.Run(strings.Join(append([]string{"args"}, args...), " "), func(t *testing.T) {
			testCommittedAgentDirLink(t, args)
		})
	}
}

func testCommittedAgentDirLink(t *testing.T, args []string) {
	// The Onyx repo commits .claude/skills -> ../.agents/skills.
	base := t.TempDir()
	t.Chdir(base)
	if err := os.MkdirAll(filepath.Join(base, ".agents", "skills"), 0o755); err != nil {
		t.Fatal(err)
	}
	linkTestFile(t, filepath.Join("..", ".agents", "skills"), filepath.Join(base, ".claude", "skills"))

	ios, out, _ := testutil.TestIOStreams()
	cmd := newInstallSkillCmd(ios)
	cmd.SilenceErrors = true
	cmd.SilenceUsage = true
	cmd.SetArgs(args)
	if err := cmd.Execute(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !strings.Contains(out.String(), "Up to date "+filepath.Join(base, ".claude", "skills", "onyx-cli")) {
		t.Errorf("expected the linked agent dir reported up to date, got: %s", out.String())
	}
}

func writeTestFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func linkTestFile(t *testing.T, target, link string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(link), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
}

func TestInstallSkillCmd_RefusesAgentDirLinkedOutside(t *testing.T) {
	for _, args := range [][]string{nil, {"--copy"}} {
		t.Run(strings.Join(append([]string{"args"}, args...), " "), func(t *testing.T) {
			base := t.TempDir()
			t.Chdir(base)
			outside := t.TempDir()
			// An existing entry there that a link step would remove.
			victim := filepath.Join(outside, "skills", "onyx-cli")
			writeTestFileMkdir(t, victim, "original")
			linkTestFile(t, outside, filepath.Join(base, ".claude"))

			ios, _, _ := testutil.TestIOStreams()
			cmd := newInstallSkillCmd(ios)
			cmd.SilenceErrors = true
			cmd.SilenceUsage = true
			cmd.SetArgs(args)
			if err := cmd.Execute(); err == nil {
				t.Fatal("expected a .claude link outside the project to be refused")
			}

			info, err := os.Lstat(victim)
			if err != nil || !info.Mode().IsRegular() {
				t.Fatalf("entry outside the project was changed: %v", err)
			}
		})
	}
}

func writeTestFileMkdir(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	writeTestFile(t, path, content)
}

func TestInstallSkillCmd_CopyReplacesEarlierLink(t *testing.T) {
	base := t.TempDir()
	t.Chdir(base)
	for _, args := range [][]string{nil, {"--copy"}} {
		ios, _, _ := testutil.TestIOStreams()
		cmd := newInstallSkillCmd(ios)
		cmd.SilenceErrors = true
		cmd.SilenceUsage = true
		cmd.SetArgs(args)
		if err := cmd.Execute(); err != nil {
			t.Fatalf("install-skill %v: %v", args, err)
		}
	}
	info, err := os.Lstat(filepath.Join(base, ".claude", "skills", "onyx-cli"))
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		t.Fatalf("expected --copy to replace the earlier link with a real directory: %v %v", info, err)
	}
}
