package provider

import (
	"context"
	"errors"

	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
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
	_ resource.Resource                = (*embeddingProviderResource)(nil)
	_ resource.ResourceWithConfigure   = (*embeddingProviderResource)(nil)
	_ resource.ResourceWithImportState = (*embeddingProviderResource)(nil)
)

// NewEmbeddingProviderResource returns the onyx_embedding_provider resource.
func NewEmbeddingProviderResource() resource.Resource {
	return &embeddingProviderResource{}
}

type embeddingProviderResource struct {
	client *client.Client
}

type embeddingProviderResourceModel struct {
	ID             types.String `tfsdk:"id"`
	ProviderType   types.String `tfsdk:"provider_type"`
	APIKey         types.String `tfsdk:"api_key"`
	APIURL         types.String `tfsdk:"api_url"`
	APIVersion     types.String `tfsdk:"api_version"`
	DeploymentName types.String `tfsdk:"deployment_name"`
}

func (r *embeddingProviderResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_embedding_provider"
}

func (r *embeddingProviderResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "A cloud embedding provider credential (one per provider type). " +
			"`api_key` is masked by the API on read, so out-of-band changes cannot be detected; " +
			"the configured value is authoritative and is resent on every update. The " +
			"currently-active embedding provider cannot be deleted (the API offers no override) — " +
			"switch search settings off it first.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Same as `provider_type` (the API's natural key).",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"provider_type": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Provider type: `openai`, `cohere`, `voyage`, `google`, `litellm`, or `azure`. Changing it replaces the resource.",
				Validators: []validator.String{
					stringvalidator.OneOf("openai", "cohere", "voyage", "google", "litellm", "azure"),
				},
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"api_key": schema.StringAttribute{
				Optional:  true,
				Sensitive: true,
				MarkdownDescription: "Provider API key. Keep this set in configuration: because the API " +
					"has no keep-stored-key flag, an update applied without it clears the stored key.",
			},
			"api_url": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Custom API URL (LiteLLM proxy, Azure).",
			},
			"api_version": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "API version (Azure).",
			},
			"deployment_name": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Deployment name (Azure).",
			},
		},
	}
}

func (r *embeddingProviderResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// upsertFromPlan builds the full-replace upsert body. Values always come from
// the plan — NEVER from a GET response, whose api_key is masked: with no
// api_key_changed-style flag on this endpoint, a masked value written back
// would permanently corrupt the stored key.
func upsertFromPlan(plan embeddingProviderResourceModel) client.CloudEmbeddingProvider {
	return client.CloudEmbeddingProvider{
		ProviderType:   plan.ProviderType.ValueString(),
		APIKey:         plan.APIKey.ValueStringPointer(),
		APIURL:         plan.APIURL.ValueStringPointer(),
		APIVersion:     plan.APIVersion.ValueStringPointer(),
		DeploymentName: plan.DeploymentName.ValueStringPointer(),
	}
}

func (r *embeddingProviderResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan embeddingProviderResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	if _, err := r.client.UpsertEmbeddingProvider(ctx, upsertFromPlan(plan)); err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx embedding provider", err.Error())
		return
	}

	plan.ID = plan.ProviderType
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *embeddingProviderResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state embeddingProviderResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	remote, err := r.client.GetEmbeddingProvider(ctx, state.ID.ValueString())
	if client.IsNotFound(err) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx embedding provider", err.Error())
		return
	}

	state.ProviderType = types.StringValue(remote.ProviderType)
	state.APIURL = types.StringPointerValue(remote.APIURL)
	state.APIVersion = types.StringPointerValue(remote.APIVersion)
	state.DeploymentName = types.StringPointerValue(remote.DeploymentName)
	// state.APIKey is carried forward: the response value is masked and must
	// never reach state (or, worse, a later upsert body).
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *embeddingProviderResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state embeddingProviderResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	if plan.APIKey.IsNull() && state.APIKey.IsNull() {
		// No key in config or state (e.g. imported resource): the upsert
		// below overwrites the stored key with null. Surface it rather than
		// clearing silently.
		resp.Diagnostics.AddWarning(
			"Stored embedding API key may be cleared",
			"onyx_embedding_provider has no api_key in configuration, and the Onyx API replaces all "+
				"fields on update — any key stored server-side is now cleared. Set api_key to manage it.",
		)
	}

	if _, err := r.client.UpsertEmbeddingProvider(ctx, upsertFromPlan(plan)); err != nil {
		resp.Diagnostics.AddError("Failed to update Onyx embedding provider", err.Error())
		return
	}

	plan.ID = state.ID
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *embeddingProviderResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state embeddingProviderResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	err := r.client.DeleteEmbeddingProvider(ctx, state.ID.ValueString())
	if err != nil && !client.IsNotFound(err) {
		var apiErr *client.APIError
		if errors.As(err, &apiErr) && apiErr.StatusCode == 400 {
			resp.Diagnostics.AddError(
				"Cannot delete the active embedding provider",
				err.Error()+"\n\nThe Onyx API refuses to delete the embedding provider used by current "+
					"search settings, with no override. Switch search settings to another provider first.",
			)
			return
		}
		resp.Diagnostics.AddError("Failed to delete Onyx embedding provider", err.Error())
	}
}

func (r *embeddingProviderResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	// The import id is the provider_type; it lands in both id and provider_type.
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, path.Root("id"), req.ID)...)
	resp.Diagnostics.Append(resp.State.SetAttribute(ctx, path.Root("provider_type"), req.ID)...)
}
