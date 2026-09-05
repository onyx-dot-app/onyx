package provider

import (
	"context"
	"regexp"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework-validators/mapvalidator"
	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/booldefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/setdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/tfsdk"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                = (*llmProviderResource)(nil)
	_ resource.ResourceWithConfigure   = (*llmProviderResource)(nil)
	_ resource.ResourceWithImportState = (*llmProviderResource)(nil)
)

// NewLLMProviderResource returns the onyx_llm_provider resource.
func NewLLMProviderResource() resource.Resource {
	return &llmProviderResource{}
}

type llmProviderResource struct {
	client *client.Client
}

type llmProviderResourceModel struct {
	ID                    types.String `tfsdk:"id"`
	Name                  types.String `tfsdk:"name"`
	ProviderType          types.String `tfsdk:"provider_type"`
	APIKey                types.String `tfsdk:"api_key"`
	APIKeyWO              types.String `tfsdk:"api_key_wo"`
	APIKeyWOVersion       types.Int64  `tfsdk:"api_key_wo_version"`
	APIBase               types.String `tfsdk:"api_base"`
	APIVersion            types.String `tfsdk:"api_version"`
	DeploymentName        types.String `tfsdk:"deployment_name"`
	CustomConfig          types.Map    `tfsdk:"custom_config"`
	CustomConfigWO        types.Map    `tfsdk:"custom_config_wo"`
	CustomConfigWOVersion types.Int64  `tfsdk:"custom_config_wo_version"`
	IsPublic              types.Bool   `tfsdk:"is_public"`
	IsAutoMode            types.Bool   `tfsdk:"is_auto_mode"`
	Groups                types.Set    `tfsdk:"groups"`
	Personas              types.Set    `tfsdk:"personas"`
	ForceDelete           types.Bool   `tfsdk:"force_delete"`
	ModelConfigurations   types.Set    `tfsdk:"model_configurations"`
}

type modelConfigurationModel struct {
	Name               types.String `tfsdk:"name"`
	IsVisible          types.Bool   `tfsdk:"is_visible"`
	MaxInputTokens     types.Int64  `tfsdk:"max_input_tokens"`
	SupportsImageInput types.Bool   `tfsdk:"supports_image_input"`
	SupportsReasoning  types.Bool   `tfsdk:"supports_reasoning"`
	DisplayName        types.String `tfsdk:"display_name"`
	CustomDisplayName  types.String `tfsdk:"custom_display_name"`
}

var modelConfigurationAttrTypes = map[string]attr.Type{
	"name":                 types.StringType,
	"is_visible":           types.BoolType,
	"max_input_tokens":     types.Int64Type,
	"supports_image_input": types.BoolType,
	"supports_reasoning":   types.BoolType,
	"display_name":         types.StringType,
	"custom_display_name":  types.StringType,
}

func (r *llmProviderResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_llm_provider"
}

func (r *llmProviderResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	emptyInt64Set := types.SetValueMust(types.Int64Type, []attr.Value{})

	resp.Schema = schema.Schema{
		MarkdownDescription: "An Onyx LLM provider (OpenAI, Anthropic, Azure, Bedrock, ...) with its " +
			"enabled models. `model_configurations` is the full list of record: models omitted from it " +
			"are removed server-side on apply, and removing the model that is currently the deployment " +
			"default fails validation — repoint the default first. `api_key` and `custom_config` are " +
			"masked by the API on read, so out-of-band changes to them cannot be detected as drift.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Numeric provider id.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"name": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Display name for the provider configuration.",
			},
			"provider_type": schema.StringAttribute{
				Required: true,
				MarkdownDescription: "LiteLLM provider key, e.g. `openai`, `anthropic`, `azure`, " +
					"`bedrock`, `vertex_ai`, `ollama`. Must be lowercase.",
				Validators: []validator.String{
					stringvalidator.RegexMatches(
						regexp.MustCompile(`^[a-z0-9_-]+$`),
						"must be a lowercase LiteLLM provider key (letters, digits, '_', '-')",
					),
				},
			},
			"api_key": schema.StringAttribute{
				Optional:  true,
				Sensitive: true,
				MarkdownDescription: "Provider API key. The Onyx API masks this on read, so Terraform " +
					"cannot detect out-of-band changes; the configured value is authoritative." +
					writeOnlyDescription("api_key"),
			},
			"api_key_wo": schema.StringAttribute{
				Optional:  true,
				Sensitive: true,
				WriteOnly: true,
				MarkdownDescription: "Provider API key, held only in configuration. Terraform sends it on " +
					"every apply and stores nothing, so the key never reaches state. Pair it with " +
					"`api_key_wo_version` to rotate it. Needs Terraform 1.11 or later.",
				Validators: []validator.String{
					stringvalidator.ConflictsWith(path.MatchRoot("api_key")),
				},
			},
			"api_key_wo_version": writeOnlyVersionAttribute("api_key_wo"),
			"api_base": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Custom API base URL (e.g. for Azure or self-hosted gateways).",
			},
			"api_version": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "API version (Azure).",
			},
			"deployment_name": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Deployment name (Azure).",
			},
			"custom_config": schema.MapAttribute{
				ElementType: types.StringType,
				Optional:    true,
				Sensitive:   true,
				MarkdownDescription: "Provider-specific config key/values (e.g. Vertex service-account " +
					"JSON, Bedrock credentials). Masked on read like `api_key`." +
					writeOnlyDescription("custom_config"),
			},
			"custom_config_wo": schema.MapAttribute{
				ElementType: types.StringType,
				Optional:    true,
				Sensitive:   true,
				WriteOnly:   true,
				MarkdownDescription: "Provider-specific config key/values, held only in configuration. " +
					"Terraform sends them on every apply and stores nothing, so they never reach state. " +
					"Pair with `custom_config_wo_version` to rotate them. Needs Terraform 1.11 or later.",
				Validators: []validator.Map{
					mapvalidator.ConflictsWith(path.MatchRoot("custom_config")),
				},
			},
			"custom_config_wo_version": writeOnlyVersionAttribute("custom_config_wo"),
			"is_public": schema.BoolAttribute{
				Optional:            true,
				Computed:            true,
				Default:             booldefault.StaticBool(true),
				MarkdownDescription: "Whether the provider is available to all users.",
			},
			"is_auto_mode": schema.BoolAttribute{
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(false),
				MarkdownDescription: "Onyx Auto mode: the model list is managed by Onyx. When enabled, " +
					"the server owns `model_configurations`: Terraform stops drift-checking the list, " +
					"and updates re-assert the server's current models instead of the configured ones, " +
					"so registry-managed models are never removed.",
			},
			"groups": schema.SetAttribute{
				ElementType:         types.Int64Type,
				Optional:            true,
				Computed:            true,
				Default:             setdefault.StaticValue(emptyInt64Set),
				MarkdownDescription: "User group ids the provider is restricted to (EE).",
			},
			"personas": schema.SetAttribute{
				ElementType:         types.Int64Type,
				Optional:            true,
				Computed:            true,
				Default:             setdefault.StaticValue(emptyInt64Set),
				MarkdownDescription: "Persona ids the provider is restricted to.",
			},
			"force_delete": schema.BoolAttribute{
				Optional: true,
				MarkdownDescription: "Allow destroying this provider even while it holds the deployment " +
					"default model. Defaults to false, where such a destroy fails.",
			},
			"model_configurations": schema.SetNestedAttribute{
				Required: true,
				MarkdownDescription: "The complete set of models enabled on this provider. Applies " +
					"replace the server-side list with exactly this set.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"name": schema.StringAttribute{
							Required:            true,
							MarkdownDescription: "Model name as known to the provider, e.g. `gpt-5-mini`.",
						},
						"is_visible": schema.BoolAttribute{
							Optional:            true,
							Computed:            true,
							Default:             booldefault.StaticBool(true),
							MarkdownDescription: "Whether the model is selectable in the UI.",
						},
						"max_input_tokens": schema.Int64Attribute{
							Optional:            true,
							MarkdownDescription: "Override for the model's max input tokens; unset uses the model's known default.",
						},
						"supports_image_input": schema.BoolAttribute{
							Optional:            true,
							MarkdownDescription: "Override for image-input support; unset lets Onyx infer it.",
						},
						"supports_reasoning": schema.BoolAttribute{
							Optional:            true,
							MarkdownDescription: "Override for reasoning-model classification; unset lets Onyx infer it.",
						},
						"display_name": schema.StringAttribute{
							Optional:            true,
							MarkdownDescription: "Source-API display name (dynamic providers such as OpenRouter/Ollama).",
						},
						"custom_display_name": schema.StringAttribute{
							Optional:            true,
							MarkdownDescription: "Admin-specified display-name override.",
						},
					},
				},
			},
		},
	}
}

func (r *llmProviderResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// llmProviderSecrets carries the secret values in force for one apply, each
// resolved from either the stored attribute or its write-only twin.
type llmProviderSecrets struct {
	apiKey       types.String
	customConfig types.Map
}

// resolveLLMProviderSecrets reads the write-only twins, which live in
// configuration only.
func resolveLLMProviderSecrets(ctx context.Context, config tfsdk.Config, plan llmProviderResourceModel, diags *diag.Diagnostics) llmProviderSecrets {
	return llmProviderSecrets{
		apiKey:       resolveWriteOnly(ctx, config, path.Root("api_key_wo"), plan.APIKey, diags),
		customConfig: resolveWriteOnly(ctx, config, path.Root("custom_config_wo"), plan.CustomConfig, diags),
	}
}

// buildUpsertRequest converts a plan into the API's full-replace upsert body.
func (r *llmProviderResource) buildUpsertRequest(ctx context.Context, plan llmProviderResourceModel, id *int64, secrets llmProviderSecrets, apiKeyChanged bool, customConfigChanged bool, diags *diag.Diagnostics) client.LLMProviderUpsertRequest {
	upsert := client.LLMProviderUpsertRequest{
		ID:                  id,
		Name:                plan.Name.ValueStringPointer(),
		Provider:            plan.ProviderType.ValueString(),
		APIKey:              secrets.apiKey.ValueStringPointer(),
		APIBase:             plan.APIBase.ValueStringPointer(),
		APIVersion:          plan.APIVersion.ValueStringPointer(),
		DeploymentName:      plan.DeploymentName.ValueStringPointer(),
		IsPublic:            plan.IsPublic.ValueBool(),
		IsAutoMode:          plan.IsAutoMode.ValueBool(),
		APIKeyChanged:       apiKeyChanged,
		CustomConfigChanged: customConfigChanged,
	}

	if !secrets.customConfig.IsNull() {
		customConfig := map[string]string{}
		diags.Append(secrets.customConfig.ElementsAs(ctx, &customConfig, false)...)
		upsert.CustomConfig = customConfig
	}
	diags.Append(plan.Groups.ElementsAs(ctx, &upsert.Groups, false)...)
	diags.Append(plan.Personas.ElementsAs(ctx, &upsert.Personas, false)...)

	var modelConfigs []modelConfigurationModel
	diags.Append(plan.ModelConfigurations.ElementsAs(ctx, &modelConfigs, false)...)
	for _, mc := range modelConfigs {
		upsert.ModelConfigurations = append(upsert.ModelConfigurations, client.ModelConfigurationUpsert{
			Name:               mc.Name.ValueString(),
			IsVisible:          mc.IsVisible.ValueBool(),
			MaxInputTokens:     mc.MaxInputTokens.ValueInt64Pointer(),
			SupportsImageInput: mc.SupportsImageInput.ValueBoolPointer(),
			SupportsReasoning:  mc.SupportsReasoning.ValueBoolPointer(),
			DisplayName:        mc.DisplayName.ValueStringPointer(),
			CustomDisplayName:  mc.CustomDisplayName.ValueStringPointer(),
		})
	}
	return upsert
}

func (r *llmProviderResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan llmProviderResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	secrets := resolveLLMProviderSecrets(ctx, req.Config, plan, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}

	upsert := r.buildUpsertRequest(ctx, plan, nil, secrets,
		!secrets.apiKey.IsNull(), !secrets.customConfig.IsNull(), &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}

	view, err := r.client.UpsertLLMProvider(ctx, upsert, true)
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx LLM provider", err.Error())
		return
	}

	// State is the plan (config is authoritative for secrets and per-model
	// fields) plus the server-assigned id.
	plan.ID = types.StringValue(strconv.FormatInt(view.ID, 10))
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *llmProviderResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state llmProviderResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "LLM provider", &resp.Diagnostics)
	if !ok {
		return
	}

	view, err := r.client.GetLLMProvider(ctx, id)
	if client.IsNotFound(err) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx LLM provider", err.Error())
		return
	}

	state.Name = types.StringPointerValue(view.Name)
	state.ProviderType = types.StringValue(view.Provider)
	state.APIBase = types.StringPointerValue(view.APIBase)
	state.APIVersion = types.StringPointerValue(view.APIVersion)
	state.DeploymentName = types.StringPointerValue(view.DeploymentName)
	state.IsPublic = types.BoolValue(view.IsPublic)
	state.IsAutoMode = types.BoolValue(view.IsAutoMode)

	groups, diags := types.SetValueFrom(ctx, types.Int64Type, view.Groups)
	resp.Diagnostics.Append(diags...)
	state.Groups = groups
	personas, diags := types.SetValueFrom(ctx, types.Int64Type, view.Personas)
	resp.Diagnostics.Append(diags...)
	state.Personas = personas

	// api_key/custom_config are masked in responses; carry the real values
	// forward from prior state and never let a masked placeholder in.

	// Under auto mode the server owns the model list; keep prior state.
	if !view.IsAutoMode {
		state.ModelConfigurations = r.reconcileModelConfigurations(ctx, state.ModelConfigurations, view.ModelConfigurations, &resp.Diagnostics)
		if resp.Diagnostics.HasError() {
			return
		}
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

// reconcileModelConfigurations refreshes membership (by name) and the
// persisted fields (is_visible, custom_display_name); the other per-model
// fields are server-enriched resolved values that would show phantom drift,
// so prior state is kept for them.
func (r *llmProviderResource) reconcileModelConfigurations(ctx context.Context, prior types.Set, remote []client.ModelConfigurationView, diags *diag.Diagnostics) types.Set {
	var priorConfigs []modelConfigurationModel
	if !prior.IsNull() && !prior.IsUnknown() {
		diags.Append(prior.ElementsAs(ctx, &priorConfigs, false)...)
		if diags.HasError() {
			return prior
		}
	}

	remoteNames := map[string]client.ModelConfigurationView{}
	for _, mc := range remote {
		remoteNames[mc.Name] = mc
	}

	var result []modelConfigurationModel
	seen := map[string]bool{}
	for _, mc := range priorConfigs {
		if remoteMC, exists := remoteNames[mc.Name.ValueString()]; exists {
			mc.IsVisible = types.BoolValue(remoteMC.IsVisible)
			mc.CustomDisplayName = types.StringPointerValue(remoteMC.CustomDisplayName)
			result = append(result, mc)
			seen[mc.Name.ValueString()] = true
		}
	}
	for _, mc := range remote {
		if seen[mc.Name] {
			continue
		}
		result = append(result, modelConfigurationModel{
			Name:               types.StringValue(mc.Name),
			IsVisible:          types.BoolValue(mc.IsVisible),
			MaxInputTokens:     types.Int64PointerValue(mc.MaxInputTokens),
			SupportsImageInput: types.BoolValue(mc.SupportsImageInput),
			SupportsReasoning:  types.BoolValue(mc.SupportsReasoning),
			DisplayName:        types.StringPointerValue(mc.DisplayName),
			CustomDisplayName:  types.StringPointerValue(mc.CustomDisplayName),
		})
	}

	set, setDiags := types.SetValueFrom(ctx, types.ObjectType{AttrTypes: modelConfigurationAttrTypes}, result)
	diags.Append(setDiags...)
	return set
}

func (r *llmProviderResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state llmProviderResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "LLM provider", &resp.Diagnostics)
	if !ok {
		return
	}

	secrets := resolveLLMProviderSecrets(ctx, req.Config, plan, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}

	// State holds real (never masked) secrets, so resend them with the changed
	// flags on whenever either side has a value. A write-only secret sits in
	// configuration on every apply, so it rides along the same way.
	apiKeyChanged := !secrets.apiKey.IsNull() || !state.APIKey.IsNull()
	customConfigChanged := !secrets.customConfig.IsNull() || !state.CustomConfig.IsNull()

	upsert := r.buildUpsertRequest(ctx, plan, &id, secrets, apiKeyChanged, customConfigChanged, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}

	// Steady-state auto mode has no server-side model protection (only the
	// transition preserves models), so re-assert the server's current list
	// instead of the configured one. The read is the API's filtered display
	// view and not atomic with the write — admin-UI parity, see README.
	if plan.IsAutoMode.ValueBool() {
		view, err := r.client.GetLLMProvider(ctx, id)
		if err != nil {
			resp.Diagnostics.AddError(
				"Failed to read Onyx LLM provider before update",
				"The provider is in auto mode, so its current model list must be carried "+
					"through the update.\n\n"+err.Error(),
			)
			return
		}
		upsert.ModelConfigurations = modelConfigUpsertsFromViews(view.ModelConfigurations)
	}

	if _, err := r.client.UpsertLLMProvider(ctx, upsert, false); err != nil {
		resp.Diagnostics.AddError("Failed to update Onyx LLM provider", err.Error())
		return
	}

	plan.ID = state.ID
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

// modelConfigUpsertsFromViews re-asserts the server's model list in upsert
// form; the API has no way to leave the list untouched.
func modelConfigUpsertsFromViews(views []client.ModelConfigurationView) []client.ModelConfigurationUpsert {
	out := make([]client.ModelConfigurationUpsert, 0, len(views))
	for _, mc := range views {
		out = append(out, client.ModelConfigurationUpsert{
			Name:               mc.Name,
			IsVisible:          mc.IsVisible,
			MaxInputTokens:     mc.MaxInputTokens,
			SupportsImageInput: &mc.SupportsImageInput,
			SupportsReasoning:  &mc.SupportsReasoning,
			DisplayName:        mc.DisplayName,
			CustomDisplayName:  mc.CustomDisplayName,
		})
	}
	return out
}

func (r *llmProviderResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state llmProviderResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "LLM provider", &resp.Diagnostics)
	if !ok {
		return
	}

	err := r.client.DeleteLLMProvider(ctx, id, state.ForceDelete.ValueBool())
	if err != nil && !client.IsNotFound(err) {
		resp.Diagnostics.AddError(
			"Failed to delete Onyx LLM provider",
			err.Error()+"\n\nIf this provider holds the deployment default model, either repoint "+
				"the default first or set force_delete = true.",
		)
	}
}

func (r *llmProviderResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
