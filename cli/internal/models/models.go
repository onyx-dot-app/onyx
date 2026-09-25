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

// LLMOverride selects a specific model for a chat message, overriding the
// agent's default. ModelConfigurationID routes unambiguously; the name-based
// fields are a fallback for older servers.
type LLMOverride struct {
	ModelConfigurationID *int    `json:"model_configuration_id,omitempty"`
	ModelProvider        *string `json:"model_provider,omitempty"`
	ModelVersion         *string `json:"model_version,omitempty"`
}

// ModelConfiguration is one model offered by an LLM provider.
type ModelConfiguration struct {
	ID                *int    `json:"id"`
	Name              string  `json:"name"`
	IsVisible         bool    `json:"is_visible"`
	DisplayName       *string `json:"display_name"`
	CustomDisplayName *string `json:"custom_display_name"`
}

// Label returns the human-readable name for the model.
func (m ModelConfiguration) Label() string {
	if m.CustomDisplayName != nil && *m.CustomDisplayName != "" {
		return *m.CustomDisplayName
	}
	if m.DisplayName != nil && *m.DisplayName != "" {
		return *m.DisplayName
	}
	return m.Name
}

// LLMProviderDescriptor is an LLM provider visible to the current user.
type LLMProviderDescriptor struct {
	ID                  int                  `json:"id"`
	Name                *string              `json:"name"`
	Provider            string               `json:"provider"`
	ProviderDisplayName string               `json:"provider_display_name"`
	ModelConfigurations []ModelConfiguration `json:"model_configurations"`
}

// DefaultModel identifies the workspace default model.
type DefaultModel struct {
	ProviderID int    `json:"provider_id"`
	ModelName  string `json:"model_name"`
}

// LLMProviderResponse is the response from GET /api/llm/provider.
type LLMProviderResponse struct {
	Providers   []LLMProviderDescriptor `json:"providers"`
	DefaultText *DefaultModel           `json:"default_text"`
}

// SendMessagePayload is the request body for POST /api/chat/send-chat-message.
type SendMessagePayload struct {
	Message          string                   `json:"message"`
	ChatSessionID    *string                  `json:"chat_session_id,omitempty"`
	ChatSessionInfo  *ChatSessionCreationInfo `json:"chat_session_info,omitempty"`
	LLMOverride      *LLMOverride             `json:"llm_override,omitempty"`
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
	Query        string   `json:"query"`
	Sources      []string `json:"sources,omitempty"`
	DocumentSets []string `json:"document_sets,omitempty"`
	// TimeCutoff is an ISO 8601 timestamp. Only documents updated on or after
	// this moment are returned; naive (timezone-less) values are treated as
	// UTC server-side.
	TimeCutoff         *string `json:"time_cutoff,omitempty"`
	PersonaID          *int    `json:"persona_id,omitempty"`
	SkipQueryExpansion bool    `json:"skip_query_expansion,omitempty"`
}

// SearchResult is a single document result from the search API.
//
// Content is the full chunk text the LLM saw for this section. Multiple
// results may share a CitationID when the LLM selected multiple
// non-overlapping sections of the same document.
type SearchResult struct {
	CitationID *int    `json:"citation_id"`
	Title      string  `json:"title"`
	Content    string  `json:"content"`
	Link       *string `json:"link"`
	SourceType string  `json:"source_type"`
	UpdatedAt  *string `json:"updated_at"`
}

// SearchResponse is the response from POST /api/search.
type SearchResponse struct {
	Results []SearchResult `json:"results"`
}
