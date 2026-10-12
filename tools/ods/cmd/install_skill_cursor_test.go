package cmd

import (
	"fmt"
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

func TestInstallCursorSkillsNumbersASecondBackup(t *testing.T) {
	source := t.TempDir()
	repoRoot := t.TempDir()
	writeSkill(t, source, "enforced", "always-on", "core rules", "Generated body.")
	rulesDir := filepath.Join(repoRoot, ".cursor", "rules")
	deployWriteFile(t, filepath.Join(rulesDir, "always-on.mdc"), "first hand-written")
	deployWriteFile(t, filepath.Join(rulesDir, "always-on_old.mdc"), "earlier backup")

	if err := installCursorSkills(discardCmd(), testUI(), discover(t, source), repoRoot); err != nil {
		t.Fatal(err)
	}

	if got := skillReadFile(t, filepath.Join(rulesDir, "always-on_old.mdc")); got != "earlier backup" {
		t.Fatalf("the earlier backup was overwritten: %q", got)
	}
	if got := skillReadFile(t, filepath.Join(rulesDir, "always-on_old2.mdc")); got != "first hand-written" {
		t.Fatalf("the kept file did not move to a numbered backup: %q", got)
	}
}

func TestDiscoverSkillsRejectsANameUsedInBothTiers(t *testing.T) {
	source := t.TempDir()
	writeSkill(t, source, "enforced", "twin", "one", "A.")
	writeSkill(t, source, "skills", "twin", "two", "B.")

	if _, err := discoverLLMContextSkills(source); err == nil ||
		!strings.Contains(err.Error(), `"twin"`) {
		t.Fatalf("expected a duplicate-name error naming the skill, got %v", err)
	}
}

func TestBackupPathSkipsDanglingSymlinksAndEventuallyGivesUp(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "rule.mdc")
	// A dangling symlink still owns its name and must be numbered past.
	if err := os.Symlink(filepath.Join(dir, "gone"), filepath.Join(dir, "rule_old.mdc")); err != nil {
		t.Fatal(err)
	}

	backup, err := backupPath(dest)
	if err != nil {
		t.Fatal(err)
	}
	if backup != filepath.Join(dir, "rule_old2.mdc") {
		t.Fatalf("expected the dangling symlink to be numbered past, got %q", backup)
	}

	deployWriteFile(t, filepath.Join(dir, "rule_old2.mdc"), "x")
	for i := 3; i <= maxBackups; i++ {
		deployWriteFile(t, filepath.Join(dir, fmt.Sprintf("rule_old%d.mdc", i)), "x")
	}
	if _, err := backupPath(dest); err == nil {
		t.Fatal("expected exhausted backup names to fail loudly")
	}
}

func TestInstallSkill_unknownAgentFails(t *testing.T) {
	skillEnv(t)
	source := filepath.Join(t.TempDir(), "onyx-llm-context")
	skillWriteSource(t, source)

	_, err := skillRun(t, "--source", source, "--agent", "emacs")

	if err == nil || !strings.Contains(err.Error(), `unknown agent "emacs"`) ||
		!strings.Contains(err.Error(), agentCursor) {
		t.Fatalf("expected an error naming the known agents, got %v", err)
	}
}

func TestInstallSkill_agentCursorInstallsRulesEndToEnd(t *testing.T) {
	_, repoRoot := skillEnv(t)
	source := filepath.Join(t.TempDir(), "onyx-llm-context")
	skillWriteSource(t, source)

	out, err := skillRun(t, "--source", source, "--agent", "claude-code", "--agent", "cursor", "--agent", "cursor")
	if err != nil {
		t.Fatalf("install-skill: %v", err)
	}

	// Both agents installed from one invocation; the repeated agent ran once.
	if got := readRule(t, repoRoot, "style"); !strings.Contains(got, "alwaysApply: true") {
		t.Fatalf("expected an enforced cursor rule, got %q", got)
	}
	if !strings.Contains(out, "Installed "+filepath.Join(repoRoot, claudeMDFile)) {
		t.Fatalf("expected the claude install to run too, got %q", out)
	}
	if strings.Count(out, "Installed "+filepath.Join(repoRoot, ".cursor", "rules", "style.mdc")) != 1 {
		t.Fatalf("expected the duplicate --agent to be deduplicated, got %q", out)
	}

	// A rerun reports the rules as up to date.
	out, err = skillRun(t, "--source", source, "--agent", "cursor")
	if err != nil {
		t.Fatalf("second install-skill: %v", err)
	}
	if !strings.Contains(out, "Up to date "+filepath.Join(repoRoot, ".cursor", "rules", "style.mdc")) {
		t.Fatalf("expected up-to-date rules, got %q", out)
	}
}

func TestResolveTargetDirCreatesTheDefaultOnConfirm(t *testing.T) {
	def := filepath.Join(t.TempDir(), "rules")
	ui := testUI()
	ui.interactive = true
	ui.confirm = func(string) bool { return true }

	got, err := ui.resolveTargetDir("Cursor rules", def)
	if err != nil {
		t.Fatal(err)
	}
	if got != def {
		t.Fatalf("expected the default directory, got %q", got)
	}
	if _, err := os.Stat(def); err != nil {
		t.Fatalf("confirmed default should be created: %v", err)
	}
}

func TestResolveConflictInteractiveChoices(t *testing.T) {
	ui := testUI()
	ui.interactive = true

	ui.choose = func(string, []string, int) int { return int(conflictKeepBoth) }
	if got := ui.resolveConflict("x.mdc"); got != conflictKeepBoth {
		t.Fatalf("expected keep-both, got %v", got)
	}
	if ui.overwriteAll {
		t.Fatal("keep-both must not turn on overwrite-all")
	}

	ui.choose = func(string, []string, int) int { return int(conflictOverwriteOne) }
	if got := ui.resolveConflict("x.mdc"); got != conflictOverwriteOne {
		t.Fatalf("expected overwrite-one, got %v", got)
	}
	if ui.overwriteAll {
		t.Fatal("overwrite-one must not turn on overwrite-all")
	}
}

func TestParseSkillMarkdownWithoutAClosedFrontmatterBlockIsAllBody(t *testing.T) {
	content := "---\ndescription: never closed\nbody text"
	description, body, err := parseSkillMarkdown(content)
	if err != nil {
		t.Fatal(err)
	}
	if description != "" || body != content {
		t.Fatalf("unclosed frontmatter must read as body: %q / %q", description, body)
	}
}
