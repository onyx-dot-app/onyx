package provider

import (
	"context"

	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ datasource.DataSource              = (*embeddingProvidersDataSource)(nil)
	_ datasource.DataSourceWithConfigure = (*embeddingProvidersDataSource)(nil)
)

// NewEmbeddingProvidersDataSource returns the onyx_embedding_providers data source.
func NewEmbeddingProvidersDataSource() datasource.DataSource {
	return &embeddingProvidersDataSource{}
}

type embeddingProvidersDataSource struct {
	client *client.Client
}

type embeddingProviderSummaryModel struct {
	ProviderType   types.String `tfsdk:"provider_type"`
	APIURL         types.String `tfsdk:"api_url"`
	APIVersion     types.String `tfsdk:"api_version"`
	DeploymentName types.String `tfsdk:"deployment_name"`
}

var embeddingProviderSummaryAttrTypes = map[string]attr.Type{
	"provider_type":   types.StringType,
	"api_url":         types.StringType,
	"api_version":     types.StringType,
	"deployment_name": types.StringType,
}

type embeddingProvidersDataSourceModel struct {
	Providers types.List `tfsdk:"providers"`
}

func (d *embeddingProvidersDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_embedding_providers"
}

func (d *embeddingProvidersDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "All configured cloud embedding providers. api_key is not exposed.",
		Attributes: map[string]schema.Attribute{
			"providers": schema.ListNestedAttribute{
				Computed: true,
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"provider_type":   schema.StringAttribute{Computed: true},
						"api_url":         schema.StringAttribute{Computed: true},
						"api_version":     schema.StringAttribute{Computed: true},
						"deployment_name": schema.StringAttribute{Computed: true},
					},
				},
			},
		},
	}
}

func (d *embeddingProvidersDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	d.client = clientFromDataSourceConfigure(req, resp)
}

func (d *embeddingProvidersDataSource) Read(ctx context.Context, _ datasource.ReadRequest, resp *datasource.ReadResponse) {
	remote, err := d.client.ListEmbeddingProviders(ctx)
	if err != nil {
		resp.Diagnostics.AddError("Failed to list Onyx embedding providers", err.Error())
		return
	}

	summaries := make([]embeddingProviderSummaryModel, 0, len(remote))
	for _, p := range remote {
		summaries = append(summaries, embeddingProviderSummaryModel{
			ProviderType:   types.StringValue(p.ProviderType),
			APIURL:         types.StringPointerValue(p.APIURL),
			APIVersion:     types.StringPointerValue(p.APIVersion),
			DeploymentName: types.StringPointerValue(p.DeploymentName),
		})
	}

	var model embeddingProvidersDataSourceModel
	providers, diags := types.ListValueFrom(ctx, types.ObjectType{AttrTypes: embeddingProviderSummaryAttrTypes}, summaries)
	resp.Diagnostics.Append(diags...)
	model.Providers = providers
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, model)...)
}
