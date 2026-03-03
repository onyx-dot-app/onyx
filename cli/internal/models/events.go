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
	ChatSessionID string
}

func (e SessionCreatedEvent) EventType() string { return EventSessionCreated }

// MessageIDEvent carries the user and agent message IDs.
type MessageIDEvent struct {
	UserMessageID              *int
	ReservedAgentMessageID int
}

func (e MessageIDEvent) EventType() string { return EventMessageIDInfo }

// StopEvent signals the end of a stream.
type StopEvent struct {
	Placement  *Placement
	StopReason *string
}

func (e StopEvent) EventType() string { return EventStop }

// ErrorEvent signals an error.
type ErrorEvent struct {
	Placement   *Placement
	Error       string
	StackTrace  *string
	IsRetryable bool
}

func (e ErrorEvent) EventType() string { return EventError }

// MessageStartEvent signals the beginning of an agent message.
type MessageStartEvent struct {
	Placement *Placement
	Documents []SearchDoc
}

func (e MessageStartEvent) EventType() string { return EventMessageStart }

// MessageDeltaEvent carries a token of agent content.
type MessageDeltaEvent struct {
	Placement *Placement
	Content   string
}

func (e MessageDeltaEvent) EventType() string { return EventMessageDelta }

// SearchStartEvent signals the beginning of a search.
type SearchStartEvent struct {
	Placement        *Placement
	IsInternetSearch bool
}

func (e SearchStartEvent) EventType() string { return EventSearchStart }

// SearchQueriesEvent carries search queries.
type SearchQueriesEvent struct {
	Placement *Placement
	Queries   []string
}

func (e SearchQueriesEvent) EventType() string { return EventSearchQueries }

// SearchDocumentsEvent carries found documents.
type SearchDocumentsEvent struct {
	Placement *Placement
	Documents []SearchDoc
}

func (e SearchDocumentsEvent) EventType() string { return EventSearchDocuments }

// ReasoningStartEvent signals the beginning of a reasoning block.
type ReasoningStartEvent struct {
	Placement *Placement
}

func (e ReasoningStartEvent) EventType() string { return EventReasoningStart }

// ReasoningDeltaEvent carries reasoning text.
type ReasoningDeltaEvent struct {
	Placement *Placement
	Reasoning string
}

func (e ReasoningDeltaEvent) EventType() string { return EventReasoningDelta }

// ReasoningDoneEvent signals the end of reasoning.
type ReasoningDoneEvent struct {
	Placement *Placement
}

func (e ReasoningDoneEvent) EventType() string { return EventReasoningDone }

// CitationEvent carries citation info.
type CitationEvent struct {
	Placement      *Placement
	CitationNumber int
	DocumentID     string
}

func (e CitationEvent) EventType() string { return EventCitationInfo }

// ToolStartEvent signals the start of a tool usage.
type ToolStartEvent struct {
	Placement *Placement
	Type      string // The specific event type (e.g. "open_url_start")
	ToolName  string
}

func (e ToolStartEvent) EventType() string { return e.Type }

// DeepResearchPlanStartEvent signals the start of a deep research plan.
type DeepResearchPlanStartEvent struct {
	Placement *Placement
}

func (e DeepResearchPlanStartEvent) EventType() string { return EventDeepResearchPlan }

// DeepResearchPlanDeltaEvent carries deep research plan content.
type DeepResearchPlanDeltaEvent struct {
	Placement *Placement
	Content   string
}

func (e DeepResearchPlanDeltaEvent) EventType() string { return EventDeepResearchDelta }

// ResearchAgentStartEvent signals a research sub-task.
type ResearchAgentStartEvent struct {
	Placement    *Placement
	ResearchTask string
}

func (e ResearchAgentStartEvent) EventType() string { return EventResearchAgentStart }

// IntermediateReportStartEvent signals the start of an intermediate report.
type IntermediateReportStartEvent struct {
	Placement *Placement
}

func (e IntermediateReportStartEvent) EventType() string { return EventIntermediateReport }

// IntermediateReportDeltaEvent carries intermediate report content.
type IntermediateReportDeltaEvent struct {
	Placement *Placement
	Content   string
}

func (e IntermediateReportDeltaEvent) EventType() string { return EventIntermediateReportDt }

// UnknownEvent is a catch-all for unrecognized stream data.
type UnknownEvent struct {
	Placement *Placement
	RawData   map[string]any
}

func (e UnknownEvent) EventType() string { return EventUnknown }
