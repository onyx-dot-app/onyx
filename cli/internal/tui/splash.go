package tui

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

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

// RenderSplashOnboarding renders splash for the terminal onboarding screen.
func RenderSplashOnboarding(width, height int) string {
	// Render the logo as a styled block, then center it as a unit
	styledLogo := splashStyle.Render(onyxLogo)
	logoWidth := lipgloss.Width(styledLogo)
	logoLines := strings.Split(styledLogo, "\n")

	logoHeight := len(logoLines)
	contentHeight := logoHeight + 2 // logo + blank + tagline
	topPad := (height - contentHeight) / 2
	if topPad < 1 {
		topPad = 1
	}

	// Center the entire logo block horizontally
	blockPad := (width - logoWidth) / 2
	if blockPad < 0 {
		blockPad = 0
	}

	var b strings.Builder
	for i := 0; i < topPad; i++ {
		b.WriteByte('\n')
	}

	for _, line := range logoLines {
		b.WriteString(strings.Repeat(" ", blockPad))
		b.WriteString(line)
		b.WriteByte('\n')
	}

	b.WriteByte('\n')
	tagPad := (width - len(tagline)) / 2
	if tagPad < 0 {
		tagPad = 0
	}
	b.WriteString(strings.Repeat(" ", tagPad))
	b.WriteString(taglineStyle.Render(tagline))
	b.WriteByte('\n')

	return b.String()
}
