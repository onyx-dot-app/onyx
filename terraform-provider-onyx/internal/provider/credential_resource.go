package provider

import (
	"context"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework-jsontypes/jsontypes"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/booldefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/boolplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/listplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                = (*credentialResource)(nil)
	_ resource.ResourceWithConfigure   = (*credentialResource)(nil)
	_ resource.ResourceWithImportState = (*credentialResource)(nil)
)

// NewCredentialResource returns the onyx_credential resource.
func NewCredentialResource() resource.Resource {
	return &credentialResource{}
}

type credentialResource struct {
	client *client.Client
}

type credentialResourceModel struct {
	ID             types.String         `tfsdk:"id"`
	Source         types.String         `tfsdk:"source"`
	Name           types.String         `tfsdk:"name"`
	CredentialJSON jsontypes.Normalized `tfsdk:"credential_json"`
	AdminPublic    types.Bool           `tfsdk:"admin_public"`
	CuratorPublic  types.Bool           `tfsdk:"curator_public"`
	Groups         types.List           `tfsdk:"groups"`
}

func (r *credentialResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_credential"
}

func (r *credentialResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "Connector credentials — the secret payload a connector authenticates with. " +
			"Pair a credential with an `onyx_connector` to start indexing. The API always returns the " +
			"payload masked, so `credential_json` is write-only: Terraform never refreshes it and cannot " +
			"detect changes made outside Terraform.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Numeric credential id.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"source": schema.StringAttribute{
				Required: true,
				MarkdownDescription: "Connector source this credential belongs to, lowercase, e.g. `confluence`, " +
					"`google_drive`, `slack`. Must match the `source` of the connector it is paired with.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"name": schema.StringAttribute{
				Optional: true,
				Computed: true,
				MarkdownDescription: "Display name. Onyx has no API to clear a name, so removing this " +
					"attribute keeps the last value instead of planning a change.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"credential_json": schema.StringAttribute{
				Required:   true,
				Sensitive:  true,
				CustomType: jsontypes.NormalizedType{},
				MarkdownDescription: "Secret payload as a JSON object, e.g. " +
					"`jsonencode({ confluence_username = \"...\", confluence_access_token = \"...\" })`. " +
					"The required keys depend on the source.",
			},
			"admin_public": schema.BoolAttribute{
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(true),
				MarkdownDescription: "Whether every admin can use this credential. Onyx has no API to change " +
					"it later. Leaving it `true` also keeps the credential readable: the API hides a private " +
					"credential from admins other than its creator, and Terraform cannot tell that apart from " +
					"a deleted one.",
				PlanModifiers: []planmodifier.Bool{
					boolplanmodifier.RequiresReplace(),
				},
			},
			"curator_public": schema.BoolAttribute{
				Optional:            true,
				Computed:            true,
				Default:             booldefault.StaticBool(false),
				MarkdownDescription: "Whether curators of the assigned groups can use this credential. Create-only.",
				PlanModifiers: []planmodifier.Bool{
					boolplanmodifier.RequiresReplace(),
				},
			},
			"groups": schema.ListAttribute{
				Optional:    true,
				ElementType: types.Int64Type,
				MarkdownDescription: "Enterprise user-group ids allowed to use this credential. Create-only, " +
					"and not returned by the API, so Terraform cannot detect changes made elsewhere.",
				PlanModifiers: []planmodifier.List{
					listplanmodifier.RequiresReplace(),
				},
			},
		},
	}
}

func (r *credentialResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// upsertFromModel builds the create/replace body. credential_json is always
// taken from configuration — the server copy is masked.
func (r *credentialResource) upsertFromModel(ctx context.Context, model credentialResourceModel, diags *diag.Diagnostics) (client.CredentialUpsert, bool) {
	payload, ok := jsonObjectFromNormalized(model.CredentialJSON, "credential_json", diags)
	if !ok {
		return client.CredentialUpsert{}, false
	}
	groups, ok := int64ListValues(ctx, model.Groups, diags)
	if !ok {
		return client.CredentialUpsert{}, false
	}
	return client.CredentialUpsert{
		CredentialJSON: payload,
		AdminPublic:    model.AdminPublic.ValueBool(),
		Source:         model.Source.ValueString(),
		Name:           stringPointer(model.Name),
		CuratorPublic:  model.CuratorPublic.ValueBool(),
		Groups:         groups,
	}, true
}

func (r *credentialResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan credentialResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	// Unset name stays unset server-side; resolve it before it reaches state.
	if plan.Name.IsUnknown() {
		plan.Name = types.StringNull()
	}

	upsert, ok := r.upsertFromModel(ctx, plan, &resp.Diagnostics)
	if !ok {
		return
	}

	id, err := r.client.CreateCredential(ctx, upsert)
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx credential", err.Error())
		return
	}

	plan.ID = types.StringValue(strconv.FormatInt(id, 10))
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *credentialResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state credentialResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "credential", &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.GetCredential(ctx, id)
	if client.IsNotFound(err) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx credential", err.Error())
		return
	}

	state.Source = types.StringValue(remote.Source)
	state.Name = types.StringPointerValue(remote.Name)
	state.AdminPublic = types.BoolValue(remote.AdminPublic)
	state.CuratorPublic = types.BoolValue(remote.CuratorPublic)
	// credential_json and groups are carried forward: the API masks the
	// payload and never returns group assignments.
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *credentialResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state credentialResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "credential", &resp.Diagnostics)
	if !ok {
		return
	}
	upsert, ok := r.upsertFromModel(ctx, plan, &resp.Diagnostics)
	if !ok {
		return
	}

	// Two endpoints split the work: PATCH replaces the payload but ignores the
	// name, PUT sets the name but only merges the payload. Replace first so
	// the merge that follows is a no-op.
	if !plan.CredentialJSON.Equal(state.CredentialJSON) {
		if err := r.client.ReplaceCredentialJSON(ctx, id, upsert); err != nil {
			resp.Diagnostics.AddError("Failed to update the Onyx credential payload", err.Error())
			return
		}
	}
	if !plan.Name.Equal(state.Name) && !plan.Name.IsNull() {
		if err := r.client.SetCredentialName(ctx, id, plan.Name.ValueString(), upsert.CredentialJSON); err != nil {
			resp.Diagnostics.AddError("Failed to rename the Onyx credential", err.Error())
			// The payload replacement above may have landed already.
			resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
			return
		}
	}

	plan.ID = state.ID
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *credentialResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state credentialResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "credential", &resp.Diagnostics)
	if !ok {
		return
	}

	if err := r.client.DeleteCredential(ctx, id); err != nil && !client.IsNotFound(err) {
		// A missing credential errors as 400, not 404; probe so destroy isn't wedged.
		if _, getErr := r.client.GetCredential(ctx, id); client.IsNotFound(getErr) {
			return
		}
		resp.Diagnostics.AddError("Failed to delete Onyx credential", err.Error())
	}
}

func (r *credentialResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	// credential_json cannot be imported: the API only returns it masked.
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
