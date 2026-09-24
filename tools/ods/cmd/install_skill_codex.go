package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"
)

const (
	// Compiled enforced skills at the repo root. Codex reads AGENTS.md (plus
	// AGENTS.override.md, ~/.codex/AGENTS.md and configured fallback names),
	// but the committed AGENTS.md is public and an override file replaces it
	// rather than extending it, and Codex skills cannot be always-on. So the
	// committed AGENTS.md carries a pointer to this untracked file.
	agentsLocalFile = ".agents-local.md"
	// Codex's native skill directory: SKILL.md-format skills, symlinks
	// followed, invoked as $skill-name.
	agentsSkillsDir = ".agents/skills"
)

// installCodexSkills compiles the enforced skills into a git-excluded
// .agents-local.md at the repo root (the committed AGENTS.md tells agents to
// read it) and symlinks each on-demand skill into Codex's native skill
// directory, the way the claude-code installer does with ~/.claude/skills.
func installCodexSkills(
	cmd *cobra.Command, ui *installUI, skills []llmContextSkill, repoRoot string, copyMode bool,
) error {
	// The exclusion comes first: a file written before a failed exclusion
	// would sit unignored, one `git add .` away from publishing the private
	// guidance the exclusion exists to protect.
	if err := excludeAgentsLocal(repoRoot); err != nil {
		return err
	}
	if err := writeAgentsLocal(cmd, ui, skills, repoRoot); err != nil {
		return err
	}
	return linkManualSkills(cmd, ui, skills, "Agent skills", agentsSkillsDir, copyMode)
}

func writeAgentsLocal(
	cmd *cobra.Command, ui *installUI, skills []llmContextSkill, repoRoot string,
) error {
	var sections []string
	for _, skill := range skills {
		if skill.Enforced {
			sections = append(
				sections, fmt.Sprintf("## %s\n\n%s", skill.Name, strings.TrimRight(skill.Body, "\n")),
			)
		}
	}
	// With no enforced skills left, a previously compiled file would stay
	// active through the AGENTS.md pointer, so it is removed rather than kept.
	if len(sections) == 0 {
		return removeStaleAgentsLocal(cmd, repoRoot)
	}

	content := fmt.Sprintf(
		"%s\n\n# Onyx developer-local agent guidance\n\n"+
			"Always-on rules from onyx-llm-context. Never committed.\n\n%s\n",
		generatedRuleMarker,
		strings.Join(sections, "\n\n"),
	)

	dest := filepath.Join(repoRoot, agentsLocalFile)
	existing, err := os.ReadFile(dest)
	if err == nil && string(existing) == content {
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Up to date %s\n", dest)
		return nil
	}
	// A file of this name the user wrote themselves is never silently replaced.
	if err == nil && !strings.Contains(string(existing), generatedRuleMarker) {
		if ui.resolveConflict(dest) == conflictKeepBoth {
			if err := backUpFile(cmd, dest); err != nil {
				return err
			}
		}
	}
	if err := os.WriteFile(dest, []byte(content), 0o644); err != nil {
		return fmt.Errorf("could not write %s: %w", dest, err)
	}
	_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Installed %s\n", dest)
	return nil
}

// removeStaleAgentsLocal deletes a previously generated .agents-local.md,
// identified by its marker so a hand-written file of the same name survives.
func removeStaleAgentsLocal(cmd *cobra.Command, repoRoot string) error {
	dest := filepath.Join(repoRoot, agentsLocalFile)
	content, err := os.ReadFile(dest)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("could not read %s: %w", dest, err)
	}
	if !strings.Contains(string(content), generatedRuleMarker) {
		return nil
	}
	if err := os.Remove(dest); err != nil {
		return fmt.Errorf("could not remove stale %s: %w", dest, err)
	}
	_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Removed %s\n", dest)
	return nil
}

// excludeAgentsLocal keeps the compiled file out of accidental commits via
// .git/info/exclude, which unlike .gitignore never appears in a public diff.
func excludeAgentsLocal(repoRoot string) error {
	gitCmd := exec.Command("git", "rev-parse", "--git-path", "info/exclude")
	gitCmd.Dir = repoRoot
	out, err := gitCmd.Output()
	if err != nil {
		return fmt.Errorf("could not locate git exclude file: %w", err)
	}
	excludePath := strings.TrimSpace(string(out))
	if !filepath.IsAbs(excludePath) {
		excludePath = filepath.Join(repoRoot, excludePath)
	}

	existing, err := os.ReadFile(excludePath)
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("could not read %s: %w", excludePath, err)
	}
	for _, line := range strings.Split(string(existing), "\n") {
		if strings.TrimSpace(line) == agentsLocalFile {
			return nil
		}
	}

	if err := os.MkdirAll(filepath.Dir(excludePath), 0o755); err != nil {
		return fmt.Errorf("could not create %s: %w", filepath.Dir(excludePath), err)
	}
	content := string(existing)
	if content != "" && !strings.HasSuffix(content, "\n") {
		content += "\n"
	}
	content += agentsLocalFile + "\n"
	if err := os.WriteFile(excludePath, []byte(content), 0o644); err != nil {
		return fmt.Errorf("could not write %s: %w", excludePath, err)
	}
	return nil
}
