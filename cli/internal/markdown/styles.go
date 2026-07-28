package markdown

import "charm.land/lipgloss/v2"

// Palette kept consistent with internal/tui/styles.go. Body text uses the
// same light gray (ANSI 252) glamour's dark theme used, so agent responses
// stay visually distinct from default-foreground UI text.
var (
	accentColor = lipgloss.Color("#6c8ebf")
	dimColor    = lipgloss.Color("#555577")
	codeColor   = lipgloss.Color("#a99ee8")
	textColor   = lipgloss.Color("252")

	h1Style     = lipgloss.NewStyle().Foreground(accentColor).Bold(true).Underline(true)
	h2Style     = lipgloss.NewStyle().Foreground(accentColor).Bold(true)
	hStyle      = lipgloss.NewStyle().Bold(true)
	dimStyle    = lipgloss.NewStyle().Foreground(dimColor)
	codeStyle   = lipgloss.NewStyle().Foreground(codeColor)
	bulletStyle = lipgloss.NewStyle().Foreground(accentColor)
)

func headingStyle(level int) lipgloss.Style {
	switch level {
	case 1:
		return h1Style
	case 2:
		return h2Style
	default:
		return hStyle
	}
}
