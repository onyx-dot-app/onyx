package skills

import (
	"os"
	"path/filepath"
	"testing"
)

func writeSkill(t *testing.T, base, name, content string) {
	t.Helper()
	dir := filepath.Join(base, ".agents", "skills", name)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestParseFrontmatter(t *testing.T) {
	content := "---\nname: my-skill\ndescription: Does a thing.\n---\n\n# Heading\n\nBody text.\n"
	skill := Parse(content, "dir-name")

	if skill.Name != "my-skill" {
		t.Errorf("Name = %q, want %q", skill.Name, "my-skill")
	}
	if skill.Description != "Does a thing." {
		t.Errorf("Description = %q, want %q", skill.Description, "Does a thing.")
	}
	if skill.Body != "# Heading\n\nBody text." {
		t.Errorf("Body = %q", skill.Body)
	}
	if skill.Command() != "/my-skill" {
		t.Errorf("Command() = %q", skill.Command())
	}
}

func TestParseNoFrontmatter(t *testing.T) {
	skill := Parse("# Just markdown\n", "fallback")
	if skill.Name != "fallback" {
		t.Errorf("Name = %q, want %q", skill.Name, "fallback")
	}
	if skill.Body != "# Just markdown" {
		t.Errorf("Body = %q", skill.Body)
	}
}

func TestParseQuotedValues(t *testing.T) {
	content := "---\nname: \"quoted\"\ndescription: 'single'\n---\nbody\n"
	skill := Parse(content, "x")
	if skill.Name != "quoted" || skill.Description != "single" {
		t.Errorf("got name=%q description=%q", skill.Name, skill.Description)
	}
}

func TestParseUnterminatedFrontmatter(t *testing.T) {
	content := "---\nname: broken\nno end marker\n"
	skill := Parse(content, "fallback")
	if skill.Name != "fallback" {
		t.Errorf("Name = %q, want fallback", skill.Name)
	}
}

func TestDiscoverFrom(t *testing.T) {
	project := t.TempDir()
	home := t.TempDir()

	writeSkill(t, project, "alpha", "---\nname: alpha\ndescription: Project alpha.\n---\nA\n")
	writeSkill(t, project, "shared", "---\nname: shared\ndescription: Project copy.\n---\nP\n")
	writeSkill(t, home, "shared", "---\nname: shared\ndescription: Home copy.\n---\nH\n")
	writeSkill(t, home, "beta", "---\nname: beta\n---\nB\n")
	// Invalid name — must be skipped.
	writeSkill(t, home, "bad", "---\nname: Bad Name!\n---\nX\n")

	found := discoverFrom([]string{project, home})

	if len(found) != 3 {
		t.Fatalf("got %d skills, want 3: %+v", len(found), found)
	}
	if found[0].Name != "alpha" || found[1].Name != "beta" || found[2].Name != "shared" {
		t.Errorf("unexpected order: %+v", found)
	}
	if found[2].Description != "Project copy." {
		t.Errorf("project skill should shadow home skill, got %q", found[2].Description)
	}
}

func TestDiscoverFromMissingDir(t *testing.T) {
	if found := discoverFrom([]string{t.TempDir()}); len(found) != 0 {
		t.Errorf("expected no skills, got %+v", found)
	}
}
