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
	agentCodex      = "codex"
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
	agentCodex: installCodexSkills,
}

func NewInstallSkillCommand() *cobra.Command {
	var (
		source    string
		copyMode  bool
		cloneRepo bool
		noPull    bool
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

codex:
  Enforced skills are compiled into .agents-local.md at the repo root
  (git-excluded; the committed AGENTS.md points agents at it), since Codex
  skills cannot be always-on. Manual skills are symlinked into
  ~/.agents/skills/, Codex's native skill directory, invoked via $skill-name.

The checkout is fast-forwarded before installing, so a plain rerun picks up
new skills; --no-pull installs from the checkout as it is.

By default, looks for onyx-llm-context at ~/.claude/skills/onyx-llm-context.`,
		Example: `  ods install-skill --clone
  ods install-skill --agent cursor
  ods install-skill --agent claude-code --agent cursor --agent codex
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
			} else if !noPull {
				pullSource(cmd, source)
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
	cmd.Flags().BoolVar(&copyMode, "copy", false, "Copy files instead of symlinking (claude-code and codex manual skills)")
	cmd.Flags().BoolVar(&cloneRepo, "clone", false, fmt.Sprintf("Clone onyx-llm-context from %s if not already present", llmContextCloneURL))
	cmd.Flags().BoolVar(&noPull, "no-pull", false, "Install from the checkout as it is, without updating it first")
	cmd.Flags().StringSliceVar(&agents, "agent", []string{agentClaudeCode}, "Agents to install for (repeatable): claude-code, cursor, codex")

	return cmd
}

// pullSource fast-forwards the source checkout so a plain rerun picks up new
// skills without a separate git pull. Local work is never lost: --ff-only
// refuses diverged history, and git itself refuses a pull that would
// overwrite uncommitted changes. Any pull that cannot run (those cases,
// offline, no upstream) warns and installs from the local state, since a
// stale install is better than none. Local edits that do not conflict
// survive the update.
func pullSource(cmd *cobra.Command, source string) {
	// Not a git checkout (an exported copy, say): nothing to update.
	if _, err := os.Stat(filepath.Join(source, ".git")); os.IsNotExist(err) {
		return
	} else if err != nil {
		_, _ = fmt.Fprintf(
			cmd.ErrOrStderr(),
			"Warning: could not inspect %s (%v); installing without updating it.\n",
			source,
			err,
		)
		return
	}
	gitCmd := exec.Command("git", "-C", source, "pull", "--ff-only")
	out, err := gitCmd.CombinedOutput()
	if err != nil {
		_, _ = fmt.Fprintf(
			cmd.ErrOrStderr(),
			"Warning: could not update %s; installing from the local state.\n%s",
			source,
			out,
		)
		return
	}
	summary, _, _ := strings.Cut(strings.TrimSpace(string(out)), "\n")
	_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Pulled  %s (%s)\n", source, summary)
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
	return linkManualSkills(cmd, ui, skills, "Claude skills", claudeSkillsDir, copyMode)
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

// linkManualSkills symlinks each on-demand skill directory into the given
// skills directory under the home directory (~/.claude/skills for Claude,
// ~/.agents/skills for agents that read the universal layout, such as Codex).
func linkManualSkills(
	cmd *cobra.Command, ui *installUI, skills []llmContextSkill,
	kind, homeRelativeDir string, copyMode bool,
) error {
	if len(skills) == 0 {
		return nil
	}
	var manual []llmContextSkill
	for _, skill := range skills {
		if !skill.Enforced {
			manual = append(manual, skill)
		}
	}

	home, err := os.UserHomeDir()
	if err != nil {
		return fmt.Errorf("could not determine home directory: %w", err)
	}

	skillsDir := filepath.Join(home, homeRelativeDir)
	if _, err := os.Stat(skillsDir); os.IsNotExist(err) {
		// Nothing installed here before, so nothing to clean up either.
		if len(manual) == 0 {
			return nil
		}
		if skillsDir, err = ui.resolveTargetDir(kind, skillsDir); err != nil {
			return err
		}
	}

	// Every skill sits at <source>/<tier>/<name>, so any of them names the
	// source checkout that stale links of past installs point into. Cleanup
	// runs even when the manual tier emptied, so its old links go too.
	source := filepath.Dir(filepath.Dir(skills[0].Dir))
	if err := removeStaleSkillLinks(cmd, skillsDir, source, manual); err != nil {
		return err
	}

	for _, skill := range manual {
		srcDir := skill.Dir
		dstDir := filepath.Join(skillsDir, skill.Name)

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
		rel, err := filepath.Rel(skillsDir, srcDir)
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

// removeStaleSkillLinks deletes symlinks in skillsDir that resolve into the
// source checkout but no longer match an on-demand skill — the ownership test
// for a link, since only this command links from there. Hand-written entries,
// links to other places and past --copy installs are left alone.
func removeStaleSkillLinks(
	cmd *cobra.Command, skillsDir, source string, manual []llmContextSkill,
) error {
	current := make(map[string]bool, len(manual))
	for _, skill := range manual {
		current[skill.Name] = true
	}
	entries, err := os.ReadDir(skillsDir)
	if err != nil {
		return fmt.Errorf("could not read %s: %w", skillsDir, err)
	}
	for _, entry := range entries {
		if current[entry.Name()] || entry.Type()&os.ModeSymlink == 0 {
			continue
		}
		path := filepath.Join(skillsDir, entry.Name())
		target, err := os.Readlink(path)
		if err != nil {
			return fmt.Errorf("could not read link %s: %w", path, err)
		}
		if !filepath.IsAbs(target) {
			target = filepath.Join(skillsDir, target)
		}
		rel, err := filepath.Rel(source, filepath.Clean(target))
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			continue
		}
		if err := os.Remove(path); err != nil {
			return fmt.Errorf("could not remove stale skill link %s: %w", path, err)
		}
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Removed %s\n", path)
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
