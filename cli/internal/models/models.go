// Package models defines API request/response types for the Onyx CLI.
package models

// AgentSummary represents an agent from the API.
type AgentSummary struct {
	ID               int    `json:"id"`
	Name             string `json:"name"`
	Description      string `json:"description"`
	IsDefaultPersona bool   `json:"is_default_persona"`
	IsVisible        bool   `json:"is_listed"`
}

// ChatSessionDetails is a session with timestamps as strings.
type ChatSessionDetails struct {
	ID        string  `json:"id"`
	Name      *string `json:"name"`
	AgentID *int    `json:"persona_id"`
	Created   string  `json:"time_created"`
	Updated   string  `json:"time_updated"`
}

// ChatMessageDetail is a single message in a session.
type ChatMessageDetail struct {
	MessageID          int     `json:"message_id"`
	ParentMessage      *int    `json:"parent_message"`
	LatestChildMessage *int    `json:"latest_child_message"`
	Message            string  `json:"message"`
	MessageType        string  `json:"message_type"`
	TimeSent           string  `json:"time_sent"`
	Error              *string `json:"error"`
}

// ChatSessionDetailResponse is the full session detail from the API.
type ChatSessionDetailResponse struct {
	ChatSessionID string              `json:"chat_session_id"`
	Description   *string             `json:"description"`
	AgentID     *int                `json:"persona_id"`
	AgentName   *string             `json:"persona_name"`
	Messages      []ChatMessageDetail `json:"messages"`
}

// ChatFileType represents a file type for uploads.
type ChatFileType string

const (
	ChatFileImage     ChatFileType = "image"
	ChatFileDoc       ChatFileType = "document"
	ChatFilePlainText ChatFileType = "plain_text"
	ChatFileCSV       ChatFileType = "csv"
)

// FileDescriptorPayload is a file descriptor for send-message requests.
type FileDescriptorPayload struct {
	ID   string       `json:"id"`
	Type ChatFileType `json:"type"`
	Name string       `json:"name,omitempty"`
}

// UserFileSnapshot represents an uploaded file.
type UserFileSnapshot struct {
	ID           string       `json:"id"`
	Name         string       `json:"name"`
	FileID       string       `json:"file_id"`
	ChatFileType ChatFileType `json:"chat_file_type"`
}

// CategorizedFilesSnapshot is the response from file upload.
type CategorizedFilesSnapshot struct {
	UserFiles []UserFileSnapshot `json:"user_files"`
}

// ChatSessionCreationInfo is included when creating a new session inline.
type ChatSessionCreationInfo struct {
	AgentID int `json:"persona_id"`
}

// SendMessagePayload is the request body for POST /api/chat/send-chat-message.
type SendMessagePayload struct {
	Message          string                   `json:"message"`
	ChatSessionID    *string                  `json:"chat_session_id,omitempty"`
	ChatSessionInfo  *ChatSessionCreationInfo `json:"chat_session_info,omitempty"`
	ParentMessageID  *int                     `json:"parent_message_id"`
	FileDescriptors  []FileDescriptorPayload `json:"file_descriptors"`
	Origin           string                   `json:"origin"`
	IncludeCitations bool                     `json:"include_citations"`
	Stream           bool                     `json:"stream"`
}

// SearchDoc represents a document found during search.
type SearchDoc struct {
	DocumentID         string  `json:"document_id"`
	SemanticIdentifier string  `json:"semantic_identifier"`
	Link               *string `json:"link"`
	SourceType         string  `json:"source_type"`
}

// Placement indicates where a stream event belongs in the conversation.
type Placement struct {
	TurnIndex    int  `json:"turn_index"`
	TabIndex     int  `json:"tab_index"`
	SubTurnIndex *int `json:"sub_turn_index"`
}

// SearchRequest is the request body for POST /api/search.
type SearchRequest struct {
	Query              string   `json:"query"`
	Sources            []string `json:"sources,omitempty"`
	DocumentSets       []string `json:"document_sets,omitempty"`
	TimeCutoffDays     *int     `json:"time_cutoff_days,omitempty"`
	NumResults         int      `json:"num_results,omitempty"`
	PersonaID          *int     `json:"persona_id,omitempty"`
	SkipQueryExpansion bool     `json:"skip_query_expansion,omitempty"`
}

// SearchResult is a single document result from the search API.
type SearchResult struct {
	CitationID *int     `json:"citation_id"`
	DocumentID string   `json:"document_id"`
	ChunkInd   int      `json:"chunk_ind"`
	Title      string   `json:"title"`
	Blurb      string   `json:"blurb"`
	Link       *string  `json:"link"`
	SourceType string   `json:"source_type"`
	Score      *float64 `json:"score"`
	UpdatedAt  *string  `json:"updated_at"`
}

// SearchResponse is the response from POST /api/search.
type SearchResponse struct {
	Results         []SearchResult `json:"results"`
	LLMFacingText   string         `json:"llm_facing_text"`
	CitationMapping map[int]string `json:"citation_mapping"`
}
