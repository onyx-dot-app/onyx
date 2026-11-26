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
	EventCustomToolStart      = "custom_tool_start"
	EventDeepResearchPlan     = "deep_research_plan_start"
	EventDeepResearchDelta    = "deep_research_plan_delta"
	EventResearchAgentStart   = "research_agent_start"
	EventIntermediateReport   = "intermediate_report_start"
	EventIntermediateReportDt = "intermediate_report_delta"
	EventToolApprovalRequest  = "tool_approval_request"
	EventToolApprovalResolved = "tool_approval_resolved"
	EventToolQuestionRequest  = "tool_question_request"
	EventToolQuestionResolved = "tool_question_resolved"
	EventStreamCursor         = "stream_cursor"
	EventStreamUnavailable    = "stream_unavailable"
	EventReplayEnd            = "replay_end"
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
	ReservedAgentMessageID int  `json:"reserved_assistant_message_id"`
}

func (e MessageIDEvent) EventType() string { return EventMessageIDInfo }

// StopReasonAwaitingUser ends the stream of a response that waits for the
// user: tool approval decisions, or answers to the agent's questions. The
// response continues on a new stream after them.
const StopReasonAwaitingUser = "awaiting_user"

// StopEvent signals the end of a stream.
type StopEvent struct {
	Placement  *Placement `json:"placement,omitempty"`
	StopReason *string    `json:"stop_reason,omitempty"`
}

func (e StopEvent) EventType() string { return EventStop }

// AwaitingUser reports a stream that stopped while its response waits for the
// user.
func (e StopEvent) AwaitingUser() bool {
	return e.StopReason != nil && *e.StopReason == StopReasonAwaitingUser
}

// ErrorEvent signals an error.
type ErrorEvent struct {
	Placement   *Placement `json:"placement,omitempty"`
	Error       string     `json:"error"`
	StackTrace  *string    `json:"stack_trace,omitempty"`
	IsRetryable bool       `json:"is_retryable"`
	StatusCode  int        `json:"-"`                    // HTTP status for client-side errors; zero for server-pushed stream errors
	ErrorCode   string     `json:"error_code,omitempty"` // Onyx error code of a rejected request, e.g. APPROVAL_PENDING
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

// ToolApprovalRequestEvent asks the user to approve one tool call. The tool
// call waits until the user decides or stops the response. Arguments come
// from the model and are untrusted.
type ToolApprovalRequestEvent struct {
	Placement   *Placement     `json:"placement,omitempty"`
	ApprovalID  string         `json:"approval_id"`
	ToolCallID  string         `json:"tool_call_id"`
	ToolName    string         `json:"tool_name"`
	DisplayName string         `json:"display_name"`
	Arguments   map[string]any `json:"arguments"`
	// AgentName names the background agent that asks; empty for the chat's
	// own agent. An agent's request never blocks the chat.
	AgentName string `json:"agent_name,omitempty"`
}

func (e ToolApprovalRequestEvent) EventType() string { return EventToolApprovalRequest }

// Outcomes of a tool approval request.
const (
	ApprovalOutcomeApproved = "approved"
	// ApprovalOutcomeApprovedForChat: a grant for the session's later calls of
	// the tool approved the request.
	ApprovalOutcomeApprovedForChat = "approved_for_chat"
	ApprovalOutcomeRejected        = "rejected"
	ApprovalOutcomeDisabled        = "disabled"
	ApprovalOutcomeCancelled       = "cancelled"
)

// ToolApprovalResolvedEvent reports how an approval request ended.
type ToolApprovalResolvedEvent struct {
	Placement  *Placement `json:"placement,omitempty"`
	ApprovalID string     `json:"approval_id"`
	Outcome    string     `json:"outcome"`
}

func (e ToolApprovalResolvedEvent) EventType() string { return EventToolApprovalResolved }

// ToolQuestionOption is one choice of a question.
type ToolQuestionOption struct {
	Label       string `json:"label"`
	Description string `json:"description"`
}

// ToolQuestion is one question that the agent asks the user.
type ToolQuestion struct {
	ID       string               `json:"id"`
	Header   string               `json:"header"`
	Question string               `json:"question"`
	Options  []ToolQuestionOption `json:"options"`
}

// ToolQuestionRequestEvent asks the user the agent's questions. The response
// waits until the user answers or stops it. The questions come from the model
// and are untrusted.
type ToolQuestionRequestEvent struct {
	Placement         *Placement     `json:"placement,omitempty"`
	QuestionRequestID string         `json:"question_request_id"`
	ToolCallID        string         `json:"tool_call_id"`
	Questions         []ToolQuestion `json:"questions"`
}

func (e ToolQuestionRequestEvent) EventType() string { return EventToolQuestionRequest }

// Outcomes of a question request, and how the user answered.
const (
	QuestionOutcomeAnswered = "answered"
	// QuestionOutcomeCancelled: the response stopped before the answer.
	QuestionOutcomeCancelled   = "cancelled"
	QuestionAnsweredViaCard    = "card"
	QuestionAnsweredViaMessage = "message"
)

// ToolQuestionResolvedEvent reports how a question request ended: answered
// on its card (Answers) or by a message that the user typed (Message), or
// cancelled.
type ToolQuestionResolvedEvent struct {
	Placement         *Placement           `json:"placement,omitempty"`
	QuestionRequestID string               `json:"question_request_id"`
	Outcome           string               `json:"outcome"`
	AnsweredVia       string               `json:"answered_via,omitempty"`
	Answers           []ToolQuestionAnswer `json:"answers,omitempty"`
	Message           string               `json:"message,omitempty"`
}

func (e ToolQuestionResolvedEvent) EventType() string { return EventToolQuestionResolved }

// StreamCursorEvent ends a complete batch of a replayed response. A request
// for the same stream from NextCursor continues after the batch.
type StreamCursorEvent struct {
	StreamID       int  `json:"stream_id"`
	NextCursor     int  `json:"next_cursor"`
	ReplayComplete bool `json:"replay_complete"`
}

func (e StreamCursorEvent) EventType() string { return EventStreamCursor }

// StreamUnavailableEvent reports that the server has nothing to serve at the
// requested cursor of a resumed response: no running response, another
// response, or no buffer. Requesting the same response again does not help.
type StreamUnavailableEvent struct{}

func (e StreamUnavailableEvent) EventType() string { return EventStreamUnavailable }

// ReplayEndEvent ends the replayed prefix of a stream that continues a
// response. The events after it are new.
type ReplayEndEvent struct{}

func (e ReplayEndEvent) EventType() string { return EventReplayEnd }

// UnknownEvent is a catch-all for unrecognized stream data.
type UnknownEvent struct {
	Placement *Placement     `json:"placement,omitempty"`
	RawData   map[string]any `json:"raw_data,omitempty"`
}

func (e UnknownEvent) EventType() string { return EventUnknown }
