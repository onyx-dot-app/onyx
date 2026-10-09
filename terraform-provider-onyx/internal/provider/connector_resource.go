package provider

import (
	"context"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework-jsontypes/jsontypes"
	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                = (*connectorResource)(nil)
	_ resource.ResourceWithConfigure   = (*connectorResource)(nil)
	_ resource.ResourceWithImportState = (*connectorResource)(nil)
)

// NewConnectorResource returns the onyx_connector resource.
func NewConnectorResource() resource.Resource {
	return &connectorResource{}
}

type connectorResource struct {
	client *client.Client
}

type connectorResourceModel struct {
	ID                      types.String         `tfsdk:"id"`
	Name                    types.String         `tfsdk:"name"`
	Source                  types.String         `tfsdk:"source"`
	InputType               types.String         `tfsdk:"input_type"`
	ConnectorSpecificConfig jsontypes.Normalized `tfsdk:"connector_specific_config"`
	RefreshFreq             types.Int64          `tfsdk:"refresh_freq"`
	PruneFreq               types.Int64          `tfsdk:"prune_freq"`
	IndexingStart           types.String         `tfsdk:"indexing_start"`
	CredentialIDs           types.List           `tfsdk:"credential_ids"`
}

func (r *connectorResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_connector"
}

func (r *connectorResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "A connector definition: what to index and how often. A connector on its own " +
			"indexes nothing — pair it with an `onyx_credential` to start indexing.\n\n" +
			"Access control is not set here. Onyx applies it when a credential is associated, so it " +
			"belongs to the connector-credential pair.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Numeric connector id.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"name": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Connector name. Must be unique for the source.",
			},
			"source": schema.StringAttribute{
				Required: true,
				MarkdownDescription: "Source system, lowercase, e.g. `web`, `confluence`, `google_drive`. " +
					"Onyx rejects sources excluded by `ENABLED_CONNECTOR_TYPES`.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"input_type": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "How the connector reads: `load_state`, `poll`, `event`, or `slim_retrieval`.",
				Validators: []validator.String{
					stringvalidator.OneOf("load_state", "poll", "event", "slim_retrieval"),
				},
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"connector_specific_config": schema.StringAttribute{
				Required:   true,
				CustomType: jsontypes.NormalizedType{},
				MarkdownDescription: "Source-specific settings as a JSON object, e.g. " +
					"`jsonencode({ base_url = \"https://example.com\", web_connector_type = \"recursive\" })`.",
			},
			"refresh_freq": schema.Int64Attribute{
				Optional:            true,
				MarkdownDescription: "Seconds between index runs. Unset means index once, with no refresh.",
			},
			"prune_freq": schema.Int64Attribute{
				Optional: true,
				Computed: true,
				MarkdownDescription: "Seconds between pruning runs. Onyx rewrites an unset value to its " +
					"default of 604800 (7 days) on the first update, and Terraform then keeps that value.",
				PlanModifiers: []planmodifier.Int64{
					ServerDefaultedInt64(),
				},
			},
			"indexing_start": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "Earliest document timestamp to index, RFC 3339, e.g. " +
					"`2026-01-01T00:00:00Z`. Onyx ignores it on update, so changing it replaces the connector.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"credential_ids": schema.ListAttribute{
				Computed:            true,
				ElementType:         types.Int64Type,
				MarkdownDescription: "Ids of the credentials paired with this connector.",
			},
		},
	}
}

func (r *connectorResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

func (r *connectorResource) upsertFromModel(ctx context.Context, model connectorResourceModel, diags *diag.Diagnostics) (client.ConnectorUpsert, bool) {
	config, ok := jsonObjectFromNormalized(model.ConnectorSpecificConfig, "connector_specific_config", diags)
	if !ok {
		return client.ConnectorUpsert{}, false
	}
	return client.ConnectorUpsert{
		Name:                    model.Name.ValueString(),
		Source:                  model.Source.ValueString(),
		InputType:               model.InputType.ValueString(),
		ConnectorSpecificConfig: config,
		RefreshFreq:             int64Pointer(model.RefreshFreq),
		PruneFreq:               int64Pointer(model.PruneFreq),
		IndexingStart:           stringPointer(model.IndexingStart),
		// Required by the request body but ignored by both handlers: access
		// control is applied when a credential is associated, on the cc-pair.
		AccessType: "public",
		Groups:     []int64{},
	}, true
}

// applyRemote copies the server's view of a connector into the model.
func applyRemote(ctx context.Context, model *connectorResourceModel, remote *client.Connector, diags *diag.Diagnostics) bool {
	config, ok := normalizedFromJSONObject(remote.ConnectorSpecificConfig, "connector_specific_config", diags)
	if !ok {
		return false
	}
	credentialIDs, listDiags := types.ListValueFrom(ctx, types.Int64Type, remote.CredentialIDs)
	diags.Append(listDiags...)
	if listDiags.HasError() {
		return false
	}

	model.ID = types.StringValue(strconv.FormatInt(remote.ID, 10))
	model.Name = types.StringValue(remote.Name)
	model.Source = types.StringValue(remote.Source)
	model.InputType = types.StringValue(remote.InputType)
	model.ConnectorSpecificConfig = config
	model.RefreshFreq = types.Int64PointerValue(remote.RefreshFreq)
	model.PruneFreq = types.Int64PointerValue(remote.PruneFreq)
	model.IndexingStart = types.StringPointerValue(remote.IndexingStart)
	model.CredentialIDs = credentialIDs
	return true
}

func (r *connectorResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan connectorResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	upsert, ok := r.upsertFromModel(ctx, plan, &resp.Diagnostics)
	if !ok {
		return
	}

	id, err := r.client.CreateConnector(ctx, upsert)
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx connector", err.Error())
		return
	}

	// Create returns only the id, so read back for the computed attributes.
	remote, err := r.client.GetConnector(ctx, id)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read back the new Onyx connector", err.Error())
		// Persist the id so the next apply updates instead of creating a duplicate.
		plan.ID = types.StringValue(strconv.FormatInt(id, 10))
		resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
		return
	}
	if !applyRemote(ctx, &plan, remote, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *connectorResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state connectorResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "connector", &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.GetConnector(ctx, id)
	if client.IsNotFound(err) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx connector", err.Error())
		return
	}
	if !applyRemote(ctx, &state, remote, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *connectorResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state connectorResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "connector", &resp.Diagnostics)
	if !ok {
		return
	}
	upsert, ok := r.upsertFromModel(ctx, plan, &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.UpdateConnector(ctx, id, upsert)
	if err != nil {
		resp.Diagnostics.AddError("Failed to update Onyx connector", err.Error())
		return
	}
	if !applyRemote(ctx, &plan, remote, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *connectorResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state connectorResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "connector", &resp.Diagnostics)
	if !ok {
		return
	}

	if err := r.client.DeleteConnector(ctx, id); err != nil && !client.IsNotFound(err) {
		resp.Diagnostics.AddError("Failed to delete Onyx connector", err.Error())
	}
}

func (r *connectorResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
