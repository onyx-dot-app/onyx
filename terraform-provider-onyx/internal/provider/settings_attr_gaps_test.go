package provider

import (
	"context"
	"strings"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/types"
)

func TestSettingsApplySendsOnlyConfiguredNewSettings(t *testing.T) {
	server := backendSettings(nil)
	server["reasoning_override_enabled"] = false
	server["hide_provider_grouping"] = true
	server["default_language"] = "de"
	server["llm_gateway_enabled"] = true
	server["embedding_rate_limit_requests"] = 10
	server["embedding_rate_limit_period_seconds"] = 60
	c, patches := settingsServer(t, server)
	r := &settingsResource{client: c}

	plan := settingsResourceModel{
		ReasoningOverrideEnabled:   types.BoolValue(false),
		DefaultLanguage:            types.StringValue("de"),
		EmbeddingRateLimitRequests: types.Int64Value(10),
	}
	state, patched, err := r.apply(context.Background(), plan)
	if err != nil || !patched {
		t.Fatalf("apply: patched=%v err=%v", patched, err)
	}

	sent := patches()
	if len(sent) != 1 {
		t.Fatalf("want one PATCH, got %d", len(sent))
	}
	want := map[string]any{
		"reasoning_override_enabled":    false,
		"default_language":              "de",
		"embedding_rate_limit_requests": float64(10),
	}
	if len(sent[0]) != len(want) {
		t.Errorf("PATCH must hold only the configured fields, got %v", sent[0])
	}
	for name, value := range want {
		if sent[0][name] != value {
			t.Errorf("PATCH %s = %v, want %v", name, sent[0][name], value)
		}
	}

	if !state.ReasoningOverrideEnabled.Equal(types.BoolValue(false)) ||
		!state.DefaultLanguage.Equal(types.StringValue("de")) ||
		!state.EmbeddingRateLimitRequests.Equal(types.Int64Value(10)) {
		t.Errorf("managed settings not refreshed: %+v", state)
	}
	// Unmanaged settings stay null even though the server returns them.
	if !state.HideProviderGrouping.IsNull() || !state.LLMGatewayEnabled.IsNull() ||
		!state.EmbeddingRateLimitPeriodSeconds.IsNull() {
		t.Errorf("unmanaged settings must stay null: %+v", state)
	}
}

// Servers before v5.0.0 ignore unknown PATCH fields and do not return them.
func TestSettingsApplyReportsSettingsTooNewForServer(t *testing.T) {
	c, _ := settingsServer(t, backendSettings(nil))
	r := &settingsResource{client: c}

	plan := settingsResourceModel{
		HideProviderGrouping: types.BoolValue(false),
		DefaultLanguage:      types.StringValue("de"),
		LLMGatewayEnabled:    types.BoolValue(false),
	}
	_, patched, err := r.apply(context.Background(), plan)
	if !patched {
		t.Fatal("the PATCH landed, so apply must report patched")
	}
	if err == nil {
		t.Fatal("want an error for settings the server did not return")
	}
	for _, name := range []string{"default_language", "llm_gateway_enabled", "v5.0.0"} {
		if !strings.Contains(err.Error(), name) {
			t.Errorf("error %q must name %s", err, name)
		}
	}
	if strings.Contains(err.Error(), "hide_provider_grouping") {
		t.Errorf("hide_provider_grouping exists since v4.8.0, got %q", err)
	}
}
