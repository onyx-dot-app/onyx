package models

// StreamEvent is the interface for all parsed stream events.
type StreamEvent interface {
	EventType() string
}

// Event type constants matching the Python StreamEventType enum.
const (
	EventSessionCreated       = "session_created"
	EventMessageIDInfo        = "message_id_info"
	EventStop                 = "stop"
	EventError                = "error"
	EventMessageStart         = "message_start"
	EventMessageDelta         = "message_delta"
	EventSearchStart          = "search_tool_start"
	EventSearchQueries        = "search_tool_queries_delta"
	EventSearchDocuments      = "search_tool_documents_delta"
	EventReasoningStart       = "reasoning_start"
	EventReasoningDelta       = "reasoning_delta"
	EventReasoningDone        = "reasoning_done"
	EventCitationInfo         = "citation_info"
	EventOpenURLStart         = "open_url_start"
	EventImageGenStart        = "image_generation_start"
	EventPythonToolStart      = "python_tool_start"
	EventCustomToolStart      = "custom_tool_start"
	EventFileReaderStart      = "file_reader_start"
	EventDeepResearchPlan     = "deep_research_plan_start"
	EventDeepResearchDelta    = "deep_research_plan_delta"
	EventResearchAgentStart   = "research_agent_start"
	EventIntermediateReport   = "intermediate_report_start"
	EventIntermediateReportDt = "intermediate_report_delta"
	EventUnknown              = "unknown"
)

// SessionCreatedEvent is emitted when a new chat session is created.
type SessionCreatedEvent struct {
	ChatSessionID string `json:"chat_session_id"`
}

func (e SessionCreatedEvent) EventType() string { return EventSessionCreated }

// MessageIDEvent carries the user and agent message IDs.
type MessageIDEvent struct {
	UserMessageID          *int `json:"user_message_id,omitempty"`
	ReservedAgentMessageID int  `json:"reserved_agent_message_id"`
}

func (e MessageIDEvent) EventType() string { return EventMessageIDInfo }

// StopEvent signals the end of a stream.
type StopEvent struct {
	Placement  *Placement `json:"placement,omitempty"`
	StopReason *string    `json:"stop_reason,omitempty"`
}

func (e StopEvent) EventType() string { return EventStop }

// ErrorEvent signals an error.
type ErrorEvent struct {
	Placement   *Placement `json:"placement,omitempty"`
	Error       string     `json:"error"`
	StackTrace  *string    `json:"stack_trace,omitempty"`
	IsRetryable bool       `json:"is_retryable"`
}

func (e ErrorEvent) EventType() string { return EventError }

// MessageStartEvent signals the beginning of an agent message.
type MessageStartEvent struct {
	Placement *Placement  `json:"placement,omitempty"`
	Documents []SearchDoc `json:"documents,omitempty"`
}

func (e MessageStartEvent) EventType() string { return EventMessageStart }

// MessageDeltaEvent carries a token of agent content.
type MessageDeltaEvent struct {
	Placement *Placement `json:"placement,omitempty"`
	Content   string     `json:"content"`
}

func (e MessageDeltaEvent) EventType() string { return EventMessageDelta }

// SearchStartEvent signals the beginning of a search.
type SearchStartEvent struct {
	Placement        *Placement `json:"placement,omitempty"`
	IsInternetSearch bool       `json:"is_internet_search"`
}

func (e SearchStartEvent) EventType() string { return EventSearchStart }

// SearchQueriesEvent carries search queries.
type SearchQueriesEvent struct {
	Placement *Placement `json:"placement,omitempty"`
	Queries   []string   `json:"queries"`
}

func (e SearchQueriesEvent) EventType() string { return EventSearchQueries }

// SearchDocumentsEvent carries found documents.
type SearchDocumentsEvent struct {
	Placement *Placement  `json:"placement,omitempty"`
	Documents []SearchDoc `json:"documents"`
}

func (e SearchDocumentsEvent) EventType() string { return EventSearchDocuments }

// ReasoningStartEvent signals the beginning of a reasoning block.
type ReasoningStartEvent struct {
	Placement *Placement `json:"placement,omitempty"`
}

func (e ReasoningStartEvent) EventType() string { return EventReasoningStart }

// ReasoningDeltaEvent carries reasoning text.
type ReasoningDeltaEvent struct {
	Placement *Placement `json:"placement,omitempty"`
	Reasoning string     `json:"reasoning"`
}

func (e ReasoningDeltaEvent) EventType() string { return EventReasoningDelta }

// ReasoningDoneEvent signals the end of reasoning.
type ReasoningDoneEvent struct {
	Placement *Placement `json:"placement,omitempty"`
}

func (e ReasoningDoneEvent) EventType() string { return EventReasoningDone }

// CitationEvent carries citation info.
type CitationEvent struct {
	Placement      *Placement `json:"placement,omitempty"`
	CitationNumber int        `json:"citation_number"`
	DocumentID     string     `json:"document_id"`
}

func (e CitationEvent) EventType() string { return EventCitationInfo }

// ToolStartEvent signals the start of a tool usage.
type ToolStartEvent struct {
	Placement *Placement `json:"placement,omitempty"`
	Type      string     `json:"type"`
	ToolName  string     `json:"tool_name"`
}

func (e ToolStartEvent) EventType() string { return e.Type }

// DeepResearchPlanStartEvent signals the start of a deep research plan.
type DeepResearchPlanStartEvent struct {
	Placement *Placement `json:"placement,omitempty"`
}

func (e DeepResearchPlanStartEvent) EventType() string { return EventDeepResearchPlan }

// DeepResearchPlanDeltaEvent carries deep research plan content.
type DeepResearchPlanDeltaEvent struct {
	Placement *Placement `json:"placement,omitempty"`
	Content   string     `json:"content"`
}

func (e DeepResearchPlanDeltaEvent) EventType() string { return EventDeepResearchDelta }

// ResearchAgentStartEvent signals a research sub-task.
type ResearchAgentStartEvent struct {
	Placement    *Placement `json:"placement,omitempty"`
	ResearchTask string     `json:"research_task"`
}

func (e ResearchAgentStartEvent) EventType() string { return EventResearchAgentStart }

// IntermediateReportStartEvent signals the start of an intermediate report.
type IntermediateReportStartEvent struct {
	Placement *Placement `json:"placement,omitempty"`
}

func (e IntermediateReportStartEvent) EventType() string { return EventIntermediateReport }

// IntermediateReportDeltaEvent carries intermediate report content.
type IntermediateReportDeltaEvent struct {
	Placement *Placement `json:"placement,omitempty"`
	Content   string     `json:"content"`
}

func (e IntermediateReportDeltaEvent) EventType() string { return EventIntermediateReportDt }

// UnknownEvent is a catch-all for unrecognized stream data.
type UnknownEvent struct {
	Placement *Placement     `json:"placement,omitempty"`
	RawData   map[string]any `json:"raw_data,omitempty"`
}

func (e UnknownEvent) EventType() string { return EventUnknown }
