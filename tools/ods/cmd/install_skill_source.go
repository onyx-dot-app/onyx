package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

// agentContextSkill is one skill directory of the agent context, parsed enough
// to install it for any agent.
type agentContextSkill struct {
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

// discoverAgentContextSkills reads the enforced/ and skills/ tiers of an
// onyx-agent-context checkout, or of the agent-context/ directory when source
// is an onyx-infra checkout. A missing tier directory is not an error.
func discoverAgentContextSkills(source string) ([]agentContextSkill, error) {
	// The Claude installer builds symlinks and @imports from these paths, so a
	// relative --source must not leak into them.
	source, err := filepath.Abs(source)
	if err != nil {
		return nil, fmt.Errorf("could not resolve source path: %w", err)
	}
	if info, err := os.Stat(filepath.Join(source, agentContextDir)); err == nil && info.IsDir() {
		source = filepath.Join(source, agentContextDir)
	} else if !hasSkillTier(source) {
		return nil, fmt.Errorf(
			"no skills/, enforced/, or %s/ directory found in %s\n  Update the checkout (git pull) or re-run with --clone",
			agentContextDir, source,
		)
	}

	var skills []agentContextSkill
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
			skills = append(skills, agentContextSkill{
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

// hasSkillTier reports whether dir directly holds an enforced/ or skills/ tier.
func hasSkillTier(dir string) bool {
	for _, tier := range []string{"enforced", "skills"} {
		if info, err := os.Stat(filepath.Join(dir, tier)); err == nil && info.IsDir() {
			return true
		}
	}
	return false
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

// agentContextSource is where install-skill reads from when --source is not
// given.
type agentContextSource struct {
	path string
	// An older checkout under the home directory, used only when no
	// onyx-agent-context checkout exists.
	legacy bool
	// Nothing was found; path is the default location next to the main checkout.
	missing bool
}

// findAgentContextSource looks for the agent context in the order AGENTS.md
// documents: $ONYX_AGENT_CONTEXT, then onyx-agent-context/ next to the main
// checkout, then .agent-context/ in this checkout or the main one. A candidate
// counts only when it holds AGENTS.md. Older checkouts under home come next.
// When nothing exists, the path is the default location next to the main
// checkout, and --clone picks the actual destination with cloneDestination.
func findAgentContextSource(repoRoot, mainRoot, home string) agentContextSource {
	if explicit := strings.TrimSpace(os.Getenv(agentContextEnv)); explicit != "" {
		if rest, ok := strings.CutPrefix(explicit, "~/"); ok {
			explicit = filepath.Join(home, rest)
		}
		return agentContextSource{path: explicit}
	}
	for _, candidate := range []string{
		filepath.Join(filepath.Dir(mainRoot), agentContextRepoName),
		filepath.Join(repoRoot, inRepoAgentContextDir),
		filepath.Join(mainRoot, inRepoAgentContextDir),
	} {
		if info, err := os.Stat(filepath.Join(candidate, agentContextEntryFile)); err == nil && !info.IsDir() {
			return agentContextSource{path: candidate}
		}
	}
	for _, older := range []string{onyxInfraSkillSource, legacySkillSource} {
		path := filepath.Join(home, older)
		if info, err := os.Stat(path); err == nil && info.IsDir() {
			return agentContextSource{path: path, legacy: true}
		}
	}
	return agentContextSource{
		path:    filepath.Join(filepath.Dir(mainRoot), agentContextRepoName),
		missing: true,
	}
}

// cloneDestination is next to the main checkout, or inside it when that folder
// is the filesystem root or not writable: the devcontainer mounts only the
// checkout, at /workspace, and nothing outside it survives a rebuild. It is
// never inside a linked worktree, which `git worktree remove` would delete.
func cloneDestination(mainRoot string) string {
	parent := filepath.Dir(mainRoot)
	if filepath.Dir(parent) != parent && dirWritable(parent) {
		return filepath.Join(parent, agentContextRepoName)
	}
	return filepath.Join(mainRoot, inRepoAgentContextDir)
}

func dirWritable(dir string) bool {
	probe, err := os.CreateTemp(dir, ".ods-write-check-*")
	if err != nil {
		return false
	}
	name := probe.Name()
	_ = probe.Close()
	_ = os.Remove(name)
	return true
}
