package provider

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework-jsontypes/jsontypes"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"

	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

func connectorUpsertBody(t *testing.T, checkFreq types.Int64) map[string]any {
	t.Helper()
	model := connectorResourceModel{
		Name:                    types.StringValue("docs"),
		Source:                  types.StringValue("web"),
		InputType:               types.StringValue("load_state"),
		ConnectorSpecificConfig: jsontypes.NewNormalizedValue(`{"base_url":"https://example.com"}`),
		CheckFreq:               checkFreq,
	}
	var diags diag.Diagnostics
	upsert, ok := (&connectorResource{}).upsertFromModel(context.Background(), model, &diags)
	if !ok || diags.HasError() {
		t.Fatalf("upsertFromModel: %v", diags)
	}
	raw, err := json.Marshal(upsert)
	if err != nil {
		t.Fatal(err)
	}
	body := map[string]any{}
	if err := json.Unmarshal(raw, &body); err != nil {
		t.Fatal(err)
	}
	return body
}

// An omitted check_freq keeps the stored schedule; an explicit null would
// clear it on Onyx v5.0.0 and later.
func TestConnectorUpsertSendsCheckFreqOnlyWhenSet(t *testing.T) {
	if _, ok := connectorUpsertBody(t, types.Int64Null())["check_freq"]; ok {
		t.Error("an unset check_freq must not be sent")
	}
	if got := connectorUpsertBody(t, types.Int64Value(3600))["check_freq"]; got != float64(3600) {
		t.Errorf("check_freq = %v, want 3600", got)
	}
}

func TestConnectorCheckFreqUnsupportedError(t *testing.T) {
	stored := int64(3600)
	for name, tc := range map[string]struct {
		configured bool
		remote     *int64
		wantError  bool
	}{
		"server stored the value":     {configured: true, remote: &stored, wantError: false},
		"server ignored the value":    {configured: true, remote: nil, wantError: true},
		"not configured, no schedule": {configured: false, remote: nil, wantError: false},
	} {
		t.Run(name, func(t *testing.T) {
			var diags diag.Diagnostics
			addCheckFreqUnsupportedError(tc.configured, &client.Connector{CheckFreq: tc.remote}, &diags)
			if diags.HasError() != tc.wantError {
				t.Errorf("error = %v, want %v: %v", diags.HasError(), tc.wantError, diags)
			}
		})
	}
}
