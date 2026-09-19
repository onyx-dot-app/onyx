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
}

func (r *llmProviderDefaultResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_llm_provider_default"
}

func (r *llmProviderDefaultResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "The deployment-wide default LLM model — a singleton pointer at one " +
			"provider + model pair (plus optional vision and chat auto-naming defaults). Managing it " +
			"as its own resource lets `depends_on` ordering repoint the default before the provider " +
			"holding it is deleted or shrunk. Onyx has no unset API for the text and vision defaults, " +
			"so destroying this resource leaves them in place; the chat-naming default is cleared when " +
			"managed.",
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
		},
	}
}

func (r *llmProviderDefaultResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// apply makes up to three writes, overlaying each success onto base. On
// failure it returns the partial result plus whether anything was written,
// so callers persist exactly what changed server-side.
func (r *llmProviderDefaultResource) apply(ctx context.Context, plan, base llmProviderDefaultResourceModel, clearChatNaming bool, diags *diag.Diagnostics) (llmProviderDefaultResourceModel, bool) {
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

	// Unlike text/vision, the chat-naming default has an unset endpoint, so
	// removing the pair from configuration clears the server value.
	switch {
	case !plan.ChatNamingProviderID.IsNull():
		chatNamingProviderID, ok := parseID(plan.ChatNamingProviderID, "LLM provider", diags)
		if !ok {
			return result, true
		}
		if err := r.client.SetDefaultChatNamingModel(ctx, client.DefaultModel{
			ProviderID: chatNamingProviderID,
			ModelName:  plan.ChatNamingModelName.ValueString(),
		}); err != nil {
			diags.AddError("Failed to set the chat auto-naming model", err.Error())
			return result, true
		}
		result.ChatNamingProviderID = plan.ChatNamingProviderID
		result.ChatNamingModelName = plan.ChatNamingModelName
	case clearChatNaming:
		if err := r.client.ClearDefaultChatNamingModel(ctx); err != nil {
			diags.AddError("Failed to clear the chat auto-naming model", err.Error())
			return result, true
		}
		result.ChatNamingProviderID = types.StringNull()
		result.ChatNamingModelName = types.StringNull()
	default:
		result.ChatNamingProviderID = types.StringNull()
		result.ChatNamingModelName = types.StringNull()
	}
	return result, true
}

func (r *llmProviderDefaultResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan llmProviderDefaultResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}
	model, wrote := r.apply(ctx, plan, llmProviderDefaultResourceModel{}, false, &resp.Diagnostics)
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

	// The vision and chat-naming defaults are only refreshed when managed
	// (set in state): unmanaged, they stay null even if configured server-side.
	if !state.VisionProviderID.IsNull() {
		if list.DefaultVision == nil {
			state.VisionProviderID = types.StringNull()
			state.VisionModelName = types.StringNull()
		} else {
			state.VisionProviderID = types.StringValue(strconv.FormatInt(list.DefaultVision.ProviderID, 10))
			state.VisionModelName = types.StringValue(list.DefaultVision.ModelName)
		}
	}
	if !state.ChatNamingProviderID.IsNull() {
		if list.DefaultChatNaming == nil {
			state.ChatNamingProviderID = types.StringNull()
			state.ChatNamingModelName = types.StringNull()
		} else {
			state.ChatNamingProviderID = types.StringValue(strconv.FormatInt(list.DefaultChatNaming.ProviderID, 10))
			state.ChatNamingModelName = types.StringValue(list.DefaultChatNaming.ModelName)
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
	clearChatNaming := plan.ChatNamingProviderID.IsNull() && !state.ChatNamingProviderID.IsNull()
	model, wrote := r.apply(ctx, plan, state, clearChatNaming, &resp.Diagnostics)
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
	if !state.ChatNamingProviderID.IsNull() {
		if err := r.client.ClearDefaultChatNamingModel(ctx); err != nil {
			resp.Diagnostics.AddError("Failed to clear the chat auto-naming model", err.Error())
			return
		}
		detail += " The managed chat-naming default was cleared."
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
	// server; the vision and chat-naming pairs stay null until configured.
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
