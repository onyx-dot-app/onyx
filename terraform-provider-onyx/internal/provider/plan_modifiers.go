package provider

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

// serverDefaultedInt64 plans an optional number that Onyx fills in itself.
// With nothing configured and nothing stored, the next update makes the server
// substitute its own default, so that plan must say "known after apply".
// Anything else keeps the stored value, which Terraform re-asserts on write.
type serverDefaultedInt64 struct{}

// ServerDefaultedInt64 returns the plan modifier described above.
func ServerDefaultedInt64() planmodifier.Int64 {
	return serverDefaultedInt64{}
}

func (m serverDefaultedInt64) Description(_ context.Context) string {
	return "Onyx picks this value when it is not configured."
}

func (m serverDefaultedInt64) MarkdownDescription(ctx context.Context) string {
	return m.Description(ctx)
}

func (m serverDefaultedInt64) PlanModifyInt64(_ context.Context, req planmodifier.Int64Request, resp *planmodifier.Int64Response) {
	// Create resolves the value from the read-back; destroy plans nothing.
	if req.State.Raw.IsNull() || req.Plan.Raw.IsNull() {
		return
	}
	if !req.ConfigValue.IsNull() {
		return
	}
	// Only an update with nothing stored triggers the substitution. Every
	// other case keeps the stored value, so an unchanged resource plans clean
	// instead of "known after apply".
	if req.StateValue.IsNull() && !req.Plan.Raw.Equal(req.State.Raw) {
		resp.PlanValue = types.Int64Unknown()
		return
	}
	resp.PlanValue = req.StateValue
}
