package tui

import (
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

// InitDoneMsg signals that async initialization is complete.
type InitDoneMsg struct {
	Agents []models.AgentSummary
	Err      error
}

// SessionsLoadedMsg carries loaded chat sessions.
type SessionsLoadedMsg struct {
	Sessions []models.ChatSessionDetails
	Err      error
}

// SessionResumedMsg carries a loaded session detail.
type SessionResumedMsg struct {
	Detail *models.ChatSessionDetailResponse
	Err    error
}

// FileUploadedMsg carries an uploaded file descriptor.
type FileUploadedMsg struct {
	Descriptor *models.FileDescriptorPayload
	FileName   string
	Err        error
}

// InfoMsg is a simple informational message for display.
type InfoMsg struct {
	Text string
}

// ErrorMsg wraps an error for display.
type ErrorMsg struct {
	Err error
}
