package provider

import (
	"context"
	"errors"

	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                = (*settingsResource)(nil)
	_ resource.ResourceWithConfigure   = (*settingsResource)(nil)
	_ resource.ResourceWithImportState = (*settingsResource)(nil)
)

const settingsResourceID = "settings"

// NewSettingsResource returns the onyx_settings resource.
func NewSettingsResource() resource.Resource {
	return &settingsResource{}
}

type settingsResource struct {
	client *client.Client
}

type settingsResourceModel struct {
	ID types.String `tfsdk:"id"`

	// Writable: null means "unmanaged — leave the server value alone".
	MaximumChatRetentionDays          types.Float64 `tfsdk:"maximum_chat_retention_days"`
	CompanyName                       types.String  `tfsdk:"company_name"`
	CompanyDescription                types.String  `tfsdk:"company_description"`
	AnonymousUserEnabled              types.Bool    `tfsdk:"anonymous_user_enabled"`
	InviteOnlyEnabled                 types.Bool    `tfsdk:"invite_only_enabled"`
	DeepResearchEnabled               types.Bool    `tfsdk:"deep_research_enabled"`
	MultiModelChatEnabled             types.Bool    `tfsdk:"multi_model_chat_enabled"`
	SearchUIEnabled                   types.Bool    `tfsdk:"search_ui_enabled"`
	AutoDetectSearchFilters           types.Bool    `tfsdk:"auto_detect_search_filters"`
	TemperatureOverrideEnabled        types.Bool    `tfsdk:"temperature_override_enabled"`
	AutoScroll                        types.Bool    `tfsdk:"auto_scroll"`
	QueryHistoryType                  types.String  `tfsdk:"query_history_type"`
	HideQueryHistoryFromAdminPanel    types.Bool    `tfsdk:"hide_query_history_from_admin_panel"`
	ImageExtractionAndAnalysisEnabled types.Bool    `tfsdk:"image_extraction_and_analysis_enabled"`
	ImageAnalysisMaxSizeMB            types.Int64   `tfsdk:"image_analysis_max_size_mb"`
	UserKnowledgeEnabled              types.Bool    `tfsdk:"user_knowledge_enabled"`
	UserFileMaxUploadSizeMB           types.Int64   `tfsdk:"user_file_max_upload_size_mb"`
	FileTokenCountThresholdK          types.Int64   `tfsdk:"file_token_count_threshold_k"`
	ShowExtraConnectors               types.Bool    `tfsdk:"show_extra_connectors"`
	DisableDefaultAssistant           types.Bool    `tfsdk:"disable_default_assistant"`
	CraftDefaultEnabled               types.Bool    `tfsdk:"craft_default_enabled"`
	CraftInstructions                 types.String  `tfsdk:"craft_instructions"`
	OpenSearchIndexingEnabled         types.Bool    `tfsdk:"opensearch_indexing_enabled"`

	// License/deployment-derived, read-only.
	ApplicationStatus types.String `tfsdk:"application_status"`
	Tier              types.String `tfsdk:"tier"`
	EEFeaturesEnabled types.Bool   `tfsdk:"ee_features_enabled"`
	GPUEnabled        types.Bool   `tfsdk:"gpu_enabled"`
	SeatCount         types.Int64  `tfsdk:"seat_count"`
	UsedSeats         types.Int64  `tfsdk:"used_seats"`
}

func (r *settingsResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_settings"
}

func (r *settingsResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "The Onyx workspace settings singleton. Only attributes set in " +
			"configuration are managed: unset attributes are left untouched server-side, and " +
			"removing an attribute from configuration stops managing it rather than resetting it. " +
			"Deleting the resource only removes it from state — the live settings are not changed. " +
			"At most one `onyx_settings` resource should exist per deployment.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Always `\"settings\"`.",
			},
			"maximum_chat_retention_days": schema.Float64Attribute{
				Optional:            true,
				MarkdownDescription: "Days to retain chat history (Enterprise tier).",
			},
			"company_name": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Company name shown in the UI.",
			},
			"company_description": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Company description.",
			},
			"anonymous_user_enabled": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Allow anonymous access.",
			},
			"invite_only_enabled": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Restrict registration to invited users.",
			},
			"deep_research_enabled": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Enable the Deep Research feature.",
			},
			"multi_model_chat_enabled": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Allow chatting with multiple models side by side.",
			},
			"search_ui_enabled": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Enable Search Mode in the UI (Business+ tier).",
			},
			"auto_detect_search_filters": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Automatically detect search filters from queries.",
			},
			"temperature_override_enabled": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Let users override model temperature.",
			},
			"auto_scroll": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Auto-scroll chat responses.",
			},
			"query_history_type": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Query history mode: `disabled`, `anonymized`, or `normal`.",
				Validators: []validator.String{
					stringvalidator.OneOf("disabled", "anonymized", "normal"),
				},
			},
			"hide_query_history_from_admin_panel": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Hide the query history page in the admin panel (recording stays on).",
			},
			"image_extraction_and_analysis_enabled": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Extract and analyze images during indexing.",
			},
			"image_analysis_max_size_mb": schema.Int64Attribute{
				Optional:            true,
				MarkdownDescription: "Max image size for analysis, in MB.",
			},
			"user_knowledge_enabled": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Enable user-uploaded knowledge files.",
			},
			"user_file_max_upload_size_mb": schema.Int64Attribute{
				Optional:            true,
				MarkdownDescription: "Max user file upload size, in MB.",
			},
			"file_token_count_threshold_k": schema.Int64Attribute{
				Optional:            true,
				MarkdownDescription: "File token threshold (thousands) before indexing instead of inlining.",
			},
			"show_extra_connectors": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Show the extended connector catalog.",
			},
			"disable_default_assistant": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Disable the built-in default assistant.",
			},
			"craft_default_enabled": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "Workspace default for Onyx Craft access (per-user overrides win).",
			},
			"craft_instructions": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Workspace-wide instructions injected into every Craft agent (max 4000 chars).",
				Validators: []validator.String{
					stringvalidator.LengthAtMost(4000),
				},
			},
			"opensearch_indexing_enabled": schema.BoolAttribute{
				Optional:            true,
				MarkdownDescription: "OpenSearch migration flag; leave unmanaged unless you know you need it.",
			},
			"application_status": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "License/billing status (read-only).",
			},
			"tier": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Resolved license tier: `community`, `business`, or `enterprise` (read-only).",
			},
			"ee_features_enabled": schema.BoolAttribute{
				Computed:            true,
				MarkdownDescription: "Whether EE features are unlocked by the license (read-only).",
			},
			"gpu_enabled": schema.BoolAttribute{
				Computed:            true,
				MarkdownDescription: "Whether the deployment has GPU support (read-only).",
			},
			"seat_count": schema.Int64Attribute{
				Computed:            true,
				MarkdownDescription: "Licensed seat count (read-only).",
			},
			"used_seats": schema.Int64Attribute{
				Computed:            true,
				MarkdownDescription: "Seats in use (read-only).",
			},
		},
	}
}

func (r *settingsResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// overlay writes every non-null plan attribute onto a freshly-fetched
// Settings, leaving everything else (including license-derived fields) as the
// server returned it. This is what makes the whole-object PUT safe.
func overlaySettings(plan settingsResourceModel, fresh *client.Settings) {
	if !plan.MaximumChatRetentionDays.IsNull() {
		fresh.MaximumChatRetentionDays = plan.MaximumChatRetentionDays.ValueFloat64Pointer()
	}
	if !plan.CompanyName.IsNull() {
		fresh.CompanyName = plan.CompanyName.ValueStringPointer()
	}
	if !plan.CompanyDescription.IsNull() {
		fresh.CompanyDescription = plan.CompanyDescription.ValueStringPointer()
	}
	if !plan.AnonymousUserEnabled.IsNull() {
		fresh.AnonymousUserEnabled = plan.AnonymousUserEnabled.ValueBoolPointer()
	}
	if !plan.InviteOnlyEnabled.IsNull() {
		fresh.InviteOnlyEnabled = plan.InviteOnlyEnabled.ValueBool()
	}
	if !plan.DeepResearchEnabled.IsNull() {
		fresh.DeepResearchEnabled = plan.DeepResearchEnabled.ValueBoolPointer()
	}
	if !plan.MultiModelChatEnabled.IsNull() {
		fresh.MultiModelChatEnabled = plan.MultiModelChatEnabled.ValueBoolPointer()
	}
	if !plan.SearchUIEnabled.IsNull() {
		fresh.SearchUIEnabled = plan.SearchUIEnabled.ValueBoolPointer()
	}
	if !plan.AutoDetectSearchFilters.IsNull() {
		fresh.AutoDetectSearchFilters = plan.AutoDetectSearchFilters.ValueBoolPointer()
	}
	if !plan.TemperatureOverrideEnabled.IsNull() {
		fresh.TemperatureOverrideEnabled = plan.TemperatureOverrideEnabled.ValueBoolPointer()
	}
	if !plan.AutoScroll.IsNull() {
		fresh.AutoScroll = plan.AutoScroll.ValueBoolPointer()
	}
	if !plan.QueryHistoryType.IsNull() {
		fresh.QueryHistoryType = plan.QueryHistoryType.ValueStringPointer()
	}
	if !plan.HideQueryHistoryFromAdminPanel.IsNull() {
		fresh.HideQueryHistoryFromAdminPanel = plan.HideQueryHistoryFromAdminPanel.ValueBool()
	}
	if !plan.ImageExtractionAndAnalysisEnabled.IsNull() {
		fresh.ImageExtractionAndAnalysisEnabled = plan.ImageExtractionAndAnalysisEnabled.ValueBoolPointer()
	}
	if !plan.ImageAnalysisMaxSizeMB.IsNull() {
		fresh.ImageAnalysisMaxSizeMB = plan.ImageAnalysisMaxSizeMB.ValueInt64Pointer()
	}
	if !plan.UserKnowledgeEnabled.IsNull() {
		fresh.UserKnowledgeEnabled = plan.UserKnowledgeEnabled.ValueBoolPointer()
	}
	if !plan.UserFileMaxUploadSizeMB.IsNull() {
		fresh.UserFileMaxUploadSizeMB = plan.UserFileMaxUploadSizeMB.ValueInt64Pointer()
	}
	if !plan.FileTokenCountThresholdK.IsNull() {
		fresh.FileTokenCountThresholdK = plan.FileTokenCountThresholdK.ValueInt64Pointer()
	}
	if !plan.ShowExtraConnectors.IsNull() {
		fresh.ShowExtraConnectors = plan.ShowExtraConnectors.ValueBoolPointer()
	}
	if !plan.DisableDefaultAssistant.IsNull() {
		fresh.DisableDefaultAssistant = plan.DisableDefaultAssistant.ValueBoolPointer()
	}
	if !plan.CraftDefaultEnabled.IsNull() {
		fresh.CraftDefaultEnabled = plan.CraftDefaultEnabled.ValueBool()
	}
	if !plan.CraftInstructions.IsNull() {
		fresh.CraftInstructions = plan.CraftInstructions.ValueStringPointer()
	}
	if !plan.OpenSearchIndexingEnabled.IsNull() {
		fresh.OpenSearchIndexingEnabled = plan.OpenSearchIndexingEnabled.ValueBool()
	}
}

// refreshFromServer updates a model's attributes from the server: managed
// (non-null) writable attributes are refreshed for drift detection, unmanaged
// ones stay null, and computed attributes are always refreshed.
func refreshSettingsModel(model *settingsResourceModel, server *client.Settings) {
	if !model.MaximumChatRetentionDays.IsNull() {
		model.MaximumChatRetentionDays = types.Float64PointerValue(server.MaximumChatRetentionDays)
	}
	if !model.CompanyName.IsNull() {
		model.CompanyName = types.StringPointerValue(server.CompanyName)
	}
	if !model.CompanyDescription.IsNull() {
		model.CompanyDescription = types.StringPointerValue(server.CompanyDescription)
	}
	if !model.AnonymousUserEnabled.IsNull() {
		model.AnonymousUserEnabled = types.BoolPointerValue(server.AnonymousUserEnabled)
	}
	if !model.InviteOnlyEnabled.IsNull() {
		model.InviteOnlyEnabled = types.BoolValue(server.InviteOnlyEnabled)
	}
	if !model.DeepResearchEnabled.IsNull() {
		model.DeepResearchEnabled = types.BoolPointerValue(server.DeepResearchEnabled)
	}
	if !model.MultiModelChatEnabled.IsNull() {
		model.MultiModelChatEnabled = types.BoolPointerValue(server.MultiModelChatEnabled)
	}
	if !model.SearchUIEnabled.IsNull() {
		model.SearchUIEnabled = types.BoolPointerValue(server.SearchUIEnabled)
	}
	if !model.AutoDetectSearchFilters.IsNull() {
		model.AutoDetectSearchFilters = types.BoolPointerValue(server.AutoDetectSearchFilters)
	}
	if !model.TemperatureOverrideEnabled.IsNull() {
		model.TemperatureOverrideEnabled = types.BoolPointerValue(server.TemperatureOverrideEnabled)
	}
	if !model.AutoScroll.IsNull() {
		model.AutoScroll = types.BoolPointerValue(server.AutoScroll)
	}
	if !model.QueryHistoryType.IsNull() {
		model.QueryHistoryType = types.StringPointerValue(server.QueryHistoryType)
	}
	if !model.HideQueryHistoryFromAdminPanel.IsNull() {
		model.HideQueryHistoryFromAdminPanel = types.BoolValue(server.HideQueryHistoryFromAdminPanel)
	}
	if !model.ImageExtractionAndAnalysisEnabled.IsNull() {
		model.ImageExtractionAndAnalysisEnabled = types.BoolPointerValue(server.ImageExtractionAndAnalysisEnabled)
	}
	if !model.ImageAnalysisMaxSizeMB.IsNull() {
		model.ImageAnalysisMaxSizeMB = types.Int64PointerValue(server.ImageAnalysisMaxSizeMB)
	}
	if !model.UserKnowledgeEnabled.IsNull() {
		model.UserKnowledgeEnabled = types.BoolPointerValue(server.UserKnowledgeEnabled)
	}
	if !model.UserFileMaxUploadSizeMB.IsNull() {
		model.UserFileMaxUploadSizeMB = types.Int64PointerValue(server.UserFileMaxUploadSizeMB)
	}
	if !model.FileTokenCountThresholdK.IsNull() {
		model.FileTokenCountThresholdK = types.Int64PointerValue(server.FileTokenCountThresholdK)
	}
	if !model.ShowExtraConnectors.IsNull() {
		model.ShowExtraConnectors = types.BoolPointerValue(server.ShowExtraConnectors)
	}
	if !model.DisableDefaultAssistant.IsNull() {
		model.DisableDefaultAssistant = types.BoolPointerValue(server.DisableDefaultAssistant)
	}
	if !model.CraftDefaultEnabled.IsNull() {
		model.CraftDefaultEnabled = types.BoolValue(server.CraftDefaultEnabled)
	}
	if !model.CraftInstructions.IsNull() {
		model.CraftInstructions = types.StringPointerValue(server.CraftInstructions)
	}
	if !model.OpenSearchIndexingEnabled.IsNull() {
		model.OpenSearchIndexingEnabled = types.BoolValue(server.OpenSearchIndexingEnabled)
	}

	model.ApplicationStatus = types.StringValue(server.ApplicationStatus)
	model.Tier = types.StringValue(server.Tier)
	model.EEFeaturesEnabled = types.BoolValue(server.EEFeaturesEnabled)
	model.GPUEnabled = types.BoolPointerValue(server.GPUEnabled)
	model.SeatCount = types.Int64PointerValue(server.SeatCount)
	model.UsedSeats = types.Int64PointerValue(server.UsedSeats)
}

// apply implements both Create and Update: read-modify-write with the plan
// overlaid on a fresh GET, then a final GET to populate computed attributes.
func (r *settingsResource) apply(ctx context.Context, plan settingsResourceModel) (settingsResourceModel, error) {
	fresh, err := r.client.GetSettings(ctx)
	if err != nil {
		return plan, err
	}
	overlaySettings(plan, fresh)
	if err := r.client.PutSettings(ctx, *fresh); err != nil {
		return plan, err
	}

	applied, err := r.client.GetSettings(ctx)
	if err != nil {
		return plan, err
	}
	plan.ID = types.StringValue(settingsResourceID)
	refreshSettingsModel(&plan, applied)
	return plan, nil
}

// settingsErrorDetail augments tier-gating errors with an actionable hint.
func settingsErrorDetail(err error) string {
	var apiErr *client.APIError
	if errors.As(err, &apiErr) && apiErr.ErrorCode == "FEATURE_NOT_AVAILABLE" {
		return err.Error() + "\n\nThis setting requires a higher Onyx license tier (see the `tier` attribute)."
	}
	return err.Error()
}

func (r *settingsResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan settingsResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	state, err := r.apply(ctx, plan)
	if err != nil {
		resp.Diagnostics.AddError("Failed to apply Onyx settings", settingsErrorDetail(err))
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *settingsResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state settingsResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	server, err := r.client.GetSettings(ctx)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx settings", err.Error())
		return
	}
	state.ID = types.StringValue(settingsResourceID)
	refreshSettingsModel(&state, server)
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *settingsResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan settingsResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	state, err := r.apply(ctx, plan)
	if err != nil {
		resp.Diagnostics.AddError("Failed to apply Onyx settings", settingsErrorDetail(err))
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *settingsResource) Delete(ctx context.Context, _ resource.DeleteRequest, resp *resource.DeleteResponse) {
	// Resetting workspace-wide settings to factory defaults on destroy would
	// be a far larger blast radius than removing one resource warrants.
	resp.Diagnostics.AddWarning(
		"Onyx settings left unchanged",
		"onyx_settings was removed from Terraform state, but the live workspace settings were NOT "+
			"reset. Re-add the resource (or use the admin panel) to manage them again.",
	)
}

func (r *settingsResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	if req.ID != settingsResourceID {
		resp.Diagnostics.AddError(
			"Invalid import id",
			"onyx_settings is a singleton; import it with the fixed id \"settings\".",
		)
		return
	}
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
