package tui

import (
	"strings"
	"testing"

	"github.com/onyx-dot-app/onyx/cli/internal/skills"
)

func TestSkillPrompt(t *testing.T) {
	s := skills.Skill{Name: "release-notes", Body: "Do the thing."}

	withArg := skillPrompt(s, "for v2")
	if !strings.Contains(withArg, `<skill name="release-notes">`) {
		t.Errorf("missing skill tag: %q", withArg)
	}
	if !strings.Contains(withArg, "Do the thing.") {
		t.Errorf("missing skill body: %q", withArg)
	}
	if !strings.Contains(withArg, "My request: for v2") {
		t.Errorf("missing user request: %q", withArg)
	}

	noArg := skillPrompt(s, "")
	if !strings.Contains(noArg, "My request: run this skill.") {
		t.Errorf("missing default request: %q", noArg)
	}
}

func TestIsBuiltinCommand(t *testing.T) {
	for _, cmd := range []string{"/help", "/skills", "/new", "/resume", "/quit"} {
		if !isBuiltinCommand(cmd) {
			t.Errorf("isBuiltinCommand(%q) = false, want true", cmd)
		}
	}
	if isBuiltinCommand("/release-notes") {
		t.Error("isBuiltinCommand(/release-notes) = true, want false")
	}
}

func TestRenderHelpIncludesSkills(t *testing.T) {
	help := renderHelp([]skills.Skill{{Name: "foo", Description: "Foo skill."}})
	if !strings.Contains(help, "/foo") || !strings.Contains(help, "Foo skill.") {
		t.Errorf("help missing skill entry: %q", help)
	}

	bare := renderHelp(nil)
	if strings.Contains(bare, "Skills\n") {
		t.Errorf("help without skills should omit the Skills section: %q", bare)
	}
}

func TestSkillMenuCompletion(t *testing.T) {
	m := newInputModel()
	m.setSkillCommands([]slashCommand{{command: "/release-notes", description: "Draft notes"}})
	m.textInput.SetValue("/rel")
	m = m.updateMenu()

	if !m.menuVisible || len(m.menuItems) != 1 || m.menuItems[0].command != "/release-notes" {
		t.Errorf("menu = visible:%v items:%+v", m.menuVisible, m.menuItems)
	}
}
