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
	ID                   types.String `tfsdk:"id"`
	ProviderID           types.String `tfsdk:"provider_id"`
	ModelName            types.String `tfsdk:"model_name"`
	VisionProviderID     types.String `tfsdk:"vision_provider_id"`
	VisionModelName      types.String `tfsdk:"vision_model_name"`
	ChatNamingProviderID types.String `tfsdk:"chat_naming_provider_id"`
	ChatNamingModelName  types.String `tfsdk:"chat_naming_model_name"`
	CraftProviderID      types.String `tfsdk:"craft_provider_id"`
	CraftModelName       types.String `tfsdk:"craft_model_name"`
	// The search selection pair needs Onyx v5.0.0 or later.
	SearchSelectionProviderID types.String `tfsdk:"search_selection_provider_id"`
	SearchSelectionModelName  types.String `tfsdk:"search_selection_model_name"`
}

// clearableDefault is a default model pair that Onyx can also unset.
type clearableDefault struct {
	label      string
	providerID func(*llmProviderDefaultResourceModel) *types.String
	modelName  func(*llmProviderDefaultResourceModel) *types.String
	remote     func(*client.LLMProviderList) *client.DefaultModel
	set        func(*client.Client, context.Context, client.DefaultModel) error
	clear      func(*client.Client, context.Context) error
}

// clearableDefaults are applied, read and cleared the same way: setting the
// pair writes it, and removing a managed pair clears it.
var clearableDefaults = []clearableDefault{
	{
		label:      "chat auto-naming model",
		providerID: func(m *llmProviderDefaultResourceModel) *types.String { return &m.ChatNamingProviderID },
		modelName:  func(m *llmProviderDefaultResourceModel) *types.String { return &m.ChatNamingModelName },
		remote:     func(l *client.LLMProviderList) *client.DefaultModel { return l.DefaultChatNaming },
		set:        (*client.Client).SetDefaultChatNamingModel,
		clear:      (*client.Client).ClearDefaultChatNamingModel,
	},
	{
		label:      "default Craft model",
		providerID: func(m *llmProviderDefaultResourceModel) *types.String { return &m.CraftProviderID },
		modelName:  func(m *llmProviderDefaultResourceModel) *types.String { return &m.CraftModelName },
		remote:     func(l *client.LLMProviderList) *client.DefaultModel { return l.DefaultCraft },
		set:        (*client.Client).SetDefaultCraftModel,
		clear:      (*client.Client).ClearDefaultCraftModel,
	},
	{
		label:      "default search selection model",
		providerID: func(m *llmProviderDefaultResourceModel) *types.String { return &m.SearchSelectionProviderID },
		modelName:  func(m *llmProviderDefaultResourceModel) *types.String { return &m.SearchSelectionModelName },
		remote:     func(l *client.LLMProviderList) *client.DefaultModel { return l.DefaultSearchSelection },
		set:        (*client.Client).SetDefaultSearchSelectionModel,
		clear:      (*client.Client).ClearDefaultSearchSelectionModel,
	},
}

func (r *llmProviderDefaultResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_llm_provider_default"
}

func (r *llmProviderDefaultResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "The deployment-wide default LLM model — a singleton pointer at one " +
			"provider + model pair (plus optional vision, chat auto-naming, Craft and search selection " +
			"defaults). Managing it " +
			"as its own resource lets `depends_on` ordering repoint the default before the provider " +
			"holding it is deleted or shrunk. Onyx has no unset API for the text and vision defaults, " +
			"so destroying this resource leaves them in place. Destroy clears the chat-naming, Craft " +
			"and search selection defaults that the resource manages.",
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
				MarkdownDescription: "Model name within that provider, e.g. `gpt-6-luna`. Must be one of its visible `model_configurations`.",
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
			"chat_naming_provider_id": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "Provider id for the dedicated chat auto-naming model. Unset, " +
					"auto-naming uses the session's model. Removing the pair clears the server value.",
				Validators: []validator.String{
					stringvalidator.AlsoRequires(path.MatchRoot("chat_naming_model_name")),
				},
			},
			"chat_naming_model_name": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Dedicated chat auto-naming model name.",
				Validators: []validator.String{
					stringvalidator.AlsoRequires(path.MatchRoot("chat_naming_provider_id")),
				},
			},
			"craft_provider_id": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "Provider id for the default Onyx Craft model. Unset, Craft uses the " +
					"default text model. Removing the pair clears the server value.",
				Validators: []validator.String{
					stringvalidator.AlsoRequires(path.MatchRoot("craft_model_name")),
				},
			},
			"craft_model_name": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Default Onyx Craft model name.",
				Validators: []validator.String{
					stringvalidator.AlsoRequires(path.MatchRoot("craft_provider_id")),
				},
			},
			"search_selection_provider_id": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "Provider id for the model that selects search results. Unset, the " +
					"session's model selects them. Removing the pair clears the server value. Needs Onyx " +
					"v5.0.0 or later.",
				Validators: []validator.String{
					stringvalidator.AlsoRequires(path.MatchRoot("search_selection_model_name")),
				},
			},
			"search_selection_model_name": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Name of the model that selects search results. Needs Onyx v5.0.0 or later.",
				Validators: []validator.String{
					stringvalidator.AlsoRequires(path.MatchRoot("search_selection_provider_id")),
				},
			},
		},
	}
}

func (r *llmProviderDefaultResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// apply writes each configured default, overlaying each success onto base.
// It clears a clearable default that state manages and plan does not. On
// failure it returns the partial result plus whether anything was written,
// so callers persist exactly what changed server-side.
func (r *llmProviderDefaultResource) apply(ctx context.Context, plan, base llmProviderDefaultResourceModel, diags *diag.Diagnostics) (llmProviderDefaultResourceModel, bool) {
	result := base
	result.ID = types.StringValue(llmProviderDefaultResourceID)

	providerID, ok := parseID(plan.ProviderID, "LLM provider", diags)
	if !ok {
		return result, false
	}
	if err := r.client.SetDefaultLLMModel(ctx, client.DefaultModel{
		ProviderID: providerID,
		ModelName:  plan.ModelName.ValueString(),
	}); err != nil {
		diags.AddError("Failed to set the default LLM model", err.Error())
		return result, false
	}
	result.ProviderID = plan.ProviderID
	result.ModelName = plan.ModelName

	if plan.VisionProviderID.IsNull() {
		// No server write: the vision default just stops being managed.
		result.VisionProviderID = types.StringNull()
		result.VisionModelName = types.StringNull()
	} else {
		visionProviderID, ok := parseID(plan.VisionProviderID, "LLM provider", diags)
		if !ok {
			return result, true
		}
		if err := r.client.SetDefaultVisionModel(ctx, client.DefaultModel{
			ProviderID: visionProviderID,
			ModelName:  plan.VisionModelName.ValueString(),
		}); err != nil {
			diags.AddError("Failed to set the default vision model", err.Error())
			return result, true
		}
		result.VisionProviderID = plan.VisionProviderID
		result.VisionModelName = plan.VisionModelName
	}

	// Unlike text/vision, these defaults have an unset endpoint, so removing
	// a pair from configuration clears the server value.
	for _, d := range clearableDefaults {
		planProvider, planModel := d.providerID(&plan), d.modelName(&plan)
		resultProvider, resultModel := d.providerID(&result), d.modelName(&result)
		switch {
		case !planProvider.IsNull():
			providerID, ok := parseID(*planProvider, "LLM provider", diags)
			if !ok {
				return result, true
			}
			if err := d.set(r.client, ctx, client.DefaultModel{
				ProviderID: providerID,
				ModelName:  planModel.ValueString(),
			}); err != nil {
				diags.AddError("Failed to set the "+d.label, err.Error())
				return result, true
			}
			*resultProvider, *resultModel = *planProvider, *planModel
		case !resultProvider.IsNull():
			if err := d.clear(r.client, ctx); err != nil {
				diags.AddError("Failed to clear the "+d.label, err.Error())
				return result, true
			}
			*resultProvider, *resultModel = types.StringNull(), types.StringNull()
		}
	}
	return result, true
}

func (r *llmProviderDefaultResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan llmProviderDefaultResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	model, wrote := r.apply(ctx, plan, llmProviderDefaultResourceModel{}, &resp.Diagnostics)
	if resp.Diagnostics.HasError() && !wrote {
		return
	}
	// Set state even on partial failure so the server-side change is tracked.
	resp.Diagnostics.Append(resp.State.Set(ctx, model)...)
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

	// The optional defaults are only refreshed when managed (set in state):
	// unmanaged, they stay null even if configured server-side.
	if !state.VisionProviderID.IsNull() {
		if list.DefaultVision == nil {
			state.VisionProviderID = types.StringNull()
			state.VisionModelName = types.StringNull()
		} else {
			state.VisionProviderID = types.StringValue(strconv.FormatInt(list.DefaultVision.ProviderID, 10))
			state.VisionModelName = types.StringValue(list.DefaultVision.ModelName)
		}
	}
	for _, d := range clearableDefaults {
		providerID, modelName := d.providerID(&state), d.modelName(&state)
		if providerID.IsNull() {
			continue
		}
		if remote := d.remote(list); remote == nil {
			*providerID, *modelName = types.StringNull(), types.StringNull()
		} else {
			*providerID = types.StringValue(strconv.FormatInt(remote.ProviderID, 10))
			*modelName = types.StringValue(remote.ModelName)
		}
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *llmProviderDefaultResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state llmProviderDefaultResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	model, wrote := r.apply(ctx, plan, state, &resp.Diagnostics)
	if resp.Diagnostics.HasError() && !wrote {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, model)...)
}

func (r *llmProviderDefaultResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state llmProviderDefaultResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	detail := "onyx_llm_provider_default was removed from Terraform state, but Onyx has no API to " +
		"unset the deployment default text/vision models, so they remain pointed at their current targets."
	for _, d := range clearableDefaults {
		if d.providerID(&state).IsNull() {
			continue
		}
		if err := d.clear(r.client, ctx); err != nil {
			resp.Diagnostics.AddError("Failed to clear the "+d.label, err.Error())
			return
		}
		detail += " The managed " + d.label + " was cleared."
	}
	resp.Diagnostics.AddWarning("Default LLM model left unchanged", detail)
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
	// server; the optional pairs stay null until configured.
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
