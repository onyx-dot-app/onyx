package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
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
	// The Claude installer builds symlinks and @imports from these paths, so a
	// relative --source must not leak into them.
	source, err := filepath.Abs(source)
	if err != nil {
		return nil, fmt.Errorf("could not resolve source path: %w", err)
	}

	var skills []llmContextSkill
	// Every agent maps a skill name to one file or link, so a name used in
	// both tiers would have the second silently shadow the first.
	seen := make(map[string]bool)
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
			description, body, err := parseSkillMarkdown(string(content))
			if err != nil {
				return nil, fmt.Errorf("could not parse %s: %w", skillFile, err)
			}
			if seen[entry.Name()] {
				return nil, fmt.Errorf(
					"skill %q exists in both enforced/ and skills/; rename one", entry.Name(),
				)
			}
			seen[entry.Name()] = true
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

// parseSkillMarkdown splits a SKILL.md into its `description` frontmatter
// value and its body. The frontmatter is real YAML, so folded and quoted
// values parse the way skill authors wrote them. A file with no frontmatter
// block is all body.
func parseSkillMarkdown(content string) (description string, body string, err error) {
	rest, found := strings.CutPrefix(content, "---\n")
	if !found {
		return "", content, nil
	}
	frontmatter, body, found := strings.Cut(rest, "\n---\n")
	if !found {
		return "", content, nil
	}
	var parsed struct {
		Description string `yaml:"description"`
	}
	if err := yaml.Unmarshal([]byte(frontmatter), &parsed); err != nil {
		return "", "", fmt.Errorf("invalid frontmatter: %w", err)
	}
	return parsed.Description, strings.TrimLeft(body, "\n"), nil
}
