package tui

import "github.com/onyx-dot-app/onyx/cli/internal/config"

// experimentsText returns the formatted experiments list for the current config.
func (m Model) experimentsText() string {
	return config.ExperimentsText(m.config.Features)
}
