package tui

import (
	"strings"

	"charm.land/lipgloss/v2"
	"github.com/onyx-dot-app/onyx/cli/internal/sanitize"
)

// statusBar manages the footer status display.
type statusBar struct {
	agentName string
	modelName string
	serverURL string
	sessionID string
	streaming bool
	width     int
}

func newStatusBar() statusBar {
	return statusBar{
		agentName: "Default",
	}
}

func (s *statusBar) setAgent(name string) { s.agentName = sanitize.Line(name) }
func (s *statusBar) setModel(name string) { s.modelName = sanitize.Line(name) }
func (s *statusBar) setServer(url string) { s.serverURL = url }
func (s *statusBar) setSession(id string) {
	if len(id) > 8 {
		id = id[:8]
	}
	s.sessionID = sanitize.Line(id)
}
func (s *statusBar) setStreaming(v bool) { s.streaming = v }
func (s *statusBar) setWidth(w int)      { s.width = w }

func (s statusBar) view() string {
	var leftParts []string
	if s.serverURL != "" {
		leftParts = append(leftParts, s.serverURL)
	}
	name := s.agentName
	if name == "" {
		name = "Default"
	}
	leftParts = append(leftParts, name)
	if s.modelName != "" {
		leftParts = append(leftParts, s.modelName)
	}
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
