package provider

import (
	"context"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                = (*llmProviderDefaultResource)(nil)
	_ resource.ResourceWithConfigure   = (*llmProviderDefaultResource)(nil)
	_ resource.ResourceWithImportState = (*llmProviderDefaultResource)(nil)
)

const llmProviderDefaultResourceID = "default"

// NewLLMProviderDefaultResource returns the onyx_llm_provider_default resource.
func NewLLMProviderDefaultResource() resource.Resource {
	return &llmProviderDefaultResource{}
}

type llmProviderDefaultResource struct {
	client *client.Client
}

type llmProviderDefaultResourceModel struct {
	ID               types.String `tfsdk:"id"`
	ProviderID       types.String `tfsdk:"provider_id"`
	ModelName        types.String `tfsdk:"model_name"`
	VisionProviderID types.String `tfsdk:"vision_provider_id"`
	VisionModelName  types.String `tfsdk:"vision_model_name"`
}

func (r *llmProviderDefaultResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_llm_provider_default"
}

func (r *llmProviderDefaultResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "The deployment-wide default LLM model — a singleton pointer at one " +
			"provider + model pair (plus an optional vision default). Managing it as its own resource " +
			"lets `depends_on` ordering repoint the default before the provider holding it is deleted " +
			"or shrunk. Onyx has no unset-default API, so destroying this resource only removes it " +
			"from state.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Always `\"default\"`.",
			},
			"provider_id": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Id of the `onyx_llm_provider` holding the default model.",
			},
			"model_name": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Model name within that provider, e.g. `gpt-5-mini`. Must be one of its visible `model_configurations`.",
			},
			"vision_provider_id": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Provider id for the default vision model.",
				Validators: []validator.String{
					stringvalidator.AlsoRequires(path.MatchRoot("vision_model_name")),
				},
			},
			"vision_model_name": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Default vision model name.",
				Validators: []validator.String{
					stringvalidator.AlsoRequires(path.MatchRoot("vision_provider_id")),
				},
			},
		},
	}
}

func (r *llmProviderDefaultResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

func (r *llmProviderDefaultResource) apply(ctx context.Context, plan llmProviderDefaultResourceModel, diags *diag.Diagnostics) llmProviderDefaultResourceModel {
	providerID, ok := parseID(plan.ProviderID, "LLM provider", diags)
	if !ok {
		return plan
	}
	if err := r.client.SetDefaultLLMModel(ctx, client.DefaultModel{
		ProviderID: providerID,
		ModelName:  plan.ModelName.ValueString(),
	}); err != nil {
		diags.AddError("Failed to set the default LLM model", err.Error())
		return plan
	}

	if !plan.VisionProviderID.IsNull() {
		visionProviderID, ok := parseID(plan.VisionProviderID, "LLM provider", diags)
		if !ok {
			return plan
		}
		if err := r.client.SetDefaultVisionModel(ctx, client.DefaultModel{
			ProviderID: visionProviderID,
			ModelName:  plan.VisionModelName.ValueString(),
		}); err != nil {
			diags.AddError("Failed to set the default vision model", err.Error())
			return plan
		}
	}

	plan.ID = types.StringValue(llmProviderDefaultResourceID)
	return plan
}

func (r *llmProviderDefaultResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan llmProviderDefaultResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	plan = r.apply(ctx, plan, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *llmProviderDefaultResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state llmProviderDefaultResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	list, err := r.client.ListLLMProviders(ctx)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read the default LLM model", err.Error())
		return
	}
	if list.DefaultText == nil {
		resp.State.RemoveResource(ctx)
		return
	}

	state.ID = types.StringValue(llmProviderDefaultResourceID)
	state.ProviderID = types.StringValue(strconv.FormatInt(list.DefaultText.ProviderID, 10))
	state.ModelName = types.StringValue(list.DefaultText.ModelName)

	// The vision default is only refreshed when managed (set in state):
	// unmanaged, it stays null even if one is configured server-side.
	if !state.VisionProviderID.IsNull() {
		if list.DefaultVision == nil {
			state.VisionProviderID = types.StringNull()
			state.VisionModelName = types.StringNull()
		} else {
			state.VisionProviderID = types.StringValue(strconv.FormatInt(list.DefaultVision.ProviderID, 10))
			state.VisionModelName = types.StringValue(list.DefaultVision.ModelName)
		}
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *llmProviderDefaultResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan llmProviderDefaultResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	plan = r.apply(ctx, plan, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *llmProviderDefaultResource) Delete(_ context.Context, _ resource.DeleteRequest, resp *resource.DeleteResponse) {
	resp.Diagnostics.AddWarning(
		"Default LLM model left unchanged",
		"onyx_llm_provider_default was removed from Terraform state, but Onyx has no API to unset "+
			"the deployment default model, so it remains pointed at its current target.",
	)
}

func (r *llmProviderDefaultResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	if req.ID != llmProviderDefaultResourceID {
		resp.Diagnostics.AddError(
			"Invalid import id",
			"onyx_llm_provider_default is a singleton; import it with the fixed id \"default\".",
		)
		return
	}
	// The follow-up Read always refreshes provider_id/model_name from the
	// server; only the vision pair stays null until configured.
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
