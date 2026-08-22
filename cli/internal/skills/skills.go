// Package skills discovers local agent skills (SKILL.md files) so the chat
// TUI can expose them as slash commands.
package skills

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Skill is a parsed SKILL.md file.
type Skill struct {
	// Name is the skill's frontmatter name (falls back to the directory name).
	Name string
	// Description is the frontmatter description (may be empty).
	Description string
	// Body is the markdown content after the frontmatter.
	Body string
	// Path is the absolute path of the SKILL.md file.
	Path string
}

// Command returns the slash command that invokes the skill.
func (s Skill) Command() string {
	return "/" + s.Name
}

// skillsSubdir is the canonical skills directory relative to a base directory.
var skillsSubdir = filepath.Join(".agents", "skills")

// validName matches skill names that are safe to use as slash commands.
var validName = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]*$`)

// Discover loads skills from the project (working directory) and the user's
// home directory. Project skills shadow home skills with the same name.
// Results are sorted by name. Discovery errors are silently skipped — a
// malformed skill must not break the chat TUI.
func Discover() []Skill {
	var bases []string
	if cwd, err := os.Getwd(); err == nil {
		bases = append(bases, cwd)
	}
	if home, err := os.UserHomeDir(); err == nil {
		bases = append(bases, home)
	}
	return discoverFrom(bases)
}

// discoverFrom loads skills from each base directory in order. Earlier bases
// shadow later ones on name collisions.
func discoverFrom(bases []string) []Skill {
	seen := make(map[string]bool)
	var result []Skill

	for _, base := range bases {
		dir := filepath.Join(base, skillsSubdir)
		entries, err := os.ReadDir(dir)
		if err != nil {
			continue
		}
		for _, entry := range entries {
			// Allow symlinked skill directories (install-skill creates them).
			info, err := os.Stat(filepath.Join(dir, entry.Name()))
			if err != nil || !info.IsDir() {
				continue
			}
			path := filepath.Join(dir, entry.Name(), "SKILL.md")
			raw, err := os.ReadFile(path)
			if err != nil {
				continue
			}
			skill := Parse(string(raw), entry.Name())
			skill.Path = path
			if !validName.MatchString(skill.Name) || seen[skill.Name] {
				continue
			}
			seen[skill.Name] = true
			result = append(result, skill)
		}
	}

	sort.Slice(result, func(i, j int) bool { return result[i].Name < result[j].Name })
	return result
}

// Parse extracts the frontmatter name/description and the body from SKILL.md
// content. fallbackName is used when the frontmatter has no name.
func Parse(content string, fallbackName string) Skill {
	skill := Skill{Name: fallbackName, Body: strings.TrimSpace(content)}

	normalized := strings.ReplaceAll(content, "\r\n", "\n")
	if !strings.HasPrefix(normalized, "---\n") {
		return skill
	}
	rest := normalized[len("---\n"):]
	end := strings.Index(rest, "\n---")
	if end < 0 {
		return skill
	}
	frontmatter := rest[:end]
	body := rest[end+len("\n---"):]
	if i := strings.Index(body, "\n"); i >= 0 {
		body = body[i+1:]
	} else {
		body = ""
	}
	skill.Body = strings.TrimSpace(body)

	for _, line := range strings.Split(frontmatter, "\n") {
		key, value, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		value = strings.TrimSpace(value)
		value = strings.Trim(value, `"'`)
		switch strings.TrimSpace(key) {
		case "name":
			if value != "" {
				skill.Name = value
			}
		case "description":
			skill.Description = value
		}
	}
	return skill
}
