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

func TestPatchSettingsSendsOnlyManagedFields(t *testing.T) {
	c, captured := newTestServer(t, http.StatusOK, `null`)

	// Unmanaged fields must be absent from the body or the server merges them.
	err := c.PatchSettings(context.Background(), map[string]any{
		"company_name":        "ACME",
		"invite_only_enabled": true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if captured.Method != http.MethodPatch || captured.Path != "/admin/settings" {
		t.Errorf("got %s %s, want PATCH /admin/settings", captured.Method, captured.Path)
	}

	body := bodyAsMap(t, captured.Body)
	if len(body) != 2 {
		t.Errorf("body must contain exactly the managed fields, got: %s", captured.Body)
	}
	if body["company_name"] != "ACME" || body["invite_only_enabled"] != true {
		t.Errorf("unexpected body: %s", captured.Body)
	}
	for _, field := range []string{"tier", "ee_features_enabled", "gpu_enabled", "application_status"} {
		if _, present := body[field]; present {
			t.Errorf("read-only field %q must not be sent: %s", field, captured.Body)
		}
	}
}
