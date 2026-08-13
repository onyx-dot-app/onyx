package provider

import (
	"context"
	"errors"

	"github.com/hashicorp/terraform-plugin-framework-validators/int64validator"
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
	ImageExtractionAndAnalysisEnabled types.Bool    `tfsdk:"image_extraction_and_analysis_enabled"`
	ImageAnalysisMaxSizeMB            types.Int64   `tfsdk:"image_analysis_max_size_mb"`
	UserKnowledgeEnabled              types.Bool    `tfsdk:"user_knowledge_enabled"`
	UserFileMaxUploadSizeMB           types.Int64   `tfsdk:"user_file_max_upload_size_mb"`
	FileTokenCountThresholdK          types.Int64   `tfsdk:"file_token_count_threshold_k"`
	DisableDefaultAssistant           types.Bool    `tfsdk:"disable_default_assistant"`
	CraftDefaultEnabled               types.Bool    `tfsdk:"craft_default_enabled"`
	CraftInstructions                 types.String  `tfsdk:"craft_instructions"`

	// Read-only: license-derived, or (the last three) overwritten from
	// backend env vars on every read.
	ApplicationStatus              types.String `tfsdk:"application_status"`
	Tier                           types.String `tfsdk:"tier"`
	EEFeaturesEnabled              types.Bool   `tfsdk:"ee_features_enabled"`
	GPUEnabled                     types.Bool   `tfsdk:"gpu_enabled"`
	SeatCount                      types.Int64  `tfsdk:"seat_count"`
	UsedSeats                      types.Int64  `tfsdk:"used_seats"`
	HideQueryHistoryFromAdminPanel types.Bool   `tfsdk:"hide_query_history_from_admin_panel"`
	ShowExtraConnectors            types.Bool   `tfsdk:"show_extra_connectors"`
	OpenSearchIndexingEnabled      types.Bool   `tfsdk:"opensearch_indexing_enabled"`
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
				Optional: true,
				MarkdownDescription: "Max user file upload size, in MB. Must be at least 1 — the " +
					"backend treats 0 as unset and substitutes the deployment default.",
				Validators: []validator.Int64{
					int64validator.AtLeast(1),
				},
			},
			"file_token_count_threshold_k": schema.Int64Attribute{
				Optional:            true,
				MarkdownDescription: "File token threshold (thousands) before indexing instead of inlining.",
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
			"hide_query_history_from_admin_panel": schema.BoolAttribute{
				Computed: true,
				MarkdownDescription: "Whether the query history page is hidden in the admin panel. " +
					"Read-only: controlled by the HIDE_QUERY_HISTORY_FROM_ADMIN_PANEL backend env var.",
			},
			"show_extra_connectors": schema.BoolAttribute{
				Computed: true,
				MarkdownDescription: "Whether the extended connector catalog is shown. Read-only: " +
					"controlled by the SHOW_EXTRA_CONNECTORS backend env var.",
			},
			"opensearch_indexing_enabled": schema.BoolAttribute{
				Computed: true,
				MarkdownDescription: "OpenSearch migration flag. Read-only: controlled by the " +
					"ENABLE_OPENSEARCH_INDEXING_FOR_ONYX backend env var.",
			},
		},
	}
}

func (r *settingsResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// patchBodyFromPlan builds the sparse PATCH body: exactly the non-null
// (managed) plan attributes, so unmanaged fields are never touched.
func patchBodyFromPlan(plan settingsResourceModel) map[string]any {
	body := map[string]any{}
	if !plan.MaximumChatRetentionDays.IsNull() {
		body["maximum_chat_retention_days"] = plan.MaximumChatRetentionDays.ValueFloat64()
	}
	if !plan.CompanyName.IsNull() {
		body["company_name"] = plan.CompanyName.ValueString()
	}
	if !plan.CompanyDescription.IsNull() {
		body["company_description"] = plan.CompanyDescription.ValueString()
	}
	if !plan.AnonymousUserEnabled.IsNull() {
		body["anonymous_user_enabled"] = plan.AnonymousUserEnabled.ValueBool()
	}
	if !plan.InviteOnlyEnabled.IsNull() {
		body["invite_only_enabled"] = plan.InviteOnlyEnabled.ValueBool()
	}
	if !plan.DeepResearchEnabled.IsNull() {
		body["deep_research_enabled"] = plan.DeepResearchEnabled.ValueBool()
	}
	if !plan.MultiModelChatEnabled.IsNull() {
		body["multi_model_chat_enabled"] = plan.MultiModelChatEnabled.ValueBool()
	}
	if !plan.SearchUIEnabled.IsNull() {
		body["search_ui_enabled"] = plan.SearchUIEnabled.ValueBool()
	}
	if !plan.AutoDetectSearchFilters.IsNull() {
		body["auto_detect_search_filters"] = plan.AutoDetectSearchFilters.ValueBool()
	}
	if !plan.TemperatureOverrideEnabled.IsNull() {
		body["temperature_override_enabled"] = plan.TemperatureOverrideEnabled.ValueBool()
	}
	if !plan.AutoScroll.IsNull() {
		body["auto_scroll"] = plan.AutoScroll.ValueBool()
	}
	if !plan.QueryHistoryType.IsNull() {
		body["query_history_type"] = plan.QueryHistoryType.ValueString()
	}
	if !plan.ImageExtractionAndAnalysisEnabled.IsNull() {
		body["image_extraction_and_analysis_enabled"] = plan.ImageExtractionAndAnalysisEnabled.ValueBool()
	}
	if !plan.ImageAnalysisMaxSizeMB.IsNull() {
		body["image_analysis_max_size_mb"] = plan.ImageAnalysisMaxSizeMB.ValueInt64()
	}
	if !plan.UserKnowledgeEnabled.IsNull() {
		body["user_knowledge_enabled"] = plan.UserKnowledgeEnabled.ValueBool()
	}
	if !plan.UserFileMaxUploadSizeMB.IsNull() {
		body["user_file_max_upload_size_mb"] = plan.UserFileMaxUploadSizeMB.ValueInt64()
	}
	if !plan.FileTokenCountThresholdK.IsNull() {
		body["file_token_count_threshold_k"] = plan.FileTokenCountThresholdK.ValueInt64()
	}
	if !plan.DisableDefaultAssistant.IsNull() {
		body["disable_default_assistant"] = plan.DisableDefaultAssistant.ValueBool()
	}
	if !plan.CraftDefaultEnabled.IsNull() {
		body["craft_default_enabled"] = plan.CraftDefaultEnabled.ValueBool()
	}
	if !plan.CraftInstructions.IsNull() {
		body["craft_instructions"] = plan.CraftInstructions.ValueString()
	}
	return body
}

// refreshSettingsModel refreshes managed (non-null) attributes for drift
// detection; unmanaged ones stay null, computed ones always refresh.
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
	if !model.DisableDefaultAssistant.IsNull() {
		model.DisableDefaultAssistant = types.BoolPointerValue(server.DisableDefaultAssistant)
	}
	if !model.CraftDefaultEnabled.IsNull() {
		model.CraftDefaultEnabled = types.BoolValue(server.CraftDefaultEnabled)
	}
	if !model.CraftInstructions.IsNull() {
		model.CraftInstructions = types.StringPointerValue(server.CraftInstructions)
	}

	model.ApplicationStatus = types.StringValue(server.ApplicationStatus)
	model.Tier = types.StringValue(server.Tier)
	model.EEFeaturesEnabled = types.BoolValue(server.EEFeaturesEnabled)
	model.GPUEnabled = types.BoolPointerValue(server.GPUEnabled)
	model.SeatCount = types.Int64PointerValue(server.SeatCount)
	model.UsedSeats = types.Int64PointerValue(server.UsedSeats)
	model.HideQueryHistoryFromAdminPanel = types.BoolValue(server.HideQueryHistoryFromAdminPanel)
	model.ShowExtraConnectors = types.BoolPointerValue(server.ShowExtraConnectors)
	model.OpenSearchIndexingEnabled = types.BoolValue(server.OpenSearchIndexingEnabled)
}

// apply PATCHes the managed attributes, then GETs to populate computed
// attributes. patched reports whether the write landed, so callers persist
// state even when only the read-back fails.
func (r *settingsResource) apply(ctx context.Context, plan settingsResourceModel) (settingsResourceModel, bool, error) {
	if body := patchBodyFromPlan(plan); len(body) > 0 {
		if err := r.client.PatchSettings(ctx, body); err != nil {
			return plan, false, err
		}
	}

	plan.ID = types.StringValue(settingsResourceID)
	applied, err := r.client.GetSettings(ctx)
	if err != nil {
		// Computed attributes are unknown in the plan; null them so the
		// partial result is storable. The next Read refreshes them.
		plan.ApplicationStatus = types.StringNull()
		plan.Tier = types.StringNull()
		plan.EEFeaturesEnabled = types.BoolNull()
		plan.GPUEnabled = types.BoolNull()
		plan.SeatCount = types.Int64Null()
		plan.UsedSeats = types.Int64Null()
		plan.HideQueryHistoryFromAdminPanel = types.BoolNull()
		plan.ShowExtraConnectors = types.BoolNull()
		plan.OpenSearchIndexingEnabled = types.BoolNull()
		return plan, true, err
	}
	refreshSettingsModel(&plan, applied)
	return plan, true, nil
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

	state, patched, err := r.apply(ctx, plan)
	if err != nil {
		resp.Diagnostics.AddError("Failed to apply Onyx settings", settingsErrorDetail(err))
		if !patched {
			return
		}
		// The PATCH landed; set state so the change is tracked.
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

	state, patched, err := r.apply(ctx, plan)
	if err != nil {
		resp.Diagnostics.AddError("Failed to apply Onyx settings", settingsErrorDetail(err))
		if !patched {
			return
		}
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
