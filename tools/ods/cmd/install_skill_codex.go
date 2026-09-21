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
	// Compiled enforced skills at the repo root. Codex only auto-discovers
	// files literally named AGENTS.md, and the committed AGENTS.md is public,
	// so it carries a pointer to this untracked file instead of the content.
	agentsLocalFile = ".agents-local.md"
	// Codex custom prompts, invoked as /name like Claude's manual skills.
	codexPromptsDir = ".codex/prompts"
)

// installCodexSkills compiles the enforced skills into a git-excluded
// .agents-local.md at the repo root (the committed AGENTS.md tells agents to
// read it) and installs each on-demand skill as a Codex custom prompt.
func installCodexSkills(
	cmd *cobra.Command, skills []llmContextSkill, repoRoot string,
) error {
	if err := writeAgentsLocal(cmd, skills, repoRoot); err != nil {
		return err
	}
	if err := excludeAgentsLocal(repoRoot); err != nil {
		return err
	}
	return installCodexPrompts(cmd, skills)
}

func writeAgentsLocal(
	cmd *cobra.Command, skills []llmContextSkill, repoRoot string,
) error {
	var sections []string
	for _, skill := range skills {
		if skill.Enforced {
			sections = append(
				sections, fmt.Sprintf("## %s\n\n%s", skill.Name, strings.TrimRight(skill.Body, "\n")),
			)
		}
	}
	if len(sections) == 0 {
		return nil
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
	if err := os.WriteFile(dest, []byte(content), 0o644); err != nil {
		return fmt.Errorf("could not write %s: %w", dest, err)
	}
	_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Installed %s\n", dest)
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

// installCodexPrompts writes each on-demand skill as ~/.codex/prompts/<name>.md.
// Prompts are single files, so the SKILL.md body is copied with the frontmatter
// stripped rather than symlinked. Stale generated prompts are removed by their
// marker, so hand-written prompts survive.
func installCodexPrompts(cmd *cobra.Command, skills []llmContextSkill) error {
	home, err := os.UserHomeDir()
	if err != nil {
		return fmt.Errorf("could not determine home directory: %w", err)
	}
	promptsDir := filepath.Join(home, codexPromptsDir)
	if err := os.MkdirAll(promptsDir, 0o755); err != nil {
		return fmt.Errorf("could not create %s: %w", promptsDir, err)
	}

	current := make(map[string]bool, len(skills))
	var manual []llmContextSkill
	for _, skill := range skills {
		if skill.Enforced {
			continue
		}
		manual = append(manual, skill)
		current[skill.Name+".md"] = true
	}

	entries, err := os.ReadDir(promptsDir)
	if err != nil {
		return fmt.Errorf("could not read %s: %w", promptsDir, err)
	}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".md") || current[entry.Name()] {
			continue
		}
		path := filepath.Join(promptsDir, entry.Name())
		content, err := os.ReadFile(path)
		if err != nil || !strings.Contains(string(content), generatedRuleMarker) {
			continue
		}
		if err := os.Remove(path); err != nil {
			return fmt.Errorf("could not remove stale prompt %s: %w", path, err)
		}
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Removed %s\n", path)
	}

	for _, skill := range manual {
		dest := filepath.Join(promptsDir, skill.Name+".md")
		content := fmt.Sprintf("%s\n\n%s", generatedRuleMarker, skill.Body)
		existing, err := os.ReadFile(dest)
		if err == nil && string(existing) == content {
			_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Up to date %s\n", dest)
			continue
		}
		if err := os.WriteFile(dest, []byte(content), 0o644); err != nil {
			return fmt.Errorf("could not write %s: %w", dest, err)
		}
		_, _ = fmt.Fprintf(cmd.OutOrStdout(), "Installed %s\n", dest)
	}
	return nil
}
