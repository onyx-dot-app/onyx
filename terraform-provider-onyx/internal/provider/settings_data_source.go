package provider

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ datasource.DataSource              = (*settingsDataSource)(nil)
	_ datasource.DataSourceWithConfigure = (*settingsDataSource)(nil)
)

// NewSettingsDataSource returns the onyx_settings data source.
func NewSettingsDataSource() datasource.DataSource {
	return &settingsDataSource{}
}

type settingsDataSource struct {
	client *client.Client
}

// settingsDataSourceModel mirrors the full Settings object, read-only.
type settingsDataSourceModel struct {
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
	ApplicationStatus                 types.String  `tfsdk:"application_status"`
	Tier                              types.String  `tfsdk:"tier"`
	EEFeaturesEnabled                 types.Bool    `tfsdk:"ee_features_enabled"`
	GPUEnabled                        types.Bool    `tfsdk:"gpu_enabled"`
	SeatCount                         types.Int64   `tfsdk:"seat_count"`
	UsedSeats                         types.Int64   `tfsdk:"used_seats"`
}

func (d *settingsDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_settings"
}

func (d *settingsDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	attrs := map[string]schema.Attribute{
		"maximum_chat_retention_days":           schema.Float64Attribute{Computed: true},
		"company_name":                          schema.StringAttribute{Computed: true},
		"company_description":                   schema.StringAttribute{Computed: true},
		"anonymous_user_enabled":                schema.BoolAttribute{Computed: true},
		"invite_only_enabled":                   schema.BoolAttribute{Computed: true},
		"deep_research_enabled":                 schema.BoolAttribute{Computed: true},
		"multi_model_chat_enabled":              schema.BoolAttribute{Computed: true},
		"search_ui_enabled":                     schema.BoolAttribute{Computed: true},
		"auto_detect_search_filters":            schema.BoolAttribute{Computed: true},
		"temperature_override_enabled":          schema.BoolAttribute{Computed: true},
		"auto_scroll":                           schema.BoolAttribute{Computed: true},
		"query_history_type":                    schema.StringAttribute{Computed: true},
		"hide_query_history_from_admin_panel":   schema.BoolAttribute{Computed: true},
		"image_extraction_and_analysis_enabled": schema.BoolAttribute{Computed: true},
		"image_analysis_max_size_mb":            schema.Int64Attribute{Computed: true},
		"user_knowledge_enabled":                schema.BoolAttribute{Computed: true},
		"user_file_max_upload_size_mb":          schema.Int64Attribute{Computed: true},
		"file_token_count_threshold_k":          schema.Int64Attribute{Computed: true},
		"show_extra_connectors":                 schema.BoolAttribute{Computed: true},
		"disable_default_assistant":             schema.BoolAttribute{Computed: true},
		"craft_default_enabled":                 schema.BoolAttribute{Computed: true},
		"craft_instructions":                    schema.StringAttribute{Computed: true},
		"opensearch_indexing_enabled":           schema.BoolAttribute{Computed: true},
		"application_status":                    schema.StringAttribute{Computed: true},
		"tier":                                  schema.StringAttribute{Computed: true},
		"ee_features_enabled":                   schema.BoolAttribute{Computed: true},
		"gpu_enabled":                           schema.BoolAttribute{Computed: true},
		"seat_count":                            schema.Int64Attribute{Computed: true},
		"used_seats":                            schema.Int64Attribute{Computed: true},
	}
	resp.Schema = schema.Schema{
		MarkdownDescription: "The current Onyx workspace settings, read-only. Useful for referencing " +
			"settings (e.g. the license `tier`) without managing them.",
		Attributes: attrs,
	}
}

func (d *settingsDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	d.client = clientFromDataSourceConfigure(req, resp)
}

func (d *settingsDataSource) Read(ctx context.Context, _ datasource.ReadRequest, resp *datasource.ReadResponse) {
	server, err := d.client.GetSettings(ctx)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx settings", err.Error())
		return
	}

	model := settingsDataSourceModel{
		MaximumChatRetentionDays:          types.Float64PointerValue(server.MaximumChatRetentionDays),
		CompanyName:                       types.StringPointerValue(server.CompanyName),
		CompanyDescription:                types.StringPointerValue(server.CompanyDescription),
		AnonymousUserEnabled:              types.BoolPointerValue(server.AnonymousUserEnabled),
		InviteOnlyEnabled:                 types.BoolValue(server.InviteOnlyEnabled),
		DeepResearchEnabled:               types.BoolPointerValue(server.DeepResearchEnabled),
		MultiModelChatEnabled:             types.BoolPointerValue(server.MultiModelChatEnabled),
		SearchUIEnabled:                   types.BoolPointerValue(server.SearchUIEnabled),
		AutoDetectSearchFilters:           types.BoolPointerValue(server.AutoDetectSearchFilters),
		TemperatureOverrideEnabled:        types.BoolPointerValue(server.TemperatureOverrideEnabled),
		AutoScroll:                        types.BoolPointerValue(server.AutoScroll),
		QueryHistoryType:                  types.StringPointerValue(server.QueryHistoryType),
		HideQueryHistoryFromAdminPanel:    types.BoolValue(server.HideQueryHistoryFromAdminPanel),
		ImageExtractionAndAnalysisEnabled: types.BoolPointerValue(server.ImageExtractionAndAnalysisEnabled),
		ImageAnalysisMaxSizeMB:            types.Int64PointerValue(server.ImageAnalysisMaxSizeMB),
		UserKnowledgeEnabled:              types.BoolPointerValue(server.UserKnowledgeEnabled),
		UserFileMaxUploadSizeMB:           types.Int64PointerValue(server.UserFileMaxUploadSizeMB),
		FileTokenCountThresholdK:          types.Int64PointerValue(server.FileTokenCountThresholdK),
		ShowExtraConnectors:               types.BoolPointerValue(server.ShowExtraConnectors),
		DisableDefaultAssistant:           types.BoolPointerValue(server.DisableDefaultAssistant),
		CraftDefaultEnabled:               types.BoolValue(server.CraftDefaultEnabled),
		CraftInstructions:                 types.StringPointerValue(server.CraftInstructions),
		OpenSearchIndexingEnabled:         types.BoolValue(server.OpenSearchIndexingEnabled),
		ApplicationStatus:                 types.StringValue(server.ApplicationStatus),
		Tier:                              types.StringValue(server.Tier),
		EEFeaturesEnabled:                 types.BoolValue(server.EEFeaturesEnabled),
		GPUEnabled:                        types.BoolPointerValue(server.GPUEnabled),
		SeatCount:                         types.Int64PointerValue(server.SeatCount),
		UsedSeats:                         types.Int64PointerValue(server.UsedSeats),
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, model)...)
}
