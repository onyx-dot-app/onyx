package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/spf13/cobra"
)

const (
	defaultSkillSource = ".claude/skills/onyx-llm-context"
	claudeSkillsDir    = ".claude/skills"
	claudeMDFile       = ".claude/CLAUDE.md"
	llmContextCloneURL = "https://github.com/onyx-dot-app/onyx-llm-context.git"
)


func NewInstallSkillCommand() *cobra.Command {
	var (
		source    string
		copyMode  bool
		cloneRepo bool
	)

	cmd := &cobra.Command{
		Use:   "install-skill",
		Short: "Install onyx-llm-context skills for Claude Code",
		Long: `Install skills from onyx-llm-context into Claude Code.

Enforced skills (enforced/) are added as @imports in .claude/CLAUDE.md (project-scoped, git-ignored).
Manual skills (skills/) are symlinked into ~/.claude/skills/ and invoked via /skill-name.

By default, looks for onyx-llm-context at ~/.claude/skills/onyx-llm-context.`,
		Example: `  ods install-skill --clone
  ods install-skill --source /path/to/onyx-llm-context
  ods install-skill --copy`,
		RunE: func(cmd *cobra.Command, args []string) error {
			if source == "" {
				home, err := os.UserHomeDir()
				if err != nil {
					return fmt.Errorf("could not determine home directory: %w", err)
				}
				source = filepath.Join(home, defaultSkillSource)
			}

			if _, err := os.Stat(source); os.IsNotExist(err) {
				if !cloneRepo {
					return fmt.Errorf("onyx-llm-context not found at %s\n  Re-run with --clone to fetch it automatically", source)
				}
				_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Cloning %s → %s\n", llmContextCloneURL, source)
				gitCmd := exec.Command("git", "clone", llmContextCloneURL, source)
				gitCmd.Stdout = cmd.OutOrStdout()
				gitCmd.Stderr = cmd.ErrOrStderr()
				if err := gitCmd.Run(); err != nil {
					return fmt.Errorf("git clone failed: %w", err)
				}
			}

			repoRoot, err := paths.GitRoot()
			if err != nil {
				return err
			}
			if err := installEnforcedSkills(cmd, source, repoRoot); err != nil {
				return err
			}
			if err := installManualSkills(cmd, source, copyMode); err != nil {
				return err
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&source, "source", "", "Path to onyx-llm-context (default: ~/.claude/skills/onyx-llm-context)")
	cmd.Flags().BoolVar(&copyMode, "copy", false, "Copy files instead of symlinking")
	cmd.Flags().BoolVar(&cloneRepo, "clone", false, fmt.Sprintf("Clone onyx-llm-context from %s if not already present", llmContextCloneURL))

	return cmd
}

// installEnforcedSkills writes @imports for all enforced/ skills into .claude/CLAUDE.md at the repo root.
func installEnforcedSkills(cmd *cobra.Command, source, repoRoot string) error {
	enforcedDir := filepath.Join(source, "enforced")
	entries, err := os.ReadDir(enforcedDir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("could not read %s: %w", enforcedDir, err)
	}

	var imports []string
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		skillFile := filepath.Join(enforcedDir, entry.Name(), "SKILL.md")
		if _, err := os.Stat(skillFile); os.IsNotExist(err) {
			continue
		}
		imports = append(imports, fmt.Sprintf("@%s", skillFile))
	}

	if len(imports) == 0 {
		return nil
	}

	claudeDir := filepath.Join(repoRoot, ".claude")
	destFile := filepath.Join(repoRoot, claudeMDFile)

	if err := os.MkdirAll(claudeDir, 0o755); err != nil {
		return fmt.Errorf("could not create .claude directory: %w", err)
	}

	content := strings.Join(imports, "\n") + "\n"
	existing, err := os.ReadFile(destFile)
	if err == nil && string(existing) == content {
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Up to date %s\n", destFile)
		return nil
	}

	if err := os.WriteFile(destFile, []byte(content), 0o644); err != nil {
		return fmt.Errorf("could not write %s: %w", destFile, err)
	}
	_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Installed %s\n", destFile)
	return nil
}

// installManualSkills symlinks each skills/ subdirectory into ~/.claude/skills/.
func installManualSkills(cmd *cobra.Command, source string, copyMode bool) error {
	skillsDir := filepath.Join(source, "skills")
	entries, err := os.ReadDir(skillsDir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("could not read %s: %w", skillsDir, err)
	}

	home, err := os.UserHomeDir()
	if err != nil {
		return fmt.Errorf("could not determine home directory: %w", err)
	}

	claudeSkills := filepath.Join(home, claudeSkillsDir)
	if err := os.MkdirAll(claudeSkills, 0o755); err != nil {
		return fmt.Errorf("could not create %s: %w", claudeSkills, err)
	}

	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}

		srcDir := filepath.Join(skillsDir, entry.Name())
		dstDir := filepath.Join(claudeSkills, entry.Name())

		if copyMode {
			if err := copySkill(srcDir, dstDir); err != nil {
				return fmt.Errorf("could not copy %s: %w", entry.Name(), err)
			}
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Copied  %s\n", dstDir)
			continue
		}

		if fi, err := os.Lstat(dstDir); err == nil {
			if fi.Mode()&os.ModeSymlink != 0 {
				_ = os.Remove(dstDir)
			} else if err := os.RemoveAll(dstDir); err != nil {
				return fmt.Errorf("could not remove existing %s: %w", dstDir, err)
			}
		}
		rel, err := filepath.Rel(claudeSkills, srcDir)
		if err != nil {
			return fmt.Errorf("could not compute relative path for %s: %w", entry.Name(), err)
		}

		if err := os.Symlink(rel, dstDir); err != nil {
			if copyErr := copySkill(srcDir, dstDir); copyErr != nil {
				return fmt.Errorf("could not install %s: %w", entry.Name(), copyErr)
			}
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Copied  %s (symlink failed)\n", dstDir)
			continue
		}
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Linked  %s -> %s\n", dstDir, rel)
	}

	return nil
}

func copySkill(srcDir, dstDir string) error {
	return filepath.WalkDir(srcDir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(srcDir, path)
		dst := filepath.Join(dstDir, rel)
		if d.IsDir() {
			return os.MkdirAll(dst, 0o755)
		}
		content, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(dst, content, 0o644)
	})
}
