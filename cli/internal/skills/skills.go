// Package skills discovers user-authored SKILL.md files and turns them into
// reusable chat prompts.
package skills

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// ArgsPlaceholder is replaced with the text the user typed after the command.
// A skill without the placeholder gets the text appended instead.
const ArgsPlaceholder = "$ARGUMENTS"

// maxBodyBytes caps how much of a SKILL.md file is sent as a prompt. Files
// above this size are skipped rather than silently truncated.
const maxBodyBytes = 128 * 1024

// skillDirs are the skill directory layouts searched under each root, in
// precedence order. The canonical .agents directory wins over agent-specific
// directories, which are usually symlinks back to it.
var skillDirs = []string{
	filepath.Join(".agents", "skills"),
	filepath.Join(".claude", "skills"),
}

// Skill is a user-authored prompt loaded from a SKILL.md file.
type Skill struct {
	// Name is the slash command name, without the leading slash.
	Name string
	// Description is a one-line summary shown in the command menu.
	Description string
	// Body is the file content with any YAML frontmatter removed.
	Body string
	// Path is the SKILL.md file the skill was loaded from.
	Path string
}

// Prompt builds the message to send for this skill. args is the text the user
// typed after the command name.
func (s Skill) Prompt(args string) string {
	args = strings.TrimSpace(args)
	if strings.Contains(s.Body, ArgsPlaceholder) {
		return strings.ReplaceAll(s.Body, ArgsPlaceholder, args)
	}
	if args == "" {
		return s.Body
	}
	return s.Body + "\n\n" + args
}

// Roots returns the base directories searched for skills, project first.
func Roots() []string {
	var roots []string
	if cwd, err := os.Getwd(); err == nil {
		roots = append(roots, cwd)
	}
	if home, err := os.UserHomeDir(); err == nil {
		roots = append(roots, home)
	}
	return roots
}

// Discover loads skills from the project directory and the home directory.
func Discover() []Skill {
	return DiscoverIn(Roots())
}

// DiscoverIn loads skills from the given roots. Earlier roots win when two
// skills share a name, as does .agents/skills over an agent-specific directory
// within the same root. Unreadable or malformed skills are skipped.
func DiscoverIn(roots []string) []Skill {
	seen := make(map[string]bool)
	var found []Skill

	for _, root := range roots {
		for _, dir := range skillDirs {
			for _, skill := range scanDir(filepath.Join(root, dir)) {
				if seen[skill.Name] {
					continue
				}
				seen[skill.Name] = true
				found = append(found, skill)
			}
		}
	}

	sort.Slice(found, func(i, j int) bool { return found[i].Name < found[j].Name })
	return found
}

// scanDir loads every <dir>/<name>/SKILL.md, sorted by directory name.
func scanDir(dir string) []Skill {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}

	var found []Skill
	for _, entry := range entries {
		// A skill directory is often a symlink to the canonical copy, and
		// ReadDir reports symlinks as non-directories.
		info, err := os.Stat(filepath.Join(dir, entry.Name()))
		if err != nil || !info.IsDir() {
			continue
		}
		skill, err := Load(filepath.Join(dir, entry.Name(), "SKILL.md"))
		if err != nil {
			continue
		}
		found = append(found, skill)
	}

	sort.Slice(found, func(i, j int) bool { return found[i].Name < found[j].Name })
	return found
}

// Load reads a single SKILL.md file. The command name comes from the
// frontmatter `name` field, falling back to the parent directory name.
func Load(path string) (Skill, error) {
	info, err := os.Stat(path)
	if err != nil {
		return Skill{}, err
	}
	// Reading a FIFO or device file can block forever, and Size() is
	// meaningless for them.
	if !info.Mode().IsRegular() {
		return Skill{}, fmt.Errorf("%s is not a regular file", path)
	}
	if info.Size() > maxBodyBytes {
		return Skill{}, fmt.Errorf("%s is larger than %d bytes", path, maxBodyBytes)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return Skill{}, err
	}

	meta, body, err := splitFrontmatter(string(data))
	if err != nil {
		return Skill{}, fmt.Errorf("%s: %w", path, err)
	}
	body = strings.TrimSpace(body)
	if body == "" {
		return Skill{}, errors.New("skill body is empty")
	}

	name := normalizeName(meta["name"])
	if name == "" {
		name = normalizeName(filepath.Base(filepath.Dir(path)))
	}
	if name == "" {
		return Skill{}, fmt.Errorf("%s has no usable skill name", path)
	}

	return Skill{
		Name:        name,
		Description: firstLine(meta["description"]),
		Body:        body,
		Path:        path,
	}, nil
}

// splitFrontmatter separates a leading YAML frontmatter block from the body.
// Only flat `key: value` pairs are read; anything else is ignored. A file that
// opens a frontmatter block but never closes it is an error, because returning
// it whole would send the YAML metadata as prompt content.
func splitFrontmatter(content string) (map[string]string, string, error) {
	meta := make(map[string]string)

	rest, ok := strings.CutPrefix(content, "---\n")
	if !ok {
		rest, ok = strings.CutPrefix(content, "---\r\n")
		if !ok {
			return meta, content, nil
		}
	}

	end := strings.Index(rest, "\n---")
	if end < 0 {
		return nil, "", errors.New("frontmatter block is not closed")
	}
	block := rest[:end]
	body := rest[end+len("\n---"):]
	if idx := strings.Index(body, "\n"); idx >= 0 {
		body = body[idx+1:]
	} else {
		body = ""
	}

	for _, line := range strings.Split(block, "\n") {
		key, value, found := strings.Cut(line, ":")
		if !found {
			continue
		}
		key = strings.ToLower(strings.TrimSpace(key))
		value = strings.TrimSpace(value)
		value = strings.Trim(value, `"'`)
		if key != "" && value != "" {
			meta[key] = value
		}
	}

	return meta, body, nil
}

// normalizeName lowercases a name and keeps only characters that are safe in a
// slash command. It returns "" when nothing usable remains.
func normalizeName(raw string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(strings.TrimSpace(raw)) {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9', r == '-', r == '_':
			b.WriteRune(r)
		case r == ' ':
			b.WriteRune('-')
		}
	}
	return strings.Trim(b.String(), "-_")
}

// firstLine collapses a value to its first line for menu display.
func firstLine(value string) string {
	line, _, _ := strings.Cut(strings.TrimSpace(value), "\n")
	return strings.TrimSpace(line)
}
