package tui

import (
	tea "github.com/charmbracelet/bubbletea"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

// StreamEventMsg wraps a StreamEvent for Bubble Tea.
type StreamEventMsg struct {
	Event models.StreamEvent
}

// StreamDoneMsg signals the stream has ended.
type StreamDoneMsg struct {
	Err error
}

// WaitForStreamEvent returns a tea.Cmd that reads one event from the channel.
// On channel close, it returns StreamDoneMsg.
func WaitForStreamEvent(ch <-chan models.StreamEvent) tea.Cmd {
	return func() tea.Msg {
		event, ok := <-ch
		if !ok {
			return StreamDoneMsg{}
		}
		return StreamEventMsg{Event: event}
	}
}
