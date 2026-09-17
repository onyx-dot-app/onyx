package provider

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework-validators/int64validator"
	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/tfsdk"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

// Secrets reach this provider two ways. The plain attribute is convenient but
// lands in state; its `_wo` twin is write-only, so Terraform strips the value
// from both plan and state and it exists only in configuration. The pair is
// mutually exclusive, and every resource resolves one effective value from it
// before building a request body.

// resolveWriteOnly picks the value to send to the API: the write-only twin at
// woPath when configuration sets it, otherwise the stored attribute.
//
// Terraform keeps write-only values out of plan and state, so configuration is
// the only place to read them from. That also makes them available on every
// apply, which matters here because the Onyx APIs replace all fields on update
// and would otherwise clear a stored secret.
func resolveWriteOnly[T attr.Value](
	ctx context.Context,
	config tfsdk.Config,
	woPath path.Path,
	stored T,
	diags *diag.Diagnostics,
) T {
	value, _ := resolveWriteOnlySource(ctx, config, woPath, stored, diags)
	return value
}

// resolveWriteOnlySource is resolveWriteOnly plus which half of the pair the
// value came from. Read runs without configuration, so a resource whose API
// hands secrets back in full has to record that answer to know whether the
// refresh may touch the stored attribute.
func resolveWriteOnlySource[T attr.Value](
	ctx context.Context,
	config tfsdk.Config,
	woPath path.Path,
	stored T,
	diags *diag.Diagnostics,
) (value T, fromWriteOnly bool) {
	var writeOnly T
	diags.Append(config.GetAttribute(ctx, woPath, &writeOnly)...)
	if diags.HasError() || writeOnly.IsNull() || writeOnly.IsUnknown() {
		return stored, false
	}
	return writeOnly, true
}

// writeOnlyVersionAttribute builds the rotation counter that pairs with a
// write-only secret.
//
// Terraform cannot diff a value it never stores, so changing a `_wo` secret on
// its own plans nothing. Raising this counter is what produces the diff that
// makes the next apply send the current value.
func writeOnlyVersionAttribute(secretAttr string) schema.Int64Attribute {
	return schema.Int64Attribute{
		Optional: true,
		MarkdownDescription: "Rotation counter for `" + secretAttr + "`. Terraform never stores a " +
			"write-only value and so cannot tell that the secret changed; raise this number to make " +
			"the next apply send the current one. Do not derive it from the secret itself — unlike " +
			"the secret, this number is kept in state.",
		Validators: []validator.Int64{
			int64validator.AlsoRequires(path.MatchRoot(secretAttr)),
		},
	}
}

// writeOnlyVersionChanged reports whether the rotation counter moved, which is
// an update's only evidence that a write-only secret needs resending.
func writeOnlyVersionChanged(plan, state types.Int64) bool {
	return !plan.Equal(state)
}

// writeOnlyDescription is the shared tail for a secret attribute that has a
// write-only twin.
func writeOnlyDescription(secretAttr string) string {
	return " Prefer `" + secretAttr + "_wo`, which keeps the value out of state entirely; the two " +
		"cannot be set together."
}

// eitherAttributeIsSet folds a secret and its write-only twin into one presence
// check. The pair is mutually exclusive, so a value on either side means the
// secret is set; the answer stays unknown only while both sides are.
func eitherAttributeIsSet(stored, writeOnly attr.Value) (set bool, known bool) {
	storedSet, storedKnown := attributeIsSet(stored)
	writeOnlySet, writeOnlyKnown := attributeIsSet(writeOnly)
	if (storedKnown && storedSet) || (writeOnlyKnown && writeOnlySet) {
		return true, true
	}
	return false, storedKnown && writeOnlyKnown
}

// privateStateWriter and privateStateReader mirror the private-state methods on
// the framework's request and response types. Those live in an internal
// package, so the concrete type cannot be named here.
type privateStateWriter interface {
	SetKey(ctx context.Context, key string, value []byte) diag.Diagnostics
}

type privateStateReader interface {
	GetKey(ctx context.Context, key string) ([]byte, diag.Diagnostics)
}

// markWriteOnlySource records whether a secret arrived through its write-only
// twin. Read gets no configuration, so this marker is its only way to know that
// a value has to stay out of state.
func markWriteOnlySource(ctx context.Context, private privateStateWriter, key string, fromWriteOnly bool) diag.Diagnostics {
	value := []byte("false")
	if fromWriteOnly {
		value = []byte("true")
	}
	return private.SetKey(ctx, key, value)
}

// writeOnlySourceMarked reports what markWriteOnlySource last recorded. A
// missing marker reads as false, which is the right answer for state written
// before the resource grew a write-only twin.
func writeOnlySourceMarked(ctx context.Context, private privateStateReader, key string, diags *diag.Diagnostics) bool {
	raw, getDiags := private.GetKey(ctx, key)
	diags.Append(getDiags...)
	return string(raw) == "true"
}
