package cmd

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/onyx-dot-app/onyx/cli/internal/embedded"
	"github.com/onyx-dot-app/onyx/cli/internal/fsutil"
	"github.com/spf13/cobra"
)

// agentSkillDirs maps agent names to their skill directory paths (relative to
// the project or home root). "Universal" agents like Cursor and Codex read
// from .agents/skills directly, so they don't need their own entry here.
var agentSkillDirs = map[string]string{
	"claude-code": filepath.Join(".claude", "skills"),
}

const (
	canonicalDir = ".agents/skills"
	skillName    = "onyx-cli"
)

func newInstallSkillCmd() *cobra.Command {
	var (
		global    bool
		copyMode  bool
		agents    []string
	)

	cmd := &cobra.Command{
		Use:   "install-skill",
		Short: "Install the Onyx CLI agent skill file",
		Long: `Install the bundled SKILL.md so that AI coding agents can discover and use
the Onyx CLI as a tool.

Files are written to the canonical .agents/skills/onyx-cli/ directory. For
agents that use their own skill directory (e.g. Claude Code uses .claude/skills/),
a symlink is created pointing back to the canonical copy.

By default the skill is installed at the project level (current directory).
Use --global to install under your home directory instead.

Use --copy to write independent copies instead of symlinks.
Use --agent to target specific agents (can be repeated).`,
		Example: `  onyx-cli install-skill
  onyx-cli install-skill --global
  onyx-cli install-skill --agent claude-code
  onyx-cli install-skill --copy`,
		RunE: func(cmd *cobra.Command, args []string) error {
			base, err := installBase(global)
			if err != nil {
				return err
			}

			// Write the canonical copy.
			canonicalSkillDir := filepath.Join(base, canonicalDir, skillName)
			dest := filepath.Join(canonicalSkillDir, "SKILL.md")
			content := []byte(embedded.SkillMD)

			status, err := fsutil.CompareFile(dest, content)
			if err != nil {
				return err
			}
			switch status {
			case fsutil.StatusUpToDate:
				_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Up to date %s\n", dest)
			case fsutil.StatusDiffers:
				_, _ = fmt.Fprintf(cmd.ErrOrStderr(), "Warning: overwriting modified %s\n", dest)
				if err := os.WriteFile(dest, content, 0o644); err != nil {
					return fmt.Errorf("could not write skill file: %w", err)
				}
				_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Installed %s\n", dest)
			default: // statusMissing
				if err := os.MkdirAll(canonicalSkillDir, 0o755); err != nil {
					return fmt.Errorf("could not create directory: %w", err)
				}
				if err := os.WriteFile(dest, content, 0o644); err != nil {
					return fmt.Errorf("could not write skill file: %w", err)
				}
				_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Installed %s\n", dest)
			}

			// Determine which agents to link.
			targets := agentSkillDirs
			if len(agents) > 0 {
				targets = make(map[string]string)
				for _, a := range agents {
					dir, ok := agentSkillDirs[a]
					if !ok {
						_, _ = fmt.Fprintf(cmd.ErrOrStderr(), "Unknown agent %q (skipped) — known agents:", a)
						for name := range agentSkillDirs {
							_, _ = fmt.Fprintf(cmd.ErrOrStderr(), " %s", name)
						}
						_, _ = fmt.Fprintln(cmd.ErrOrStderr())
						continue
					}
					targets[a] = dir
				}
			}

			// Create symlinks (or copies) from agent-specific dirs to canonical.
			for name, skillsDir := range targets {
				agentSkillDir := filepath.Join(base, skillsDir, skillName)

				if copyMode {
					copyDest := filepath.Join(agentSkillDir, "SKILL.md")
					if err := fsutil.EnsureDirForCopy(agentSkillDir); err != nil {
						return fmt.Errorf("could not prepare %s directory: %w", name, err)
					}
					if err := os.MkdirAll(agentSkillDir, 0o755); err != nil {
						return fmt.Errorf("could not create %s directory: %w", name, err)
					}
					if err := os.WriteFile(copyDest, []byte(embedded.SkillMD), 0o644); err != nil {
						return fmt.Errorf("could not write %s skill file: %w", name, err)
					}
					_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Copied  %s\n", copyDest)
					continue
				}

				// Compute relative symlink target. Symlinks resolve relative to
				// the parent directory of the link, not the link itself.
				rel, err := filepath.Rel(filepath.Dir(agentSkillDir), canonicalSkillDir)
				if err != nil {
					return fmt.Errorf("could not compute relative path for %s: %w", name, err)
				}

				if err := os.MkdirAll(filepath.Dir(agentSkillDir), 0o755); err != nil {
					return fmt.Errorf("could not create %s directory: %w", name, err)
				}

				// Remove existing symlink/dir before creating.
				_ = os.Remove(agentSkillDir)

				if err := os.Symlink(rel, agentSkillDir); err != nil {
					// Fall back to copy if symlink fails (e.g. Windows without dev mode).
					copyDest := filepath.Join(agentSkillDir, "SKILL.md")
					if mkErr := os.MkdirAll(agentSkillDir, 0o755); mkErr != nil {
						return fmt.Errorf("could not create %s directory: %w", name, mkErr)
					}
					if wErr := os.WriteFile(copyDest, []byte(embedded.SkillMD), 0o644); wErr != nil {
						return fmt.Errorf("could not write %s skill file: %w", name, wErr)
					}
					_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Copied  %s (symlink failed)\n", copyDest)
					continue
				}
				_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Linked  %s -> %s\n", agentSkillDir, rel)
			}

			return nil
		},
	}

	cmd.Flags().BoolVarP(&global, "global", "g", false, "Install to home directory instead of project")
	cmd.Flags().BoolVar(&copyMode, "copy", false, "Copy files instead of symlinking")
	cmd.Flags().StringSliceVarP(&agents, "agent", "a", nil, "Target specific agents (e.g. claude-code)")

	return cmd
}

func installBase(global bool) (string, error) {
	if global {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", fmt.Errorf("could not determine home directory: %w", err)
		}
		return home, nil
	}
	cwd, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("could not determine working directory: %w", err)
	}
	return cwd, nil
}

