package tui

import (
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

// InitDoneMsg signals that async initialization is complete.
type InitDoneMsg struct {
	Agents []models.AgentSummary
	Err    error
}

// SessionsLoadedMsg carries loaded chat sessions.
type SessionsLoadedMsg struct {
	Sessions []models.ChatSessionDetails
	Err      error
}

// SessionResumedMsg carries a loaded session detail.
type SessionResumedMsg struct {
	Detail *models.ChatSessionDetailResponse
	// Status reports a response that still runs, such as one that waits for
	// an approval.
	Status models.ChatSessionStatus
	// Origin is the stream that asked to reload its session, or nil when the
	// user opened the session.
	Origin <-chan models.StreamEvent
	// Reload names the open chat whose saved session a status read loads, or
	// nil. Its result applies only while that chat stays open and no stream
	// runs.
	Reload *sessionReload
	Err    error
}

// sessionReload is a status read's load of the open chat's saved session.
type sessionReload struct {
	sessionID string
	// responseID is the unseen response that the load shows, or 0.
	responseID int
	// streams is the model's stream count when the load started.
	streams int
}

// FileUploadedMsg carries an uploaded file descriptor.
type FileUploadedMsg struct {
	Descriptor *models.FileDescriptorPayload
	FileName   string
	Err        error
}

// AgentsLoadedMsg carries freshly fetched agents from the API.
type AgentsLoadedMsg struct {
	Agents []models.AgentSummary
	Err    error
}

// ModelsLoadedMsg carries LLM providers fetched from the API. ShowPicker is
// true when the fetch was triggered by /model (open the modal) and false when
// it ran during startup (only resolve the status-bar model name).
type ModelsLoadedMsg struct {
	Response   *models.LLMProviderResponse
	ShowPicker bool
	Err        error
}

// ConfigTestResultMsg carries the result of an async connection test during /configure.
type ConfigTestResultMsg struct {
	Err error
}
