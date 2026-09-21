package cmd

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/spf13/cobra"
)

func writeSkill(t *testing.T, source, tier, name, description, body string) {
	t.Helper()
	dir := filepath.Join(source, tier, name)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	content := "---\nname: " + name + "\ndescription: " + description + "\n---\n\n" + body + "\n"
	if err := os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func discardCmd() *cobra.Command {
	cmd := &cobra.Command{}
	cmd.SetOut(io.Discard)
	cmd.SetErr(io.Discard)
	return cmd
}

func TestDiscoverSkillsParsesBothTiers(t *testing.T) {
	source := t.TempDir()
	writeSkill(t, source, "enforced", "always-on", "applies to: everything", "Rule one.")
	writeSkill(t, source, "skills", "on-demand", "load when relevant", "Rule two.")

	skills, err := discoverLLMContextSkills(source)
	if err != nil {
		t.Fatal(err)
	}
	if len(skills) != 2 {
		t.Fatalf("expected 2 skills, got %d", len(skills))
	}

	enforced, manual := skills[0], skills[1]
	if !enforced.Enforced || enforced.Name != "always-on" {
		t.Fatalf("unexpected enforced skill: %+v", enforced)
	}
	// The description keeps everything after the key, colons included.
	if enforced.Description != "applies to: everything" {
		t.Fatalf("unexpected description: %q", enforced.Description)
	}
	if enforced.Body != "Rule one.\n" {
		t.Fatalf("frontmatter should be stripped from the body: %q", enforced.Body)
	}
	if manual.Enforced {
		t.Fatalf("skills/ tier must not be enforced: %+v", manual)
	}
}

func TestInstallCursorSkillsRendersTiersAsRuleTypes(t *testing.T) {
	source := t.TempDir()
	repoRoot := t.TempDir()
	writeSkill(t, source, "enforced", "always-on", "core rules", "Always do X.")
	writeSkill(t, source, "skills", "on-demand", "db work", "Use sessions.")

	skills, err := discoverLLMContextSkills(source)
	if err != nil {
		t.Fatal(err)
	}
	if err := installCursorSkills(discardCmd(), skills, repoRoot); err != nil {
		t.Fatal(err)
	}

	enforced := readRule(t, repoRoot, "always-on")
	if !strings.Contains(enforced, "alwaysApply: true") {
		t.Fatalf("enforced skill must be an always rule:\n%s", enforced)
	}
	if !strings.Contains(enforced, "description: core rules") ||
		!strings.Contains(enforced, "Always do X.") ||
		!strings.Contains(enforced, generatedRuleMarker) {
		t.Fatalf("unexpected rule content:\n%s", enforced)
	}
	// The skill's own frontmatter must not leak into the rule body.
	if strings.Contains(enforced, "name: always-on") {
		t.Fatalf("skill frontmatter leaked into the rule:\n%s", enforced)
	}

	if manual := readRule(t, repoRoot, "on-demand"); !strings.Contains(manual, "alwaysApply: false") {
		t.Fatalf("on-demand skill must be agent-requested:\n%s", manual)
	}
}

func TestInstallCursorSkillsRemovesStaleGeneratedRulesOnly(t *testing.T) {
	source := t.TempDir()
	repoRoot := t.TempDir()
	writeSkill(t, source, "enforced", "kept", "still here", "Body.")

	rulesDir := filepath.Join(repoRoot, ".cursor", "rules")
	if err := os.MkdirAll(rulesDir, 0o755); err != nil {
		t.Fatal(err)
	}
	stale := filepath.Join(rulesDir, "removed-skill.mdc")
	if err := os.WriteFile(stale, []byte("---\n---\n"+generatedRuleMarker+"\nold"), 0o644); err != nil {
		t.Fatal(err)
	}
	handWritten := filepath.Join(rulesDir, "my-own-rule.mdc")
	if err := os.WriteFile(handWritten, []byte("---\nalwaysApply: true\n---\nmine"), 0o644); err != nil {
		t.Fatal(err)
	}

	skills, err := discoverLLMContextSkills(source)
	if err != nil {
		t.Fatal(err)
	}
	if err := installCursorSkills(discardCmd(), skills, repoRoot); err != nil {
		t.Fatal(err)
	}

	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Fatalf("stale generated rule should be removed: %v", err)
	}
	if _, err := os.Stat(handWritten); err != nil {
		t.Fatalf("hand-written rule must survive: %v", err)
	}
	readRule(t, repoRoot, "kept")
}

func TestInstallCursorSkillsIsIdempotent(t *testing.T) {
	source := t.TempDir()
	repoRoot := t.TempDir()
	writeSkill(t, source, "enforced", "always-on", "core rules", "Body.")

	skills, err := discoverLLMContextSkills(source)
	if err != nil {
		t.Fatal(err)
	}
	if err := installCursorSkills(discardCmd(), skills, repoRoot); err != nil {
		t.Fatal(err)
	}
	first := readRule(t, repoRoot, "always-on")
	if err := installCursorSkills(discardCmd(), skills, repoRoot); err != nil {
		t.Fatal(err)
	}
	if second := readRule(t, repoRoot, "always-on"); second != first {
		t.Fatalf("rerun changed the rule:\nfirst:\n%s\nsecond:\n%s", first, second)
	}
}

func readRule(t *testing.T, repoRoot, name string) string {
	t.Helper()
	content, err := os.ReadFile(filepath.Join(repoRoot, ".cursor", "rules", name+".mdc"))
	if err != nil {
		t.Fatal(err)
	}
	return string(content)
}
