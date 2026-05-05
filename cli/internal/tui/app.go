// Package tui implements the Bubble Tea TUI for Onyx CLI.
package tui

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/config"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
)

// Model is the root Bubble Tea model.
type Model struct {
	config config.OnyxCliConfig
	client *api.Client

	viewport *viewport
	input    inputModel
	status   statusBar

	width  int
	height int

	// Chat state
	chatSessionID   *string
	agentID       int
	agentName     string
	agents        []models.AgentSummary
	parentMessageID *int
	isStreaming      bool
	streamCancel    context.CancelFunc
	streamCh        <-chan models.StreamEvent
	citations       map[int]string
	attachedFiles   []models.FileDescriptorPayload
	needsRename     bool
	agentStarted bool

	// Quit state
	quitPending    bool
	splashShown    bool
	initInputReady bool // true once terminal init responses have passed
}

// NewModel creates a new TUI model.
func NewModel(cfg config.OnyxCliConfig) Model {
	client := api.NewClient(cfg)
	parentID := -1

	return Model{
		config:          cfg,
		client:          client,
		viewport:        newViewport(80, cfg.Features.StreamMarkdownEnabled()),
		input:           newInputModel(),
		status:          newStatusBar(),
		agentID:       cfg.DefaultAgentID,
		agentName:     "Default",
		parentMessageID: &parentID,
		citations:       make(map[int]string),
	}
}

// Init initializes the model.
func (m Model) Init() tea.Cmd {
	return loadAgentsCmd(m.client)
}

// Update handles messages.
func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	// Filter out terminal query responses (OSC 11 background color, cursor
	// position reports, etc.) that arrive as key events with raw escape content.
	// These arrive split across multiple key events, so we use a brief window
	// after startup to swallow them all.
	if keyMsg, ok := msg.(tea.KeyMsg); ok && !m.initInputReady {
		// During init, drop ALL key events — they're terminal query responses
		_ = keyMsg
		return m, nil
	}

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.viewport.setWidth(msg.Width)
		m.status.setWidth(msg.Width)
		m.input.textInput.Width = msg.Width - 4
		if !m.splashShown {
			m.splashShown = true
			// bottomHeight = sep + input + sep + status = 4 (approx)
			viewportHeight := msg.Height - 4
			if viewportHeight < 1 {
				viewportHeight = msg.Height
			}
			m.viewport.addSplash(viewportHeight)
			// Delay input focus to let terminal query responses flush
			return m, tea.Tick(100*time.Millisecond, func(time.Time) tea.Msg {
				return inputReadyMsg{}
			})
		}
		return m, nil

	case tea.MouseMsg:
		switch msg.Button {
		case tea.MouseButtonWheelUp:
			m.viewport.scrollUp(3, m.viewportHeight())
			return m, nil
		case tea.MouseButtonWheelDown:
			m.viewport.scrollDown(3)
			return m, nil
		}

	case tea.KeyMsg:
		return m.handleKey(msg)

	case submitMsg:
		return m.handleSubmit(msg.text)

	case fileDropMsg:
		return m.handleFileDrop(msg.path)

	case InitDoneMsg:
		return m.handleInitDone(msg)

	case api.StreamEventMsg:
		return m.handleStreamEvent(msg)

	case api.StreamDoneMsg:
		return m.handleStreamDone(msg)

	case AgentsLoadedMsg:
		return m.handleAgentsLoaded(msg)

	case SessionsLoadedMsg:
		return m.handleSessionsLoaded(msg)

	case SessionResumedMsg:
		return m.handleSessionResumed(msg)

	case FileUploadedMsg:
		return m.handleFileUploaded(msg)

	case inputReadyMsg:
		m.initInputReady = true
		m.input.textInput.Focus()
		m.input.textInput.SetValue("")
		return m, m.input.textInput.Cursor.BlinkCmd()

	case resetQuitMsg:
		m.quitPending = false
		return m, nil
	}

	// Only forward messages to the text input after it's been focused
	if m.splashShown {
		var cmd tea.Cmd
		m.input, cmd = m.input.update(msg)
		return m, cmd
	}
	return m, nil
}

// View renders the UI.
// viewportHeight returns the number of visible chat rows, accounting for the
// dynamic bottom area (separator, menu, file badges, input, status bar).
func (m Model) viewportHeight() int {
	menuHeight := 0
	if m.input.menuVisible {
		menuHeight = len(m.input.menuItems)
	}
	fileHeight := 0
	if len(m.input.attachedFiles) > 0 {
		fileHeight = 1
	}
	h := m.height - (1 + menuHeight + fileHeight + 1 + 1 + 1)
	if h < 1 {
		return 1
	}
	return h
}

func (m Model) View() string {
	if m.width == 0 || m.height == 0 {
		return ""
	}

	separator := lipgloss.NewStyle().Foreground(separatorColor).Render(
		strings.Repeat("─", m.width),
	)

	menuView := m.input.viewMenu(m.width)
	viewportHeight := m.viewportHeight()

	var parts []string
	parts = append(parts, m.viewport.view(viewportHeight))
	parts = append(parts, separator)
	if menuView != "" {
		parts = append(parts, menuView)
	}
	parts = append(parts, m.input.viewInput())
	parts = append(parts, separator)
	parts = append(parts, m.status.view())

	return strings.Join(parts, "\n")
}

// handleKey processes keyboard input.
func (m Model) handleKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	switch msg.Type {
	case tea.KeyEscape:
		// Cancel streaming or close menu
		if m.input.menuVisible {
			m.input.menuVisible = false
			return m, nil
		}
		if m.isStreaming {
			return m.cancelStream()
		}
		// Dismiss picker
		if m.viewport.pickerActive {
			m.viewport.pickerActive = false
			return m, nil
		}
		return m, nil

	case tea.KeyCtrlD:
		// If streaming, cancel first; require a fresh Ctrl+D pair to quit
		if m.isStreaming {
			return m.cancelStream()
		}
		if m.quitPending {
			return m, tea.Quit
		}
		m.quitPending = true
		m.viewport.addInfo("Press Ctrl+D again to quit.")
		return m, tea.Tick(2*time.Second, func(t time.Time) tea.Msg {
			return resetQuitMsg{}
		})

	case tea.KeyCtrlO:
		m.viewport.showSources = !m.viewport.showSources
		return m, nil

	case tea.KeyEnter:
		if m.viewport.pickerActive {
			if len(m.viewport.pickerItems) > 0 {
				item := m.viewport.pickerItems[m.viewport.pickerIndex]
				if item.id == "" {
					return m, nil
				}
				m.viewport.pickerActive = false
				switch m.viewport.pickerType {
				case pickerSession:
					return cmdResume(m, item.id)
				case pickerAgent:
					return cmdSelectAgent(m, item.id)
				}
			}
			return m, nil
		}

	case tea.KeyUp:
		if m.viewport.pickerActive {
			if m.viewport.pickerIndex > 0 {
				m.viewport.pickerIndex--
			}
			return m, nil
		}

	case tea.KeyDown:
		if m.viewport.pickerActive {
			if m.viewport.pickerIndex < len(m.viewport.pickerItems)-1 {
				m.viewport.pickerIndex++
			}
			return m, nil
		}

	case tea.KeyPgUp:
		m.viewport.scrollUp(m.viewportHeight()/2, m.viewportHeight())
		return m, nil

	case tea.KeyPgDown:
		m.viewport.scrollDown(m.viewportHeight() / 2)
		return m, nil

	case tea.KeyShiftUp:
		m.viewport.scrollUp(3, m.viewportHeight())
		return m, nil

	case tea.KeyShiftDown:
		m.viewport.scrollDown(3)
		return m, nil
	}

	// Pass to input
	var cmd tea.Cmd
	m.input, cmd = m.input.update(msg)
	return m, cmd
}

func (m Model) handleSubmit(text string) (tea.Model, tea.Cmd) {
	if strings.HasPrefix(text, "/") {
		return handleSlashCommand(m, text)
	}
	return m.sendMessage(text)
}

func (m Model) handleFileDrop(path string) (tea.Model, tea.Cmd) {
	return cmdAttach(m, path)
}

func (m Model) cancelStream() (Model, tea.Cmd) {
	if m.streamCancel != nil {
		m.streamCancel()
	}
	if m.chatSessionID != nil {
		sid := *m.chatSessionID
		go m.client.StopChatSession(context.Background(), sid)
	}
	m, cmd := m.finishStream(nil)
	m.viewport.addInfo("Generation stopped.")
	return m, cmd
}

func (m Model) sendMessage(message string) (Model, tea.Cmd) {
	if m.isStreaming {
		return m, nil
	}

	m.viewport.addUserMessage(message)
	m.viewport.startAgent()

	// Prepare file descriptors
	fileDescs := make([]models.FileDescriptorPayload, len(m.attachedFiles))
	copy(fileDescs, m.attachedFiles)
	m.attachedFiles = nil
	m.input.clearFiles()

	m.isStreaming = true
	m.agentStarted = false
	m.citations = make(map[int]string)
	m.status.setStreaming(true)

	ctx, cancel := context.WithCancel(context.Background())
	m.streamCancel = cancel

	ch := m.client.SendMessageStream(
		ctx,
		message,
		m.chatSessionID,
		m.agentID,
		m.parentMessageID,
		fileDescs,
	)
	m.streamCh = ch

	return m, api.WaitForStreamEvent(ch)
}

func (m Model) handleStreamEvent(msg api.StreamEventMsg) (tea.Model, tea.Cmd) {
	// Ignore stale events after cancellation
	if !m.isStreaming {
		return m, nil
	}
	switch e := msg.Event.(type) {
	case models.SessionCreatedEvent:
		m.chatSessionID = &e.ChatSessionID
		m.needsRename = true
		m.status.setSession(e.ChatSessionID)

	case models.MessageIDEvent:
		m.parentMessageID = &e.ReservedAgentMessageID

	case models.MessageStartEvent:
		m.agentStarted = true

	case models.MessageDeltaEvent:
		m.agentStarted = true
		m.viewport.appendToken(e.Content)

	case models.SearchStartEvent:
		if e.IsInternetSearch {
			m.viewport.addInfo("Web search…")
		} else {
			m.viewport.addInfo("Searching…")
		}

	case models.SearchQueriesEvent:
		if len(e.Queries) > 0 {
			queries := e.Queries
			if len(queries) > 3 {
				queries = queries[:3]
			}
			parts := make([]string, len(queries))
			for i, q := range queries {
				parts[i] = "\"" + q + "\""
			}
			m.viewport.addInfo("Searching: " + strings.Join(parts, ", "))
		}

	case models.SearchDocumentsEvent:
		count := len(e.Documents)
		suffix := "s"
		if count == 1 {
			suffix = ""
		}
		m.viewport.addInfo("Found " + strconv.Itoa(count) + " document" + suffix)

	case models.ReasoningStartEvent:
		m.viewport.addInfo("Thinking…")

	case models.ReasoningDeltaEvent:
		// We don't display reasoning text, just the indicator

	case models.ReasoningDoneEvent:
		// No-op

	case models.CitationEvent:
		m.citations[e.CitationNumber] = e.DocumentID

	case models.ToolStartEvent:
		m.viewport.addInfo("Using " + e.ToolName + "…")

	case models.ResearchAgentStartEvent:
		m.viewport.addInfo("Researching: " + e.ResearchTask)

	case models.DeepResearchPlanDeltaEvent:
		m.viewport.appendToken(e.Content)

	case models.IntermediateReportDeltaEvent:
		m.viewport.appendToken(e.Content)

	case models.StopEvent:
		return m.finishStream(nil)

	case models.ErrorEvent:
		m.viewport.addError(e.Error)
		return m.finishStream(nil)
	}

	return m, api.WaitForStreamEvent(m.streamCh)
}

func (m Model) handleStreamDone(msg api.StreamDoneMsg) (tea.Model, tea.Cmd) {
	// Ignore if already cancelled
	if !m.isStreaming {
		return m, nil
	}
	return m.finishStream(msg.Err)
}

func (m Model) finishStream(err error) (Model, tea.Cmd) {
	m.viewport.finishAgent()
	if m.agentStarted && len(m.citations) > 0 {
		m.viewport.addCitations(m.citations)
	}
	m.isStreaming = false
	m.agentStarted = false
	m.status.setStreaming(false)
	if m.streamCancel != nil {
		m.streamCancel()
	}
	m.streamCancel = nil
	m.streamCh = nil

	// Auto-rename new sessions
	if m.needsRename && m.chatSessionID != nil {
		m.needsRename = false
		sessionID := *m.chatSessionID
		client := m.client
		go func() {
			_, _ = client.RenameChatSession(context.Background(), sessionID, nil)
		}()
	}

	return m, nil
}

func (m Model) handleInitDone(msg InitDoneMsg) (tea.Model, tea.Cmd) {
	if msg.Err != nil {
		m.viewport.addWarning("Could not load agents. Using default.")
	} else {
		m.agents = msg.Agents
		for _, p := range m.agents {
			if p.ID == m.agentID {
				m.agentName = p.Name
				break
			}
		}
	}
	m.status.setServer(m.config.ServerURL)
	m.status.setAgent(m.agentName)
	return m, nil
}

func (m Model) handleAgentsLoaded(msg AgentsLoadedMsg) (tea.Model, tea.Cmd) {
	if msg.Err != nil {
		m.viewport.addError("Could not load agents: " + msg.Err.Error())
		return m, nil
	}
	m.agents = msg.Agents
	if len(m.agents) == 0 {
		m.viewport.addInfo("No agents available.")
		return m, nil
	}

	m.viewport.addInfo("Select an agent (Enter to select, Esc to cancel):")

	var items []pickerItem
	for _, p := range m.agents {
		label := fmt.Sprintf("%d: %s", p.ID, p.Name)
		if p.ID == m.agentID {
			label += " *"
		}
		desc := p.Description
		if len(desc) > 50 {
			desc = desc[:50] + "..."
		}
		if desc != "" {
			label += " - " + desc
		}
		items = append(items, pickerItem{
			id:    strconv.Itoa(p.ID),
			label: label,
		})
	}
	m.viewport.showPicker(pickerAgent, items)
	return m, nil
}

func (m Model) handleSessionsLoaded(msg SessionsLoadedMsg) (tea.Model, tea.Cmd) {
	if msg.Err != nil {
		m.viewport.addError("Could not load sessions: " + msg.Err.Error())
		return m, nil
	}
	if len(msg.Sessions) == 0 {
		m.viewport.addInfo("No previous sessions found.")
		return m, nil
	}

	m.viewport.addInfo("Select a session to resume (Enter to select, Esc to cancel):")

	const maxSessions = 15
	var items []pickerItem
	for i, s := range msg.Sessions {
		if i >= maxSessions {
			break
		}
		name := "Untitled"
		if s.Name != nil && *s.Name != "" {
			name = *s.Name
		}
		sid := s.ID
		if len(sid) > 8 {
			sid = sid[:8]
		}
		items = append(items, pickerItem{
			id:    s.ID,
			label: sid + "  " + name + "  (" + s.Created + ")",
		})
	}
	if len(msg.Sessions) > maxSessions {
		items = append(items, pickerItem{
			id:    "",
			label: fmt.Sprintf("… and %d more (use /resume <id> to open)", len(msg.Sessions)-maxSessions),
		})
	}
	m.viewport.showPicker(pickerSession, items)
	return m, nil
}

func (m Model) handleSessionResumed(msg SessionResumedMsg) (tea.Model, tea.Cmd) {
	if msg.Err != nil {
		m.viewport.addError("Could not load session: " + msg.Err.Error())
		return m, nil
	}

	// Cancel any in-progress stream before replacing the session
	if m.isStreaming {
		m, _ = m.cancelStream()
	}

	detail := msg.Detail
	m.chatSessionID = &detail.ChatSessionID
	m.viewport.clearDisplay()
	m.status.setSession(detail.ChatSessionID)

	if detail.AgentName != nil {
		m.agentName = *detail.AgentName
		m.status.setAgent(*detail.AgentName)
	}
	if detail.AgentID != nil {
		m.agentID = *detail.AgentID
	}

	// Replay messages
	for _, chatMsg := range detail.Messages {
		switch chatMsg.MessageType {
		case "user":
			m.viewport.addUserMessage(chatMsg.Message)
		case "assistant":
			m.viewport.startAgent()
			m.viewport.appendToken(chatMsg.Message)
			m.viewport.finishAgent()
		}
	}

	// Set parent to last message
	if len(detail.Messages) > 0 {
		lastID := detail.Messages[len(detail.Messages)-1].MessageID
		m.parentMessageID = &lastID
	}

	desc := "Untitled"
	if detail.Description != nil && *detail.Description != "" {
		desc = *detail.Description
	}
	m.viewport.addInfo("Resumed session: " + desc)
	return m, nil
}

func (m Model) handleFileUploaded(msg FileUploadedMsg) (tea.Model, tea.Cmd) {
	if msg.Err != nil {
		m.viewport.addError("Upload failed: " + msg.Err.Error())
		return m, nil
	}
	m.attachedFiles = append(m.attachedFiles, *msg.Descriptor)
	m.input.addFile(msg.FileName)
	m.viewport.addInfo("Attached: " + msg.FileName)
	return m, nil
}

type inputReadyMsg struct{}
type resetQuitMsg struct{}

