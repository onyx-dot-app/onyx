package provider

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/tfsdk"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/hashicorp/terraform-plugin-go/tftypes"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

// ccPairConfig builds an onyx_cc_pair configuration with every attribute
// null except access_type and data_access_group_ids.
func ccPairConfig(t *testing.T, accessType *string, dataAccess []int64) tfsdk.Config {
	t.Helper()
	ctx := context.Background()
	var schemaResp resource.SchemaResponse
	(&ccPairResource{}).Schema(ctx, resource.SchemaRequest{}, &schemaResp)
	objectType, ok := schemaResp.Schema.Type().TerraformType(ctx).(tftypes.Object)
	if !ok {
		t.Fatal("the schema type is not an object")
	}

	values := make(map[string]tftypes.Value, len(objectType.AttributeTypes))
	for name, attrType := range objectType.AttributeTypes {
		values[name] = tftypes.NewValue(attrType, nil)
	}
	if accessType != nil {
		values["access_type"] = tftypes.NewValue(tftypes.String, *accessType)
	}
	if dataAccess != nil {
		elements := make([]tftypes.Value, 0, len(dataAccess))
		for _, id := range dataAccess {
			elements = append(elements, tftypes.NewValue(tftypes.Number, id))
		}
		values["data_access_group_ids"] = tftypes.NewValue(tftypes.Set{ElementType: tftypes.Number}, elements)
	}
	return tfsdk.Config{Schema: schemaResp.Schema, Raw: tftypes.NewValue(objectType, values)}
}

func TestCCPairValidateConfigDataAccess(t *testing.T) {
	str := func(s string) *string { return &s }
	cases := []struct {
		name       string
		accessType *string
		dataAccess []int64
		wantError  bool
	}{
		{"public without data access", nil, nil, false},
		{"private with data access", str("private"), []int64{4}, false},
		{"restricted with data access", str("sync_restricted"), []int64{4}, false},
		{"restricted without data access", str("sync_restricted"), nil, true},
		{"restricted with an empty set", str("sync_restricted"), []int64{}, true},
		{"public with data access", nil, []int64{4}, true},
		{"sync with data access", str("sync"), []int64{4}, true},
		{"public with an empty set", nil, []int64{}, true},
		{"sync with an empty set", str("sync"), []int64{}, true},
		{"private with an empty set", str("private"), []int64{}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			req := resource.ValidateConfigRequest{Config: ccPairConfig(t, tc.accessType, tc.dataAccess)}
			var resp resource.ValidateConfigResponse
			(&ccPairResource{}).ValidateConfig(context.Background(), req, &resp)
			if resp.Diagnostics.HasError() != tc.wantError {
				t.Errorf("want error = %t, got %v", tc.wantError, resp.Diagnostics)
			}
		})
	}
}

// groups, auto_sync_options and processing_mode come back on read, so import
// and drift detection see them.
func TestApplyRemoteCCPairRefreshesCreateFields(t *testing.T) {
	ctx := context.Background()
	var model ccPairResourceModel
	var diags diag.Diagnostics
	applyRemoteCCPair(ctx, &model, &client.CCPair{
		ID:              77,
		AccessType:      "private",
		Status:          client.CCPairStatusActive,
		Groups:          []int64{4, 6},
		AutoSyncOptions: map[string]any{"customer_id": "c1"},
		ProcessingMode:  "RAW_BINARY",
	}, &diags)
	if diags.HasError() {
		t.Fatal(diags)
	}
	want := types.SetValueMust(types.Int64Type, []attr.Value{types.Int64Value(4), types.Int64Value(6)})
	if !model.Groups.Equal(want) {
		t.Errorf("groups = %v, want [4 6]", model.Groups)
	}
	if model.AutoSyncOptions.ValueString() != `{"customer_id":"c1"}` {
		t.Errorf("auto_sync_options = %s", model.AutoSyncOptions.ValueString())
	}
	if model.ProcessingMode.ValueString() != "RAW_BINARY" {
		t.Errorf("processing_mode = %s", model.ProcessingMode.ValueString())
	}

	// A pair with no groups and no sync options reads as an empty set and null.
	applyRemoteCCPair(ctx, &model, &client.CCPair{ID: 77, ProcessingMode: "REGULAR"}, &diags)
	if model.Groups.IsNull() || len(model.Groups.Elements()) != 0 {
		t.Errorf("want an empty groups set, got %v", model.Groups)
	}
	if !model.AutoSyncOptions.IsNull() {
		t.Errorf("want null auto_sync_options, got %s", model.AutoSyncOptions.ValueString())
	}
}

// Onyx before v4.8 returns none of the three fields. The known values stay,
// so the pair is not planned for replacement.
func TestApplyRemoteCCPairKeepsValuesFromAnOlderServer(t *testing.T) {
	ctx := context.Background()
	groups := types.SetValueMust(types.Int64Type, []attr.Value{types.Int64Value(4)})
	model := ccPairResourceModel{
		Groups:         groups,
		ProcessingMode: types.StringValue("RAW_BINARY"),
	}
	var diags diag.Diagnostics
	applyRemoteCCPair(ctx, &model, &client.CCPair{ID: 77, AccessType: "private"}, &diags)
	if !model.Groups.Equal(groups) || model.ProcessingMode.ValueString() != "RAW_BINARY" {
		t.Errorf("want the known values kept, got groups %v and processing_mode %s",
			model.Groups, model.ProcessingMode)
	}
}

// Onyx before v5.0 and Community Edition have no data-access route and drop
// the field on create. That must fail the write, but not a plain read.
func TestRefreshDataAccessWithoutTheRoute(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"detail": "Not Found"}`))
	}))
	t.Cleanup(server.Close)
	r := &ccPairResource{client: client.NewClient(client.Config{ServerURL: server.URL, APIKey: "on_test_key"})}
	want := types.SetValueMust(types.Int64Type, []attr.Value{types.Int64Value(4)})

	for _, afterWrite := range []bool{true, false} {
		model := ccPairResourceModel{AccessType: types.StringValue("private"), DataAccessGroupIDs: want}
		var diags diag.Diagnostics
		r.refreshDataAccess(context.Background(), 77, &model, afterWrite, &diags)
		if diags.HasError() != afterWrite {
			t.Errorf("afterWrite=%t: want error = %t, got %v", afterWrite, afterWrite, diags)
		}
		if !model.DataAccessGroupIDs.Equal(want) {
			t.Errorf("afterWrite=%t: data_access_group_ids = %v, want [4]", afterWrite, model.DataAccessGroupIDs)
		}
	}
}
