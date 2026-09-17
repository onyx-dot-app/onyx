package models

import "encoding/json"

type StreamEvent interface{ EventType() string }

const (
	EventSessionCreated = "session_created"
	EventMessageIDInfo  = "message_id_info"
	EventStop           = "stop"
	EventError          = "error"
	EventItemUpdate     = "item_update"
	EventItemDelta      = "item_delta"
	EventRunUpdate      = "run_update"
	EventHeartbeat      = "chat_heartbeat"
	EventUnknown        = "unknown"
)

type SessionCreatedEvent struct {
	ChatSessionID string `json:"chat_session_id"`
}

func (e SessionCreatedEvent) EventType() string { return EventSessionCreated }

type MessageIDEvent struct {
	UserMessageID          *int `json:"user_message_id,omitempty"`
	ReservedAgentMessageID int  `json:"reserved_assistant_message_id"`
}

func (e MessageIDEvent) EventType() string { return EventMessageIDInfo }

type ItemIdentity struct {
	ResponseID       int    `json:"response_id"`
	RunID            string `json:"run_id"`
	MessageID        string `json:"message_id"`
	PartID           string `json:"part_id"`
	ToolCallID       string `json:"tool_call_id,omitempty"`
	ParentRunID      string `json:"parent_run_id,omitempty"`
	ParentMessageID  string `json:"parent_message_id,omitempty"`
	ParentToolCallID string `json:"parent_tool_call_id,omitempty"`
	AgentID          string `json:"agent_id,omitempty"`
	AgentPath        string `json:"agent_path,omitempty"`
}
type EventContext struct {
	Identity   *ItemIdentity `json:"identity,omitempty"`
	ModelIndex *int          `json:"model_index,omitempty"`
}
type Citation struct {
	CitationNumber int    `json:"citation_number"`
	DocumentID     string `json:"document_id"`
}

type ItemKind string

const (
	ItemText      ItemKind = "text"
	ItemReasoning ItemKind = "reasoning"
	ItemTool      ItemKind = "tool"
)

type ItemStatus string

const (
	StatusPending   ItemStatus = "pending"
	StatusRunning   ItemStatus = "running"
	StatusComplete  ItemStatus = "complete"
	StatusError     ItemStatus = "error"
	StatusCancelled ItemStatus = "cancelled"
	StatusLimit     ItemStatus = "limit"
)

type TextPurpose string

const (
	PurposeAnswer     TextPurpose = "answer"
	PurposePlan       TextPurpose = "plan"
	PurposeReport     TextPurpose = "report"
	PurposeCommentary TextPurpose = "commentary"
)

type DeltaKind string

const (
	DeltaText          DeltaKind = "text"
	DeltaToolOutput    DeltaKind = "tool_output"
	DeltaToolArguments DeltaKind = "tool_arguments"
)

// ChatItem contains the public content used by interactive and saved responses.
type ChatItem struct {
	Kind             ItemKind                   `json:"kind"`
	Status           ItemStatus                 `json:"status"`
	Text             string                     `json:"text,omitempty"`
	Purpose          TextPurpose                `json:"purpose,omitempty"`
	Documents        []SearchDoc                `json:"documents,omitempty"`
	Citations        []Citation                 `json:"citations,omitempty"`
	PreAnswerSeconds *float64                   `json:"pre_answer_seconds,omitempty"`
	Name             string                     `json:"name,omitempty"`
	Arguments        map[string]json.RawMessage `json:"arguments,omitempty"`
	ToolID           *int                       `json:"tool_id,omitempty"`
	Output           string                     `json:"output,omitempty"`
	// Tool metadata remains intact for JSON clients; terminal views read only fields they display.
	Metadata json.RawMessage `json:"metadata,omitempty"`
}
type ItemUpdateEvent struct {
	EventContext
	Item ChatItem `json:"item"`
}

func (e ItemUpdateEvent) EventType() string { return EventItemUpdate }

type ItemDelta struct {
	Kind      DeltaKind         `json:"kind"`
	Text      string            `json:"text,omitempty"`
	Citations []Citation        `json:"citations,omitempty"`
	Name      string            `json:"name,omitempty"`
	Arguments map[string]string `json:"arguments,omitempty"`
	Output    *string           `json:"output,omitempty"`
	Metadata  json.RawMessage   `json:"metadata,omitempty"`
}
type ItemDeltaEvent struct {
	EventContext
	Delta ItemDelta `json:"delta"`
}

func (e ItemDeltaEvent) EventType() string { return EventItemDelta }

type RunUpdateEvent struct {
	EventContext
	Status ItemStatus `json:"status"`
}

func (e RunUpdateEvent) EventType() string { return EventRunUpdate }

type HeartbeatEvent struct{}

func (e HeartbeatEvent) EventType() string { return EventHeartbeat }

type StopEvent struct {
	EventContext
	StopReason *string `json:"stop_reason,omitempty"`
}

func (e StopEvent) EventType() string { return EventStop }

type ErrorEvent struct {
	Error       string  `json:"error"`
	StackTrace  *string `json:"stack_trace,omitempty"`
	IsRetryable bool    `json:"is_retryable"`
	StatusCode  int     `json:"-"`
}

func (e ErrorEvent) EventType() string { return EventError }

type UnknownEvent struct {
	RawData json.RawMessage `json:"raw_data,omitempty"`
}

func (e UnknownEvent) EventType() string { return EventUnknown }
