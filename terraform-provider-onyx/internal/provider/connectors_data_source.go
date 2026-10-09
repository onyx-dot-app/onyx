package provider

import (
	"context"
	"sort"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework-jsontypes/jsontypes"
	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ datasource.DataSource              = (*connectorsDataSource)(nil)
	_ datasource.DataSourceWithConfigure = (*connectorsDataSource)(nil)
)

// NewConnectorsDataSource returns the onyx_connectors data source.
func NewConnectorsDataSource() datasource.DataSource {
	return &connectorsDataSource{}
}

type connectorsDataSource struct {
	client *client.Client
}

type connectorSummaryModel struct {
	ID                      types.String         `tfsdk:"id"`
	Name                    types.String         `tfsdk:"name"`
	Source                  types.String         `tfsdk:"source"`
	InputType               types.String         `tfsdk:"input_type"`
	ConnectorSpecificConfig jsontypes.Normalized `tfsdk:"connector_specific_config"`
	RefreshFreq             types.Int64          `tfsdk:"refresh_freq"`
	PruneFreq               types.Int64          `tfsdk:"prune_freq"`
	IndexingStart           types.String         `tfsdk:"indexing_start"`
	CredentialIDs           types.List           `tfsdk:"credential_ids"`
}

var connectorSummaryAttrTypes = map[string]attr.Type{
	"id":                        types.StringType,
	"name":                      types.StringType,
	"source":                    types.StringType,
	"input_type":                types.StringType,
	"connector_specific_config": jsontypes.NormalizedType{},
	"refresh_freq":              types.Int64Type,
	"prune_freq":                types.Int64Type,
	"indexing_start":            types.StringType,
	"credential_ids":            types.ListType{ElemType: types.Int64Type},
}

type connectorsDataSourceModel struct {
	Connectors types.List `tfsdk:"connectors"`
}

func (d *connectorsDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_connectors"
}

func (d *connectorsDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "All configured connectors, including ones created outside Terraform.",
		Attributes: map[string]schema.Attribute{
			"connectors": schema.ListNestedAttribute{
				Computed: true,
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"id":         schema.StringAttribute{Computed: true},
						"name":       schema.StringAttribute{Computed: true},
						"source":     schema.StringAttribute{Computed: true},
						"input_type": schema.StringAttribute{Computed: true},
						"connector_specific_config": schema.StringAttribute{
							Computed:   true,
							CustomType: jsontypes.NormalizedType{},
						},
						"refresh_freq":   schema.Int64Attribute{Computed: true},
						"prune_freq":     schema.Int64Attribute{Computed: true},
						"indexing_start": schema.StringAttribute{Computed: true},
						"credential_ids": schema.ListAttribute{
							Computed:    true,
							ElementType: types.Int64Type,
						},
					},
				},
			},
		},
	}
}

func (d *connectorsDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	d.client = clientFromDataSourceConfigure(req, resp)
}

func (d *connectorsDataSource) Read(ctx context.Context, _ datasource.ReadRequest, resp *datasource.ReadResponse) {
	remote, err := d.client.ListConnectors(ctx)
	if err != nil {
		resp.Diagnostics.AddError("Failed to list Onyx connectors", err.Error())
		return
	}

	// The listing has no ORDER BY, so a stable sort keeps index-based
	// references and plans from churning between reads.
	sort.Slice(remote, func(i, j int) bool { return remote[i].ID < remote[j].ID })

	summaries := make([]connectorSummaryModel, 0, len(remote))
	for _, c := range remote {
		config, ok := normalizedFromJSONObject(c.ConnectorSpecificConfig, "connector_specific_config", &resp.Diagnostics)
		if !ok {
			return
		}
		credentialIDs, diags := types.ListValueFrom(ctx, types.Int64Type, c.CredentialIDs)
		resp.Diagnostics.Append(diags...)
		if diags.HasError() {
			return
		}
		summaries = append(summaries, connectorSummaryModel{
			ID:                      types.StringValue(strconv.FormatInt(c.ID, 10)),
			Name:                    types.StringValue(c.Name),
			Source:                  types.StringValue(c.Source),
			InputType:               types.StringValue(c.InputType),
			ConnectorSpecificConfig: config,
			RefreshFreq:             types.Int64PointerValue(c.RefreshFreq),
			PruneFreq:               types.Int64PointerValue(c.PruneFreq),
			IndexingStart:           types.StringPointerValue(c.IndexingStart),
			CredentialIDs:           credentialIDs,
		})
	}

	var model connectorsDataSourceModel
	connectors, diags := types.ListValueFrom(ctx, types.ObjectType{AttrTypes: connectorSummaryAttrTypes}, summaries)
	resp.Diagnostics.Append(diags...)
	model.Connectors = connectors
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, model)...)
}
