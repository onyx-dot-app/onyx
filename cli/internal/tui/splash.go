package tui

import "github.com/charmbracelet/lipgloss"

const onyxLogo = `   ██████╗ ███╗   ██╗██╗   ██╗██╗  ██╗
  ██╔═══██╗████╗  ██║╚██╗ ██╔╝╚██╗██╔╝
  ██║   ██║██╔██╗ ██║ ╚████╔╝  ╚███╔╝
  ██║   ██║██║╚██╗██║  ╚██╔╝   ██╔██╗
  ╚██████╔╝██║ ╚████║   ██║   ██╔╝ ██╗
   ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝`

const tagline = "Your terminal interface for Onyx"
const splashHint = "Type a message to begin  ·  /help for commands"

// renderSplash renders the splash screen centered for the given dimensions.
func renderSplash(width, height int) string {
	// Render the logo as a single block (don't center individual lines)
	logo := splashStyle.Render(onyxLogo)

	// Center tagline and hint relative to the logo block width
	logoWidth := lipgloss.Width(logo)
	tag := lipgloss.NewStyle().Width(logoWidth).Align(lipgloss.Center).Render(
		taglineStyle.Render(tagline),
	)
	hint := lipgloss.NewStyle().Width(logoWidth).Align(lipgloss.Center).Render(
		hintStyle.Render(splashHint),
	)

	block := lipgloss.JoinVertical(lipgloss.Left, logo, "", tag, hint)

	return lipgloss.Place(width, height, lipgloss.Center, lipgloss.Center, block)
}

