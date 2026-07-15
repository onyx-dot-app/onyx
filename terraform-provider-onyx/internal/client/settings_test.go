package client

import (
	"context"
	"net/http"
	"testing"
)

// userSettingsJSON is a GET /settings response: UserSettings is a superset of
// Settings with runtime fields the client must tolerate and ignore.
const userSettingsJSON = `{
	"maximum_chat_retention_days": null,
	"company_name": "ACME",
	"company_description": null,
	"gpu_enabled": false,
	"application_status": "active",
	"anonymous_user_enabled": false,
	"invite_only_enabled": false,
	"deep_research_enabled": true,
	"multi_model_chat_enabled": true,
	"search_ui_enabled": true,
	"auto_detect_search_filters": true,
	"ee_features_enabled": true,
	"tier": "enterprise",
	"temperature_override_enabled": false,
	"auto_scroll": false,
	"query_history_type": "normal",
	"hide_query_history_from_admin_panel": false,
	"image_extraction_and_analysis_enabled": true,
	"image_analysis_max_size_mb": 20,
	"user_knowledge_enabled": true,
	"user_file_max_upload_size_mb": 200,
	"file_token_count_threshold_k": null,
	"show_extra_connectors": true,
	"disable_default_assistant": false,
	"craft_default_enabled": true,
	"craft_instructions": null,
	"seat_count": 50,
	"used_seats": 12,
	"opensearch_indexing_enabled": false,
	"notifications": [],
	"needs_reindexing": false,
	"tenant_id": "public",
	"version": "1.2.3"
}`

func TestGetSettings(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, userSettingsJSON)
	settings, err := c.GetSettings(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodGet || captured.Path != "/settings" {
		t.Errorf("got %s %s, want GET /settings", captured.Method, captured.Path)
	}
	if settings.CompanyName == nil || *settings.CompanyName != "ACME" {
		t.Errorf("unexpected company_name: %v", settings.CompanyName)
	}
	if settings.Tier != "enterprise" || !settings.EEFeaturesEnabled {
		t.Errorf("license fields not decoded: %+v", settings)
	}
	if settings.SeatCount == nil || *settings.SeatCount != 50 {
		t.Errorf("unexpected seat_count: %v", settings.SeatCount)
	}
}

func TestPutSettingsSendsFullObject(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)

	// Round-trip: what GET returned must be re-sendable verbatim, since the
	// backend PUT resets any omitted field to its Pydantic default.
	getClient, _ := newTestServer(t, http.StatusOK, userSettingsJSON)
	settings, err := getClient.GetSettings(context.Background())
	if err != nil {
		t.Fatal(err)
	}

	if err := c.PutSettings(context.Background(), *settings); err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPut || captured.Path != "/admin/settings" {
		t.Errorf("got %s %s, want PUT /admin/settings", captured.Method, captured.Path)
	}

	body := bodyAsMap(t, captured.Body)
	for _, field := range []string{
		"maximum_chat_retention_days", "company_name", "company_description",
		"gpu_enabled", "application_status", "anonymous_user_enabled",
		"invite_only_enabled", "deep_research_enabled", "multi_model_chat_enabled",
		"search_ui_enabled", "auto_detect_search_filters", "ee_features_enabled",
		"tier", "temperature_override_enabled", "auto_scroll", "query_history_type",
		"hide_query_history_from_admin_panel", "image_extraction_and_analysis_enabled",
		"image_analysis_max_size_mb", "user_knowledge_enabled",
		"user_file_max_upload_size_mb", "file_token_count_threshold_k",
		"show_extra_connectors", "disable_default_assistant",
		"craft_default_enabled", "craft_instructions", "seat_count", "used_seats",
		"opensearch_indexing_enabled",
	} {
		if _, present := body[field]; !present {
			t.Errorf("field %q missing from PUT body — omitted fields get reset server-side", field)
		}
	}
	if body["tier"] != "enterprise" || body["seat_count"] != float64(50) {
		t.Errorf("license-derived fields must round-trip verbatim: %s", captured.Body)
	}
}
