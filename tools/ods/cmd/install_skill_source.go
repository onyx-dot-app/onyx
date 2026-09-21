package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// llmContextSkill is one skill directory of onyx-llm-context, parsed enough to
// install it for any agent.
type llmContextSkill struct {
	// Directory name, which is also the skill's invocation name.
	Name string
	// Absolute path of the skill directory.
	Dir string
	// Absolute path of the SKILL.md file.
	File string
	// The `description` frontmatter value, "" when absent.
	Description string
	// SKILL.md content with the frontmatter block stripped.
	Body string
	// True for enforced/ skills (always-on), false for skills/ (on demand).
	Enforced bool
}

// discoverLLMContextSkills reads the enforced/ and skills/ tiers of an
// onyx-llm-context checkout. A missing tier directory is not an error.
func discoverLLMContextSkills(source string) ([]llmContextSkill, error) {
	var skills []llmContextSkill
	for _, tier := range []struct {
		dir      string
		enforced bool
	}{
		{"enforced", true},
		{"skills", false},
	} {
		tierDir := filepath.Join(source, tier.dir)
		entries, err := os.ReadDir(tierDir)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("could not read %s: %w", tierDir, err)
		}
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			skillFile := filepath.Join(tierDir, entry.Name(), "SKILL.md")
			content, err := os.ReadFile(skillFile)
			if os.IsNotExist(err) {
				continue
			}
			if err != nil {
				return nil, fmt.Errorf("could not read %s: %w", skillFile, err)
			}
			description, body := parseSkillMarkdown(string(content))
			skills = append(skills, llmContextSkill{
				Name:        entry.Name(),
				Dir:         filepath.Join(tierDir, entry.Name()),
				File:        skillFile,
				Description: description,
				Body:        body,
				Enforced:    tier.enforced,
			})
		}
	}
	return skills, nil
}

// parseSkillMarkdown splits a SKILL.md into its `description` frontmatter value
// and its body. A file with no frontmatter block is all body.
func parseSkillMarkdown(content string) (description string, body string) {
	rest, found := strings.CutPrefix(content, "---\n")
	if !found {
		return "", content
	}
	frontmatter, body, found := strings.Cut(rest, "\n---\n")
	if !found {
		return "", content
	}
	for _, line := range strings.Split(frontmatter, "\n") {
		if value, ok := strings.CutPrefix(line, "description:"); ok {
			description = strings.TrimSpace(value)
		}
	}
	return description, strings.TrimLeft(body, "\n")
}
