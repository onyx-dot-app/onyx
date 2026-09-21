package cmd

import (
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/charlievieth/fastwalk"
	"github.com/onyx-dot-app/onyx/tools/ods/internal/paths"
	"github.com/spf13/cobra"
)

const (
	defaultSkillSource = ".claude/skills/onyx-llm-context"
	claudeSkillsDir    = ".claude/skills"
	claudeMDFile       = ".claude/CLAUDE.md"
	llmContextCloneURL = "https://github.com/onyx-dot-app/onyx-llm-context.git"

	agentClaudeCode = "claude-code"
	agentCursor     = "cursor"
)

// knownAgents maps each supported --agent value to its installer. Every
// installer regenerates its output, so reruns update in place.
var knownAgents = map[string]func(
	cmd *cobra.Command, ui *installUI, skills []llmContextSkill, repoRoot string, copyMode bool,
) error{
	agentClaudeCode: installClaudeSkills,
	agentCursor: func(
		cmd *cobra.Command, ui *installUI, skills []llmContextSkill, repoRoot string, _ bool,
	) error {
		return installCursorSkills(cmd, ui, skills, repoRoot)
	},
}

func NewInstallSkillCommand() *cobra.Command {
	var (
		source    string
		copyMode  bool
		cloneRepo bool
		agents    []string
	)

	cmd := &cobra.Command{
		Use:   "install-skill",
		Short: "Install onyx-llm-context skills for your coding agent",
		Long: `Install skills from onyx-llm-context for one or more coding agents.

claude-code (default):
  Enforced skills (enforced/) are added as @imports in .claude/CLAUDE.md
  (project-scoped, git-ignored). Manual skills (skills/) are symlinked into
  ~/.claude/skills/ and invoked via /skill-name.

cursor:
  Every skill is rendered as a rule in .cursor/rules/ (git-ignored).
  Enforced skills apply always; on-demand skills attach when Cursor matches
  their description, or on an explicit @skill-name mention.

By default, looks for onyx-llm-context at ~/.claude/skills/onyx-llm-context.`,
		Example: `  ods install-skill --clone
  ods install-skill --agent cursor
  ods install-skill --agent claude-code --agent cursor
  ods install-skill --source /path/to/onyx-llm-context
  ods install-skill --copy`,
		RunE: func(cmd *cobra.Command, args []string) error {
			installers, err := resolveAgents(agents)
			if err != nil {
				return err
			}

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
			skills, err := discoverLLMContextSkills(source)
			if err != nil {
				return err
			}
			ui := newInstallUI(cmd.OutOrStdout())
			for _, install := range installers {
				if err := install(cmd, ui, skills, repoRoot, copyMode); err != nil {
					return err
				}
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&source, "source", "", "Path to onyx-llm-context (default: ~/.claude/skills/onyx-llm-context)")
	cmd.Flags().BoolVar(&copyMode, "copy", false, "Copy files instead of symlinking (claude-code manual skills only)")
	cmd.Flags().BoolVar(&cloneRepo, "clone", false, fmt.Sprintf("Clone onyx-llm-context from %s if not already present", llmContextCloneURL))
	cmd.Flags().StringSliceVar(&agents, "agent", []string{agentClaudeCode}, "Agents to install for (repeatable): claude-code, cursor")

	return cmd
}

// resolveAgents maps the --agent values to installers, in the given order and
// deduplicated. An unknown agent is an error rather than a skip, so a typo
// never reads as a successful install.
func resolveAgents(agents []string) (
	[]func(*cobra.Command, *installUI, []llmContextSkill, string, bool) error, error,
) {
	var installers []func(*cobra.Command, *installUI, []llmContextSkill, string, bool) error
	seen := make(map[string]bool, len(agents))
	for _, agent := range agents {
		if seen[agent] {
			continue
		}
		seen[agent] = true
		install, ok := knownAgents[agent]
		if !ok {
			known := make([]string, 0, len(knownAgents))
			for name := range knownAgents {
				known = append(known, name)
			}
			return nil, fmt.Errorf(
				"unknown agent %q; known agents: %s", agent, strings.Join(known, ", "),
			)
		}
		installers = append(installers, install)
	}
	return installers, nil
}

func installClaudeSkills(
	cmd *cobra.Command, ui *installUI, skills []llmContextSkill, repoRoot string, copyMode bool,
) error {
	if err := installEnforcedSkills(cmd, skills, repoRoot); err != nil {
		return err
	}
	return installManualSkills(cmd, ui, skills, copyMode)
}

// installEnforcedSkills writes @imports for all enforced skills into .claude/CLAUDE.md at the repo root.
func installEnforcedSkills(
	cmd *cobra.Command, skills []llmContextSkill, repoRoot string,
) error {
	var imports []string
	for _, skill := range skills {
		if skill.Enforced {
			imports = append(imports, fmt.Sprintf("@%s", skill.File))
		}
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

// installManualSkills symlinks each on-demand skill directory into ~/.claude/skills/.
func installManualSkills(
	cmd *cobra.Command, ui *installUI, skills []llmContextSkill, copyMode bool,
) error {
	var manual []llmContextSkill
	for _, skill := range skills {
		if !skill.Enforced {
			manual = append(manual, skill)
		}
	}
	if len(manual) == 0 {
		return nil
	}

	home, err := os.UserHomeDir()
	if err != nil {
		return fmt.Errorf("could not determine home directory: %w", err)
	}

	claudeSkills, err := ui.resolveTargetDir(
		"Claude skills", filepath.Join(home, claudeSkillsDir),
	)
	if err != nil {
		return err
	}

	for _, skill := range manual {
		srcDir := skill.Dir
		dstDir := filepath.Join(claudeSkills, skill.Name)

		if copyMode {
			if err := copySkill(srcDir, dstDir); err != nil {
				return fmt.Errorf("could not copy %s: %w", skill.Name, err)
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
			return fmt.Errorf("could not compute relative path for %s: %w", skill.Name, err)
		}

		if err := os.Symlink(rel, dstDir); err != nil {
			if copyErr := copySkill(srcDir, dstDir); copyErr != nil {
				return fmt.Errorf("could not install %s: %w", skill.Name, copyErr)
			}
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Copied  %s (symlink failed)\n", dstDir)
			continue
		}
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Linked  %s -> %s\n", dstDir, rel)
	}

	return nil
}

func copySkill(srcDir, dstDir string) error {
	// fastwalk visits a directory before its children, so each destination
	// directory exists by the time its entries are copied.
	return fastwalk.Walk(nil, srcDir, func(path string, d fs.DirEntry, err error) error {
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
