package provider

import (
	"context"
	"fmt"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                = (*apiKeyResource)(nil)
	_ resource.ResourceWithConfigure   = (*apiKeyResource)(nil)
	_ resource.ResourceWithImportState = (*apiKeyResource)(nil)
)

// NewAPIKeyResource returns the onyx_api_key resource.
func NewAPIKeyResource() resource.Resource {
	return &apiKeyResource{}
}

type apiKeyResource struct {
	client *client.Client
}

type apiKeyResourceModel struct {
	ID            types.String `tfsdk:"id"`
	Name          types.String `tfsdk:"name"`
	GroupIDs      types.Set    `tfsdk:"group_ids"`
	APIKey        types.String `tfsdk:"api_key"`
	APIKeyDisplay types.String `tfsdk:"api_key_display"`
	UserID        types.String `tfsdk:"user_id"`
}

// groupIDsFromDescriptor always returns a known (non-null) set, even for zero groups.
func groupIDsFromDescriptor(desc *client.APIKeyDescriptor) (types.Set, diag.Diagnostics) {
	ids := make([]attr.Value, 0, len(desc.Groups))
	for _, group := range desc.Groups {
		ids = append(ids, types.Int64Value(group.ID))
	}
	return types.SetValue(types.Int64Type, ids)
}

// groupIDsToArgs: a null or unknown set becomes `[]`, which clears the key's groups.
func (r *apiKeyResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_api_key"
}

func (r *apiKeyResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "An Onyx API key. The key material is returned by the API exactly once at " +
			"creation and is kept in Terraform state (`api_key`, sensitive) from then on; it can never be " +
			"re-read, so after `terraform import` the attribute stays null. Note the chicken-and-egg: the " +
			"key the provider itself authenticates with must be created out-of-band (admin UI or curl).",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Numeric API key id.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"name": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Display name for the key.",
			},
			"group_ids": schema.SetAttribute{
				Optional:    true,
				ElementType: types.Int64Type,
				MarkdownDescription: "Ids of the user groups the backing service account belongs to. The " +
					"key resolves the union of those groups' permissions. Omit for a key with no group " +
					"permissions. This replaces the whole group set on every apply.",
			},
			"api_key": schema.StringAttribute{
				Computed:  true,
				Sensitive: true,
				MarkdownDescription: "The key material (`on_...`). Only available when the key was created " +
					"by Terraform; null after import.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"api_key_display": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Redacted form of the key, safe for display.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"user_id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "UUID of the synthetic service-account user backing the key.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
		},
	}
}

func (r *apiKeyResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

func (r *apiKeyResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan apiKeyResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	groupIDs, diags := int64SetValues(ctx, plan.GroupIDs)
	resp.Diagnostics.Append(diags...)
	if resp.Diagnostics.HasError() {
		return
	}

	desc, err := r.client.CreateAPIKey(ctx, client.APIKeyArgs{
		Name:     plan.Name.ValueStringPointer(),
		GroupIDs: groupIDs,
	})
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx API key", err.Error())
		return
	}

	plan.ID = types.StringValue(strconv.FormatInt(desc.APIKeyID, 10))
	plan.APIKey = types.StringPointerValue(desc.APIKey)
	plan.APIKeyDisplay = types.StringValue(desc.APIKeyDisplay)
	plan.UserID = types.StringValue(desc.UserID)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *apiKeyResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state apiKeyResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "API key", &resp.Diagnostics)
	if !ok {
		return
	}

	desc, err := r.client.GetAPIKey(ctx, id)
	if client.IsNotFound(err) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx API key", err.Error())
		return
	}

	state.Name = types.StringPointerValue(desc.APIKeyName)
	state.APIKeyDisplay = types.StringValue(desc.APIKeyDisplay)
	state.UserID = types.StringValue(desc.UserID)

	// Terraform treats null and an empty set as different; only overwrite group_ids when
	// the API actually reports groups, or a no-group key drifts null → [].
	if len(desc.Groups) > 0 || !state.GroupIDs.IsNull() {
		groupIDs, diags := groupIDsFromDescriptor(desc)
		resp.Diagnostics.Append(diags...)
		if resp.Diagnostics.HasError() {
			return
		}
		state.GroupIDs = groupIDs
	}

	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *apiKeyResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state apiKeyResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "API key", &resp.Diagnostics)
	if !ok {
		return
	}

	groupIDs, diags := int64SetValues(ctx, plan.GroupIDs)
	resp.Diagnostics.Append(diags...)
	if resp.Diagnostics.HasError() {
		return
	}

	desc, err := r.client.UpdateAPIKey(ctx, id, client.APIKeyArgs{
		Name:     plan.Name.ValueStringPointer(),
		GroupIDs: groupIDs,
	})
	if err != nil {
		resp.Diagnostics.AddError("Failed to update Onyx API key", err.Error())
		return
	}

	plan.ID = state.ID
	plan.APIKey = state.APIKey
	plan.APIKeyDisplay = types.StringValue(desc.APIKeyDisplay)
	plan.UserID = types.StringValue(desc.UserID)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *apiKeyResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state apiKeyResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "API key", &resp.Diagnostics)
	if !ok {
		return
	}

	if err := r.client.DeleteAPIKey(ctx, id); err != nil && !client.IsNotFound(err) {
		// A missing key errors as 400, not 404; probe so destroy isn't wedged.
		if _, getErr := r.client.GetAPIKey(ctx, id); client.IsNotFound(getErr) {
			return
		}
		resp.Diagnostics.AddError("Failed to delete Onyx API key", err.Error())
	}
}

func (r *apiKeyResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}

// parseID converts a numeric string id from state/import into an int64,
// adding a diagnostic when malformed.
func parseID(id types.String, resourceName string, diags interface {
	AddError(summary string, detail string)
}) (int64, bool) {
	parsed, err := strconv.ParseInt(id.ValueString(), 10, 64)
	if err != nil {
		diags.AddError(
			fmt.Sprintf("Invalid %s id", resourceName),
			fmt.Sprintf("Expected a numeric id, got %q.", id.ValueString()),
		)
		return 0, false
	}
	return parsed, true
}
