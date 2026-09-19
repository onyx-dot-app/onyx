package provider

import (
	"context"
	"testing"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/tfsdk"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/hashicorp/terraform-plugin-go/tftypes"
)

// secretConfig builds a configuration holding a secret and its write-only twin,
// each either a value or null.
func secretConfig(stored, writeOnly *string) tfsdk.Config {
	value := func(s *string) tftypes.Value {
		if s == nil {
			return tftypes.NewValue(tftypes.String, nil)
		}
		return tftypes.NewValue(tftypes.String, *s)
	}
	return tfsdk.Config{
		Schema: schema.Schema{
			Attributes: map[string]schema.Attribute{
				"api_key":    schema.StringAttribute{Optional: true, Sensitive: true},
				"api_key_wo": schema.StringAttribute{Optional: true, Sensitive: true, WriteOnly: true},
			},
		},
		Raw: tftypes.NewValue(
			tftypes.Object{AttributeTypes: map[string]tftypes.Type{
				"api_key":    tftypes.String,
				"api_key_wo": tftypes.String,
			}},
			map[string]tftypes.Value{
				"api_key":    value(stored),
				"api_key_wo": value(writeOnly),
			},
		),
	}
}

func stringPointerOf(s string) *string { return &s }

func TestResolveWriteOnlySource(t *testing.T) {
	tests := []struct {
		name             string
		stored           *string
		writeOnly        *string
		wantValue        types.String
		wantFromWriteOnl bool
	}{
		{
			name:             "write-only wins when set",
			stored:           nil,
			writeOnly:        stringPointerOf("from-wo"),
			wantValue:        types.StringValue("from-wo"),
			wantFromWriteOnl: true,
		},
		{
			name:             "stored value is used when the twin is null",
			stored:           stringPointerOf("from-state"),
			writeOnly:        nil,
			wantValue:        types.StringValue("from-state"),
			wantFromWriteOnl: false,
		},
		{
			name:             "neither set resolves to null",
			stored:           nil,
			writeOnly:        nil,
			wantValue:        types.StringNull(),
			wantFromWriteOnl: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			config := secretConfig(tt.stored, tt.writeOnly)
			var stored types.String
			if tt.stored != nil {
				stored = types.StringValue(*tt.stored)
			} else {
				stored = types.StringNull()
			}

			var diags diag.Diagnostics
			got, fromWriteOnly := resolveWriteOnlySource(
				context.Background(), config, path.Root("api_key_wo"), stored, &diags)
			if diags.HasError() {
				t.Fatalf("unexpected diagnostics: %v", diags)
			}
			if !got.Equal(tt.wantValue) {
				t.Errorf("value = %v, want %v", got, tt.wantValue)
			}
			if fromWriteOnly != tt.wantFromWriteOnl {
				t.Errorf("fromWriteOnly = %v, want %v", fromWriteOnly, tt.wantFromWriteOnl)
			}
		})
	}
}

func TestEitherAttributeIsSet(t *testing.T) {
	tests := []struct {
		name      string
		stored    types.String
		writeOnly types.String
		wantSet   bool
		wantKnown bool
	}{
		{"neither", types.StringNull(), types.StringNull(), false, true},
		{"stored only", types.StringValue("x"), types.StringNull(), true, true},
		{"write-only only", types.StringNull(), types.StringValue("x"), true, true},
		{"unknown twin hides the answer", types.StringNull(), types.StringUnknown(), false, false},
		{"a known value settles it despite an unknown twin", types.StringValue("x"), types.StringUnknown(), true, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			set, known := eitherAttributeIsSet(tt.stored, tt.writeOnly)
			if set != tt.wantSet || known != tt.wantKnown {
				t.Errorf("got (set=%v, known=%v), want (set=%v, known=%v)",
					set, known, tt.wantSet, tt.wantKnown)
			}
		})
	}
}

// fakePrivateState stands in for the framework's private-state type, which
// lives in an internal package.
type fakePrivateState struct {
	values map[string][]byte
}

func (f *fakePrivateState) SetKey(_ context.Context, key string, value []byte) diag.Diagnostics {
	if f.values == nil {
		f.values = map[string][]byte{}
	}
	f.values[key] = value
	return nil
}

func (f *fakePrivateState) GetKey(_ context.Context, key string) ([]byte, diag.Diagnostics) {
	return f.values[key], nil
}

func TestWriteOnlySourceMarker(t *testing.T) {
	ctx := context.Background()
	const key = "custom_headers_write_only"

	private := &fakePrivateState{}
	var diags diag.Diagnostics

	// An unwritten marker reads as "not write-only", which is what state
	// written before the twin existed should mean.
	if writeOnlySourceMarked(ctx, private, key, &diags) {
		t.Error("an absent marker must read as false")
	}

	diags.Append(markWriteOnlySource(ctx, private, key, true)...)
	if !writeOnlySourceMarked(ctx, private, key, &diags) {
		t.Error("marker set to true must read back as true")
	}

	// Moving a secret back to the stored attribute has to clear the marker, or
	// the refresh would keep skipping the attribute it is meant to track.
	diags.Append(markWriteOnlySource(ctx, private, key, false)...)
	if writeOnlySourceMarked(ctx, private, key, &diags) {
		t.Error("marker set to false must read back as false")
	}

	if diags.HasError() {
		t.Fatalf("unexpected diagnostics: %v", diags)
	}
}
