package tui

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// statusBar manages the footer status display.
type statusBar struct {
	personaName string
	serverURL   string
	sessionID   string
	streaming   bool
	width       int
}

func newStatusBar() statusBar {
	return statusBar{
		personaName: "Default",
	}
}

func (s *statusBar) setPersona(name string) { s.personaName = name }
func (s *statusBar) setServer(url string)    { s.serverURL = url }
func (s *statusBar) setSession(id string) {
	if len(id) > 8 {
		id = id[:8]
	}
	s.sessionID = id
}
func (s *statusBar) setStreaming(v bool) { s.streaming = v }
func (s *statusBar) setWidth(w int)     { s.width = w }

func (s statusBar) view() string {
	var leftParts []string
	if s.serverURL != "" {
		leftParts = append(leftParts, s.serverURL)
	}
	name := s.personaName
	if name == "" {
		name = "Default"
	}
	leftParts = append(leftParts, name)
	left := statusBarStyle.Render(strings.Join(leftParts, " · "))

	right := "Ctrl+D to quit"
	if s.streaming {
		right = "Esc to cancel"
	}
	rightRendered := statusBarStyle.Render(right)

	// Fill space between left and right
	gap := s.width - lipgloss.Width(left) - lipgloss.Width(rightRendered)
	if gap < 1 {
		gap = 1
	}

	return left + strings.Repeat(" ", gap) + rightRendered
}
