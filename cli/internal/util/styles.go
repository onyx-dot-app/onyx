// Package util provides shared utilities for the Onyx CLI.
package util

import "github.com/charmbracelet/lipgloss"

// Shared text styles used across the CLI.
var (
	BoldStyle   = lipgloss.NewStyle().Bold(true)
	DimStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("#555577"))
	GreenStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("#00cc66")).Bold(true)
	RedStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("#ff5555")).Bold(true)
	YellowStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#ffcc00"))
)
