package provider

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

func TestCustomToolAvailabilityUsesDefaultChatSelection(t *testing.T) {
	for _, legacyEnabled := range []bool{false, true} {
		for _, selected := range []bool{false, true} {
			for _, imported := range []bool{false, true} {
				t.Run(fmt.Sprintf("legacy=%t/selected=%t/imported=%t", legacyEnabled, selected, imported), func(t *testing.T) {
					model := customToolResourceModel{Enabled: types.BoolValue(legacyEnabled), CustomHeaders: types.MapNull(types.StringType)}
					if imported {
						model.Enabled = types.BoolNull()
					}
					remote := &client.CustomTool{ID: 7, Name: "weather", Definition: map[string]any{"openapi": "3.0.0"}, Enabled: legacyEnabled, DefaultChatEnabled: &selected}
					var diags diag.Diagnostics
					if !applyRemoteCustomTool(context.Background(), &model, remote, false, &diags) {
						t.Fatalf("read failed: %v", diags)
					}
					if model.Enabled.ValueBool() != selected || model.Enabled.IsNull() {
						t.Fatalf("enabled = %v, want %t", model.Enabled, selected)
					}
					r := &customToolResource{}
					write, ok := r.writeFromModel(context.Background(), model, model.CustomHeaders, &diags)
					if !ok || write.DefaultChatEnabled != selected {
						t.Fatalf("round trip changed selection: %+v, %v", write, diags)
					}
				})
			}
		}
	}
}

func TestCustomToolMissingAvailabilityRequiresServerUpgrade(t *testing.T) {
	model := customToolResourceModel{Enabled: types.BoolValue(false), CustomHeaders: types.MapNull(types.StringType)}
	remote := &client.CustomTool{ID: 7, Name: "weather", Definition: map[string]any{}, Enabled: true}
	var diags diag.Diagnostics
	if applyRemoteCustomTool(context.Background(), &model, remote, false, &diags) {
		t.Fatal("missing selection must not silently use global enabled")
	}
	if !diags.HasError() || !strings.Contains(diags[0].Detail(), "Upgrade the Onyx server") {
		t.Fatalf("expected upgrade diagnostic, got %v", diags)
	}
	if model.ID.ValueString() != "7" {
		t.Fatal("created ID must remain available to save in state")
	}
	if model.Enabled.ValueBool() {
		t.Fatal("legacy enabled must not overwrite selection")
	}
}
