package cmd

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"
)

func writeSkill(t *testing.T, source, tier, name, description, body string) {
	t.Helper()
	content := "---\nname: " + name + "\ndescription: " + description + "\n---\n\n" + body + "\n"
	deployWriteFile(t, filepath.Join(source, tier, name, "SKILL.md"), content)
}

func discardCmd() *cobra.Command {
	cmd := &cobra.Command{}
	cmd.SetOut(io.Discard)
	cmd.SetErr(io.Discard)
	return cmd
}

// testUI is non-interactive by default: directories are created without a
// question and conflicts keep both files. Tests drive the interactive paths
// through the injected prompt funcs.
func testUI() *installUI {
	return &installUI{out: io.Discard}
}

func skillByName(t *testing.T, skills []llmContextSkill, name string) llmContextSkill {
	t.Helper()
	for _, skill := range skills {
		if skill.Name == name {
			return skill
		}
	}
	t.Fatalf("no skill named %q in %+v", name, skills)
	return llmContextSkill{}
}

func discover(t *testing.T, source string) []llmContextSkill {
	t.Helper()
	skills, err := discoverLLMContextSkills(source)
	if err != nil {
		t.Fatal(err)
	}
	return skills
}

func TestDiscoverSkillsParsesBothTiers(t *testing.T) {
	source := t.TempDir()
	writeSkill(t, source, "enforced", "always-on", "'applies to: everything'", "Rule one.")
	// A folded description spans lines; the value must survive parsing whole.
	deployWriteFile(
		t,
		filepath.Join(source, "skills", "on-demand", "SKILL.md"),
		"---\ndescription: >-\n  load when\n  relevant\n---\n\nRule two.\n",
	)

	skills := discover(t, source)
	if len(skills) != 2 {
		t.Fatalf("expected 2 skills, got %d", len(skills))
	}

	enforced := skillByName(t, skills, "always-on")
	if !enforced.Enforced {
		t.Fatalf("unexpected enforced skill: %+v", enforced)
	}
	// The YAML value keeps its colon; the quotes are syntax, not content.
	if enforced.Description != "applies to: everything" {
		t.Fatalf("unexpected description: %q", enforced.Description)
	}
	if enforced.Body != "Rule one.\n" {
		t.Fatalf("frontmatter should be stripped from the body: %q", enforced.Body)
	}

	manual := skillByName(t, skills, "on-demand")
	if manual.Enforced {
		t.Fatalf("skills/ tier must not be enforced: %+v", manual)
	}
	if manual.Description != "load when relevant" {
		t.Fatalf("folded description lost its continuation: %q", manual.Description)
	}
}

func TestDiscoverSkillsRejectsInvalidFrontmatter(t *testing.T) {
	source := t.TempDir()
	deployWriteFile(
		t,
		filepath.Join(source, "enforced", "broken", "SKILL.md"),
		"---\ndescription: applies to: everything\n---\n\nBody.\n",
	)

	if _, err := discoverLLMContextSkills(source); err == nil ||
		!strings.Contains(err.Error(), "broken/SKILL.md") {
		t.Fatalf("expected a parse error naming the file, got %v", err)
	}
}

func TestInstallCursorSkillsRendersTiersAsRuleTypes(t *testing.T) {
	source := t.TempDir()
	repoRoot := t.TempDir()
	writeSkill(t, source, "enforced", "always-on", "'core rules: everywhere'", "Always do X.")
	writeSkill(t, source, "skills", "on-demand", "db work", "Use sessions.")

	if err := installCursorSkills(discardCmd(), testUI(), discover(t, source), repoRoot); err != nil {
		t.Fatal(err)
	}

	enforced := readRule(t, repoRoot, "always-on")
	var parsed struct {
		Description string `yaml:"description"`
		AlwaysApply bool   `yaml:"alwaysApply"`
	}
	frontmatter := strings.SplitN(enforced, "---\n", 3)[1]
	if err := yaml.Unmarshal([]byte(frontmatter), &parsed); err != nil {
		t.Fatalf("generated frontmatter is not valid YAML: %v\n%s", err, enforced)
	}
	// The colon in the description must round-trip through the rendered YAML.
	if parsed.Description != "core rules: everywhere" || !parsed.AlwaysApply {
		t.Fatalf("unexpected frontmatter: %+v\n%s", parsed, enforced)
	}
	if !strings.Contains(enforced, "Always do X.") ||
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

func TestInstallCursorSkillsRegeneratesAChangedRule(t *testing.T) {
	source := t.TempDir()
	repoRoot := t.TempDir()
	writeSkill(t, source, "enforced", "always-on", "core rules", "Old body.")
	if err := installCursorSkills(discardCmd(), testUI(), discover(t, source), repoRoot); err != nil {
		t.Fatal(err)
	}

	writeSkill(t, source, "enforced", "always-on", "core rules", "New body.")
	if err := installCursorSkills(discardCmd(), testUI(), discover(t, source), repoRoot); err != nil {
		t.Fatal(err)
	}

	if rule := readRule(t, repoRoot, "always-on"); !strings.Contains(rule, "New body.") {
		t.Fatalf("rule was not regenerated:\n%s", rule)
	}
}

func TestInstallCursorSkillsRemovesStaleGeneratedRulesOnly(t *testing.T) {
	source := t.TempDir()
	repoRoot := t.TempDir()
	writeSkill(t, source, "enforced", "kept", "still here", "Body.")

	rulesDir := filepath.Join(repoRoot, ".cursor", "rules")
	stale := filepath.Join(rulesDir, "removed-skill.mdc")
	deployWriteFile(t, stale, "---\n---\n"+generatedRuleMarker+"\nold")
	handWritten := filepath.Join(rulesDir, "my-own-rule.mdc")
	deployWriteFile(t, handWritten, "---\nalwaysApply: true\n---\nmine")

	if err := installCursorSkills(discardCmd(), testUI(), discover(t, source), repoRoot); err != nil {
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

func TestInstallCursorSkillsCleansStaleRulesEvenWithoutSkills(t *testing.T) {
	repoRoot := t.TempDir()
	stale := filepath.Join(repoRoot, ".cursor", "rules", "removed-skill.mdc")
	deployWriteFile(t, stale, generatedRuleMarker+"\nold")

	if err := installCursorSkills(discardCmd(), testUI(), nil, repoRoot); err != nil {
		t.Fatal(err)
	}

	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Fatalf("stale generated rule should be removed: %v", err)
	}

	// With neither skills nor an existing rules directory, nothing is created.
	emptyRoot := t.TempDir()
	if err := installCursorSkills(discardCmd(), testUI(), nil, emptyRoot); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(emptyRoot, ".cursor")); !os.IsNotExist(err) {
		t.Fatalf("expected no .cursor directory, got %v", err)
	}
}

func TestInstallCursorSkillsKeepsAConflictingHandWrittenRule(t *testing.T) {
	source := t.TempDir()
	repoRoot := t.TempDir()
	writeSkill(t, source, "enforced", "always-on", "core rules", "Generated body.")
	dest := filepath.Join(repoRoot, ".cursor", "rules", "always-on.mdc")
	deployWriteFile(t, dest, "---\nalwaysApply: true\n---\nmine")

	// Non-interactive runs must never destroy a hand-written rule.
	if err := installCursorSkills(discardCmd(), testUI(), discover(t, source), repoRoot); err != nil {
		t.Fatal(err)
	}

	if backup := skillReadFile(t, filepath.Join(
		repoRoot, ".cursor", "rules", "always-on_old.mdc",
	)); !strings.Contains(backup, "mine") {
		t.Fatalf("hand-written rule was not preserved: %q", backup)
	}
	if rule := readRule(t, repoRoot, "always-on"); !strings.Contains(rule, "Generated body.") {
		t.Fatalf("generated rule was not installed:\n%s", rule)
	}
}

func TestInstallCursorSkillsConflictChoicesOverwrite(t *testing.T) {
	source := t.TempDir()
	repoRoot := t.TempDir()
	writeSkill(t, source, "enforced", "rule-a", "a", "A body.")
	writeSkill(t, source, "enforced", "rule-b", "b", "B body.")
	for _, name := range []string{"rule-a", "rule-b"} {
		deployWriteFile(t, filepath.Join(repoRoot, ".cursor", "rules", name+".mdc"), "mine")
	}

	// The first conflict answers "overwrite all", so the second never prompts.
	prompts := 0
	ui := testUI()
	ui.interactive = true
	ui.choose = func(string, []string, int) int {
		prompts++
		return int(conflictOverwriteAll)
	}

	if err := installCursorSkills(discardCmd(), ui, discover(t, source), repoRoot); err != nil {
		t.Fatal(err)
	}

	if prompts != 1 {
		t.Fatalf("expected one prompt for overwrite-all, got %d", prompts)
	}
	for _, name := range []string{"rule-a", "rule-b"} {
		if _, err := os.Stat(filepath.Join(
			repoRoot, ".cursor", "rules", name+"_old.mdc",
		)); !os.IsNotExist(err) {
			t.Fatalf("overwrite must not leave a backup for %s: %v", name, err)
		}
		if !strings.Contains(readRule(t, repoRoot, name), generatedRuleMarker) {
			t.Fatalf("rule %s was not overwritten", name)
		}
	}
}

func TestInstallCursorSkillsAsksBeforeCreatingTheRulesDir(t *testing.T) {
	source := t.TempDir()
	repoRoot := t.TempDir()
	customDir := filepath.Join(t.TempDir(), "my-rules")
	writeSkill(t, source, "enforced", "always-on", "core rules", "Body.")

	ui := testUI()
	ui.interactive = true
	ui.confirm = func(string) bool { return false }
	ui.readString = func(string) string { return customDir }

	if err := installCursorSkills(discardCmd(), ui, discover(t, source), repoRoot); err != nil {
		t.Fatal(err)
	}

	if _, err := os.Stat(filepath.Join(repoRoot, ".cursor")); !os.IsNotExist(err) {
		t.Fatalf("declined default must not be created: %v", err)
	}
	if got := skillReadFile(t, filepath.Join(customDir, "always-on.mdc")); !strings.Contains(got, "Body.") {
		t.Fatalf("rule missing from the chosen directory: %q", got)
	}
}

func readRule(t *testing.T, repoRoot, name string) string {
	t.Helper()
	return skillReadFile(t, filepath.Join(repoRoot, ".cursor", "rules", name+".mdc"))
}
