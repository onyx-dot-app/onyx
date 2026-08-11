package client

import (
	"context"
	"net/http"
)

// Settings mirrors the backend model, for decoding GET responses only;
// writes go through PatchSettings with a sparse body.
type Settings struct {
	MaximumChatRetentionDays          *float64 `json:"maximum_chat_retention_days"`
	CompanyName                       *string  `json:"company_name"`
	CompanyDescription                *string  `json:"company_description"`
	GPUEnabled                        *bool    `json:"gpu_enabled"`
	ApplicationStatus                 string   `json:"application_status"`
	AnonymousUserEnabled              *bool    `json:"anonymous_user_enabled"`
	InviteOnlyEnabled                 bool     `json:"invite_only_enabled"`
	DeepResearchEnabled               *bool    `json:"deep_research_enabled"`
	MultiModelChatEnabled             *bool    `json:"multi_model_chat_enabled"`
	SearchUIEnabled                   *bool    `json:"search_ui_enabled"`
	AutoDetectSearchFilters           *bool    `json:"auto_detect_search_filters"`
	EEFeaturesEnabled                 bool     `json:"ee_features_enabled"`
	Tier                              string   `json:"tier"`
	TemperatureOverrideEnabled        *bool    `json:"temperature_override_enabled"`
	AutoScroll                        *bool    `json:"auto_scroll"`
	QueryHistoryType                  *string  `json:"query_history_type"`
	HideQueryHistoryFromAdminPanel    bool     `json:"hide_query_history_from_admin_panel"`
	ImageExtractionAndAnalysisEnabled *bool    `json:"image_extraction_and_analysis_enabled"`
	ImageAnalysisMaxSizeMB            *int64   `json:"image_analysis_max_size_mb"`
	UserKnowledgeEnabled              *bool    `json:"user_knowledge_enabled"`
	UserFileMaxUploadSizeMB           *int64   `json:"user_file_max_upload_size_mb"`
	FileTokenCountThresholdK          *int64   `json:"file_token_count_threshold_k"`
	ShowExtraConnectors               *bool    `json:"show_extra_connectors"`
	DisableDefaultAssistant           *bool    `json:"disable_default_assistant"`
	CraftDefaultEnabled               bool     `json:"craft_default_enabled"`
	CraftInstructions                 *string  `json:"craft_instructions"`
	SeatCount                         *int64   `json:"seat_count"`
	UsedSeats                         *int64   `json:"used_seats"`
	OpenSearchIndexingEnabled         bool     `json:"opensearch_indexing_enabled"`
}

// GetSettings fetches current settings. The endpoint returns UserSettings (a
// superset with runtime fields); the extra fields are ignored on decode.
func (c *Client) GetSettings(ctx context.Context) (*Settings, error) {
	var settings Settings
	if err := c.doJSON(ctx, http.MethodGet, "/settings", nil, &settings); err != nil {
		return nil, err
	}
	return &settings, nil
}

// PatchSettings applies a partial update: the backend merges only the fields
// present in the body, so callers send exactly what they manage.
func (c *Client) PatchSettings(ctx context.Context, fields map[string]any) error {
	return c.doJSON(ctx, http.MethodPatch, "/admin/settings", fields, nil)
}
