package skills

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// writeSkill creates <root>/<dir>/<name>/SKILL.md with the given content.
func writeSkill(t *testing.T, root, dir, name, content string) string {
	t.Helper()
	skillDir := filepath.Join(root, dir, name)
	if err := os.MkdirAll(skillDir, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	path := filepath.Join(skillDir, "SKILL.md")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}
	return path
}

func TestLoadUsesFrontmatter(t *testing.T) {
	root := t.TempDir()
	path := writeSkill(t, root, ".agents/skills", "dirname", `---
name: Release Notes
description: Draft release notes.
---

# Body

Do the thing.
`)

	skill, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if skill.Name != "release-notes" {
		t.Errorf("Name = %q, want %q", skill.Name, "release-notes")
	}
	if skill.Description != "Draft release notes." {
		t.Errorf("Description = %q", skill.Description)
	}
	if strings.Contains(skill.Body, "description:") {
		t.Errorf("body still contains frontmatter: %q", skill.Body)
	}
	if !strings.HasPrefix(skill.Body, "# Body") {
		t.Errorf("Body = %q, want it to start with the heading", skill.Body)
	}
}

func TestLoadFallsBackToDirectoryName(t *testing.T) {
	root := t.TempDir()
	path := writeSkill(t, root, ".agents/skills", "Stand Up", "Summarize standup notes.\n")

	skill, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if skill.Name != "stand-up" {
		t.Errorf("Name = %q, want %q", skill.Name, "stand-up")
	}
	if skill.Description != "" {
		t.Errorf("Description = %q, want empty", skill.Description)
	}
}

func TestLoadRejectsEmptyBody(t *testing.T) {
	root := t.TempDir()
	path := writeSkill(t, root, ".agents/skills", "empty", "---\nname: empty\n---\n")

	if _, err := Load(path); err == nil {
		t.Fatal("Load succeeded on an empty body, want an error")
	}
}

func TestLoadRejectsOversizedFile(t *testing.T) {
	root := t.TempDir()
	path := writeSkill(t, root, ".agents/skills", "big", strings.Repeat("x", maxBodyBytes+1))

	if _, err := Load(path); err == nil {
		t.Fatal("Load succeeded on an oversized file, want an error")
	}
}

func TestDiscoverInPrefersProjectOverHome(t *testing.T) {
	project := t.TempDir()
	home := t.TempDir()
	writeSkill(t, project, ".agents/skills", "triage", "project version")
	writeSkill(t, home, ".agents/skills", "triage", "home version")
	writeSkill(t, home, ".agents/skills", "standup", "home standup")

	found := DiscoverIn([]string{project, home})
	if len(found) != 2 {
		t.Fatalf("got %d skills, want 2: %+v", len(found), found)
	}
	if found[0].Name != "standup" || found[1].Name != "triage" {
		t.Errorf("skills are not sorted by name: %q, %q", found[0].Name, found[1].Name)
	}
	if found[1].Body != "project version" {
		t.Errorf("triage body = %q, want the project version", found[1].Body)
	}
}

func TestDiscoverInPrefersAgentsOverClaudeDir(t *testing.T) {
	root := t.TempDir()
	writeSkill(t, root, ".agents/skills", "triage", "canonical")
	writeSkill(t, root, ".claude/skills", "triage", "claude copy")

	found := DiscoverIn([]string{root})
	if len(found) != 1 {
		t.Fatalf("got %d skills, want 1: %+v", len(found), found)
	}
	if found[0].Body != "canonical" {
		t.Errorf("body = %q, want %q", found[0].Body, "canonical")
	}
}

func TestDiscoverInFollowsSymlinkedSkillDirs(t *testing.T) {
	root := t.TempDir()
	writeSkill(t, root, ".agents/skills", "triage", "canonical")

	claudeSkills := filepath.Join(root, ".claude", "skills")
	if err := os.MkdirAll(claudeSkills, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	target := filepath.Join(root, ".agents", "skills", "triage")
	if err := os.Symlink(target, filepath.Join(claudeSkills, "linked")); err != nil {
		t.Skipf("symlinks unavailable: %v", err)
	}

	found := DiscoverIn([]string{root})
	if len(found) != 2 {
		t.Fatalf("got %d skills, want 2: %+v", len(found), found)
	}
	if found[0].Name != "linked" || found[1].Name != "triage" {
		t.Errorf("names = %q, %q", found[0].Name, found[1].Name)
	}
}

func TestDiscoverInSkipsBrokenSkills(t *testing.T) {
	root := t.TempDir()
	writeSkill(t, root, ".agents/skills", "good", "usable body")
	writeSkill(t, root, ".agents/skills", "empty", "")
	// A directory with no SKILL.md at all.
	if err := os.MkdirAll(filepath.Join(root, ".agents", "skills", "bare"), 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}

	found := DiscoverIn([]string{root})
	if len(found) != 1 || found[0].Name != "good" {
		t.Fatalf("got %+v, want only the good skill", found)
	}
}

func TestPrompt(t *testing.T) {
	tests := []struct {
		name string
		body string
		args string
		want string
	}{
		{
			name: "placeholder is substituted",
			body: "Triage this incident: $ARGUMENTS\nBe brief.",
			args: "payments 500s",
			want: "Triage this incident: payments 500s\nBe brief.",
		},
		{
			name: "empty args clear the placeholder",
			body: "Triage: $ARGUMENTS",
			args: "  ",
			want: "Triage: ",
		},
		{
			name: "args are appended without a placeholder",
			body: "Draft release notes.",
			args: "v1.2.0",
			want: "Draft release notes.\n\nv1.2.0",
		},
		{
			name: "body is unchanged without args",
			body: "Draft release notes.",
			args: "",
			want: "Draft release notes.",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := Skill{Body: tt.body}.Prompt(tt.args)
			if got != tt.want {
				t.Errorf("Prompt() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestNormalizeName(t *testing.T) {
	tests := []struct {
		in   string
		want string
	}{
		{"Release Notes", "release-notes"},
		{"  Triage  ", "triage"},
		{"my_skill", "my_skill"},
		{"weird!!name", "weirdname"},
		{"--dashes--", "dashes"},
		{"!!!", ""},
		{"", ""},
	}
	for _, tt := range tests {
		if got := normalizeName(tt.in); got != tt.want {
			t.Errorf("normalizeName(%q) = %q, want %q", tt.in, got, tt.want)
		}
	}
}

func TestSplitFrontmatterWithoutBlock(t *testing.T) {
	content := "# Just markdown\n\nNo frontmatter here.\n"
	meta, body, err := splitFrontmatter(content)
	if err != nil {
		t.Fatalf("splitFrontmatter: %v", err)
	}
	if len(meta) != 0 {
		t.Errorf("meta = %+v, want empty", meta)
	}
	if body != content {
		t.Errorf("body = %q, want the whole content", body)
	}
}

func TestSplitFrontmatterUnterminatedBlock(t *testing.T) {
	if _, _, err := splitFrontmatter("---\nname: broken\n"); err == nil {
		t.Fatal("splitFrontmatter accepted an unclosed block, want an error")
	}
}

// An unclosed frontmatter block must be skipped, never sent as prompt content.
func TestLoadRejectsUnterminatedFrontmatter(t *testing.T) {
	root := t.TempDir()
	path := writeSkill(t, root, ".agents/skills", "broken", "---\nname: broken\ndescription: Oops.\n")

	if _, err := Load(path); err == nil {
		t.Fatal("Load accepted an unclosed frontmatter block, want an error")
	}
}

func TestLoadRejectsNonRegularFile(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, ".agents", "skills", "fifo")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("MkdirAll: %v", err)
	}
	path := filepath.Join(dir, "SKILL.md")
	if err := makeFIFO(path); err != nil {
		t.Skipf("cannot create a FIFO: %v", err)
	}

	// A blocking read here would hang the test rather than fail it, so the
	// mode check has to happen before os.ReadFile.
	done := make(chan error, 1)
	go func() {
		_, err := Load(path)
		done <- err
	}()

	select {
	case err := <-done:
		if err == nil {
			t.Fatal("Load accepted a FIFO, want an error")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Load blocked on a FIFO")
	}
}
