package provider

import (
	"context"
	"fmt"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ datasource.DataSource              = (*llmProvidersDataSource)(nil)
	_ datasource.DataSourceWithConfigure = (*llmProvidersDataSource)(nil)
)

// NewLLMProvidersDataSource returns the onyx_llm_providers data source.
func NewLLMProvidersDataSource() datasource.DataSource {
	return &llmProvidersDataSource{}
}

type llmProvidersDataSource struct {
	client *client.Client
}

type llmProviderSummaryModel struct {
	ID             types.String `tfsdk:"id"`
	Name           types.String `tfsdk:"name"`
	ProviderType   types.String `tfsdk:"provider_type"`
	APIBase        types.String `tfsdk:"api_base"`
	APIVersion     types.String `tfsdk:"api_version"`
	DeploymentName types.String `tfsdk:"deployment_name"`
	IsPublic       types.Bool   `tfsdk:"is_public"`
	IsAutoMode     types.Bool   `tfsdk:"is_auto_mode"`
	ModelNames     types.Set    `tfsdk:"model_names"`
}

var llmProviderSummaryAttrTypes = map[string]attr.Type{
	"id":              types.StringType,
	"name":            types.StringType,
	"provider_type":   types.StringType,
	"api_base":        types.StringType,
	"api_version":     types.StringType,
	"deployment_name": types.StringType,
	"is_public":       types.BoolType,
	"is_auto_mode":    types.BoolType,
	"model_names":     types.SetType{ElemType: types.StringType},
}

var defaultModelAttrTypes = map[string]attr.Type{
	"provider_id": types.StringType,
	"model_name":  types.StringType,
}

type llmProvidersDataSourceModel struct {
	Providers     types.List   `tfsdk:"providers"`
	DefaultText   types.Object `tfsdk:"default_text"`
	DefaultVision types.Object `tfsdk:"default_vision"`
}

func (d *llmProvidersDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_llm_providers"
}

func (d *llmProvidersDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	defaultModelAttribute := func(kind string) schema.SingleNestedAttribute {
		return schema.SingleNestedAttribute{
			Computed:            true,
			MarkdownDescription: fmt.Sprintf("The deployment default %s model, or null if unset.", kind),
			Attributes: map[string]schema.Attribute{
				"provider_id": schema.StringAttribute{Computed: true},
				"model_name":  schema.StringAttribute{Computed: true},
			},
		}
	}

	resp.Schema = schema.Schema{
		MarkdownDescription: "All configured LLM providers plus the deployment default models. " +
			"Secret fields (api_key, custom_config) are not exposed.",
		Attributes: map[string]schema.Attribute{
			"providers": schema.ListNestedAttribute{
				Computed: true,
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"id":              schema.StringAttribute{Computed: true},
						"name":            schema.StringAttribute{Computed: true},
						"provider_type":   schema.StringAttribute{Computed: true},
						"api_base":        schema.StringAttribute{Computed: true},
						"api_version":     schema.StringAttribute{Computed: true},
						"deployment_name": schema.StringAttribute{Computed: true},
						"is_public":       schema.BoolAttribute{Computed: true},
						"is_auto_mode":    schema.BoolAttribute{Computed: true},
						"model_names": schema.SetAttribute{
							ElementType: types.StringType,
							Computed:    true,
						},
					},
				},
			},
			"default_text":   defaultModelAttribute("text"),
			"default_vision": defaultModelAttribute("vision"),
		},
	}
}

func (d *llmProvidersDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	d.client = clientFromDataSourceConfigure(req, resp)
}

func defaultModelObject(dm *client.DefaultModel, diags *diag.Diagnostics) types.Object {
	if dm == nil {
		return types.ObjectNull(defaultModelAttrTypes)
	}
	obj, objDiags := types.ObjectValue(defaultModelAttrTypes, map[string]attr.Value{
		"provider_id": types.StringValue(strconv.FormatInt(dm.ProviderID, 10)),
		"model_name":  types.StringValue(dm.ModelName),
	})
	diags.Append(objDiags...)
	return obj
}

func (d *llmProvidersDataSource) Read(ctx context.Context, _ datasource.ReadRequest, resp *datasource.ReadResponse) {
	list, err := d.client.ListLLMProviders(ctx)
	if err != nil {
		resp.Diagnostics.AddError("Failed to list Onyx LLM providers", err.Error())
		return
	}

	summaries := make([]llmProviderSummaryModel, 0, len(list.Providers))
	for _, p := range list.Providers {
		names := make([]string, 0, len(p.ModelConfigurations))
		for _, mc := range p.ModelConfigurations {
			names = append(names, mc.Name)
		}
		nameSet, diags := types.SetValueFrom(ctx, types.StringType, names)
		resp.Diagnostics.Append(diags...)

		summaries = append(summaries, llmProviderSummaryModel{
			ID:             types.StringValue(strconv.FormatInt(p.ID, 10)),
			Name:           types.StringPointerValue(p.Name),
			ProviderType:   types.StringValue(p.Provider),
			APIBase:        types.StringPointerValue(p.APIBase),
			APIVersion:     types.StringPointerValue(p.APIVersion),
			DeploymentName: types.StringPointerValue(p.DeploymentName),
			IsPublic:       types.BoolValue(p.IsPublic),
			IsAutoMode:     types.BoolValue(p.IsAutoMode),
			ModelNames:     nameSet,
		})
	}

	var model llmProvidersDataSourceModel
	providers, diags := types.ListValueFrom(ctx, types.ObjectType{AttrTypes: llmProviderSummaryAttrTypes}, summaries)
	resp.Diagnostics.Append(diags...)
	model.Providers = providers
	model.DefaultText = defaultModelObject(list.DefaultText, &resp.Diagnostics)
	model.DefaultVision = defaultModelObject(list.DefaultVision, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, model)...)
}
