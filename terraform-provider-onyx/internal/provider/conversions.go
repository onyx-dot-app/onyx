package provider

import (
	"context"
	"encoding/json"

	"github.com/hashicorp/terraform-plugin-framework-jsontypes/jsontypes"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

// jsonObjectFromNormalized decodes a JSON attribute into the map the API
// expects, rejecting anything that is not a JSON object.
func jsonObjectFromNormalized(value jsontypes.Normalized, attribute string, diags *diag.Diagnostics) (map[string]any, bool) {
	object := map[string]any{}
	if value.IsNull() || value.IsUnknown() {
		return object, true
	}
	if unmarshalDiags := value.Unmarshal(&object); unmarshalDiags.HasError() {
		diags.AddError(
			"Invalid "+attribute,
			"Expected a JSON object, e.g. jsonencode({ key = \"value\" }).",
		)
		return nil, false
	}
	return object, true
}

// normalizedFromJSONObject re-encodes an API map as a JSON attribute value.
func normalizedFromJSONObject(object map[string]any, attribute string, diags *diag.Diagnostics) (jsontypes.Normalized, bool) {
	if object == nil {
		object = map[string]any{}
	}
	encoded, err := json.Marshal(object)
	if err != nil {
		diags.AddError("Failed to encode "+attribute, err.Error())
		return jsontypes.NewNormalizedNull(), false
	}
	return jsontypes.NewNormalizedValue(string(encoded)), true
}

// int64Pointer converts an optional number into a request field. Unknown must
// map to nil: ValueInt64Pointer reports it as a pointer to zero, which the API
// would store as a real zero instead of applying its own default.
func int64Pointer(value types.Int64) *int64 {
	if value.IsNull() || value.IsUnknown() {
		return nil
	}
	return value.ValueInt64Pointer()
}

// stringPointer is int64Pointer for optional strings.
func stringPointer(value types.String) *string {
	if value.IsNull() || value.IsUnknown() {
		return nil
	}
	return value.ValueStringPointer()
}

// int64ListValues converts an optional list attribute into a slice. The list
// is never nil: the API rejects a null where it expects an array.
func int64ListValues(ctx context.Context, list types.List, diags *diag.Diagnostics) ([]int64, bool) {
	values := []int64{}
	if list.IsNull() || list.IsUnknown() {
		return values, true
	}
	if convertDiags := list.ElementsAs(ctx, &values, false); convertDiags.HasError() {
		diags.Append(convertDiags...)
		return nil, false
	}
	return values, true
}

// int64SetValues converts an optional set attribute into a slice. Like
// int64ListValues the result is never nil: the API rejects a null where it
// expects an array. Sets suit id collections — the server returns them in its
// own order, which must not show up as a diff.
func int64SetValues(ctx context.Context, set types.Set) ([]int64, diag.Diagnostics) {
	ids := []int64{}
	if set.IsNull() || set.IsUnknown() {
		return ids, nil
	}
	return ids, set.ElementsAs(ctx, &ids, false)
}

// stringSetValues is int64SetValues for sets of strings.
func stringSetValues(ctx context.Context, set types.Set) ([]string, diag.Diagnostics) {
	values := []string{}
	if set.IsNull() || set.IsUnknown() {
		return values, nil
	}
	return values, set.ElementsAs(ctx, &values, false)
}
