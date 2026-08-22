package tui

import (
	"fmt"
	"strings"

	"github.com/onyx-dot-app/onyx/cli/internal/skills"
)

const baseHelpText = `Onyx CLI Commands

  /help              Show this help message
  /clear             Clear chat and start a new session
  /agent             List and switch agents
  /attach <path>     Attach a file to next message
  /sessions          Browse and resume previous sessions
  /skills            List available skills
  /configure         Re-run connection setup
  /connectors        Open connectors page in browser
  /settings          Open Onyx settings in browser
  /experiments       List experimental features and their status
  /quit              Exit Onyx CLI
`

const keyboardHelpText = `
Keyboard Shortcuts

  Enter              Send message
  Escape             Cancel current generation
  Ctrl+O             Toggle source citations
  Ctrl+D             Quit (press twice)
  Scroll Up/Down     Mouse wheel or Shift+Up/Down
  Page Up/Down       Scroll half page
`

// renderHelp builds the /help text, including discovered skills.
func renderHelp(localSkills []skills.Skill) string {
	var b strings.Builder
	b.WriteString(baseHelpText)
	if len(localSkills) > 0 {
		b.WriteString("\nSkills\n\n")
		b.WriteString(skillLines(localSkills))
	}
	b.WriteString(keyboardHelpText)
	return b.String()
}

// renderSkillList builds the /skills output.
func renderSkillList(localSkills []skills.Skill) string {
	if len(localSkills) == 0 {
		return "No skills found. Add SKILL.md files under .agents/skills/<name>/ " +
			"in this directory or your home directory."
	}
	return "Available skills\n\n" + skillLines(localSkills)
}

func skillLines(localSkills []skills.Skill) string {
	var b strings.Builder
	for _, s := range localSkills {
		desc := s.Description
		if desc == "" {
			desc = "(no description)"
		}
		fmt.Fprintf(&b, "  %-18s %s\n", s.Command(), desc)
	}
	return b.String()
}
