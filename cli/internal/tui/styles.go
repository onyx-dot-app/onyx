package tui

import "github.com/charmbracelet/lipgloss"

var (
	// Colors
	accentColor    = lipgloss.Color("#6c8ebf")
	dimColor       = lipgloss.Color("#555577")
	errorColor     = lipgloss.Color("#ff5555")
	splashColor    = lipgloss.Color("#7C6AEF")
	separatorColor = lipgloss.Color("#333355")
	citationColor  = lipgloss.Color("#666688")

	// Styles
	userPrefixStyle = lipgloss.NewStyle().Foreground(dimColor)
	agentDot    = lipgloss.NewStyle().Foreground(accentColor).Bold(true).Render("◉")
	infoStyle       = lipgloss.NewStyle().Foreground(lipgloss.Color("#b0b0cc"))
	dimInfoStyle    = lipgloss.NewStyle().Foreground(dimColor)
	statusMsgStyle  = dimInfoStyle // used for slash menu descriptions, file badges
	errorStyle      = lipgloss.NewStyle().Foreground(errorColor).Bold(true)
	warnStyle       = lipgloss.NewStyle().Foreground(lipgloss.Color("#ffcc00"))
	citationStyle   = lipgloss.NewStyle().Foreground(citationColor)
	statusBarStyle  = lipgloss.NewStyle().Foreground(dimColor)
	inputPrompt     = lipgloss.NewStyle().Foreground(accentColor).Render("❯ ")

	splashStyle = lipgloss.NewStyle().Foreground(splashColor).Bold(true)
	taglineStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#A0A0A0"))
	hintStyle    = lipgloss.NewStyle().Foreground(dimColor)

	// Shared text styles used across the CLI.
	BoldStyle   = lipgloss.NewStyle().Bold(true)
	DimStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("#555577"))
	GreenStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("#00cc66")).Bold(true)
	RedStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("#ff5555")).Bold(true)
	YellowStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#ffcc00"))
)
