package provider

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

// settingsServer answers GET /settings with the given body and records every
// PATCH /admin/settings body.
func settingsServer(t *testing.T, settings map[string]any) (*client.Client, func() []map[string]any) {
	t.Helper()
	body, err := json.Marshal(settings)
	if err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	var patches []map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.Method == http.MethodPatch {
			raw, _ := io.ReadAll(r.Body)
			patch := map[string]any{}
			if err := json.Unmarshal(raw, &patch); err != nil {
				t.Errorf("PATCH body is not JSON: %v", err)
			}
			mu.Lock()
			patches = append(patches, patch)
			mu.Unlock()
			_, _ = w.Write([]byte(`{}`))
			return
		}
		_, _ = w.Write(body)
	}))
	t.Cleanup(server.Close)
	recorded := func() []map[string]any {
		mu.Lock()
		defer mu.Unlock()
		return append([]map[string]any(nil), patches...)
	}
	return client.NewClient(client.Config{ServerURL: server.URL, APIKey: "on_test_key"}), recorded
}

// The backend keeps returning the field for older providers, with whatever
// value it has stored.
func backendSettings(imageAnalysisMaxSizeMB any) map[string]any {
	return map[string]any{
		"company_name":                          "acme",
		"invite_only_enabled":                   false,
		"hide_query_history_from_admin_panel":   false,
		"opensearch_indexing_enabled":           true,
		"image_extraction_and_analysis_enabled": true,
		"image_analysis_max_size_mb":            imageAnalysisMaxSizeMB,
		"application_status":                    "ACTIVE",
		"tier":                                  "enterprise",
	}
}

// A configuration written for provider 0.3.0 still sets the attribute. Apply
// must not send it, and state must keep the configured value whatever the
// backend returns, or every later plan would show a change.
func TestSettingsApplyKeepsDeprecatedImageAnalysisMaxSize(t *testing.T) {
	for name, stored := range map[string]any{"backend returns null": nil, "backend returns another value": 50} {
		t.Run(name, func(t *testing.T) {
			c, patches := settingsServer(t, backendSettings(stored))
			r := &settingsResource{client: c}
			plan := settingsResourceModel{
				CompanyName:            types.StringValue("acme"),
				ImageAnalysisMaxSizeMB: types.Int64Value(20),
			}

			state, patched, err := r.apply(context.Background(), plan)
			if err != nil || !patched {
				t.Fatalf("apply: patched=%v err=%v", patched, err)
			}

			sent := patches()
			if len(sent) != 1 {
				t.Fatalf("want one PATCH, got %d", len(sent))
			}
			if _, ok := sent[0]["image_analysis_max_size_mb"]; ok {
				t.Error("the deprecated attribute must not be sent")
			}
			if sent[0]["company_name"] != "acme" {
				t.Errorf("other attributes are still sent, got %v", sent[0])
			}
			if got := state.ImageAnalysisMaxSizeMB; !got.Equal(types.Int64Value(20)) {
				t.Errorf("state must keep the configured value 20, got %v", got)
			}
		})
	}
}
