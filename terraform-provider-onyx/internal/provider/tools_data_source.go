package provider

import (
	"context"
	"sort"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ datasource.DataSource              = (*toolsDataSource)(nil)
	_ datasource.DataSourceWithConfigure = (*toolsDataSource)(nil)
)

// NewToolsDataSource returns the onyx_tools data source.
func NewToolsDataSource() datasource.DataSource {
	return &toolsDataSource{}
}

type toolsDataSource struct {
	client *client.Client
}

type toolSummaryModel struct {
	ID           types.String `tfsdk:"id"`
	Name         types.String `tfsdk:"name"`
	DisplayName  types.String `tfsdk:"display_name"`
	Description  types.String `tfsdk:"description"`
	InCodeToolID types.String `tfsdk:"in_code_tool_id"`
	MCPServerID  types.String `tfsdk:"mcp_server_id"`
	Enabled      types.Bool   `tfsdk:"enabled"`
}

var toolSummaryAttrTypes = map[string]attr.Type{
	"id":              types.StringType,
	"name":            types.StringType,
	"display_name":    types.StringType,
	"description":     types.StringType,
	"in_code_tool_id": types.StringType,
	"mcp_server_id":   types.StringType,
	"enabled":         types.BoolType,
}

type toolsDataSourceModel struct {
	Tools types.List `tfsdk:"tools"`
}

func (d *toolsDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_tools"
}

func (d *toolsDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "The actions an agent can use now: enabled custom actions, built-in " +
			"actions that are available on this deployment, and tools of connected MCP servers. " +
			"Disabled actions, unavailable built-in actions and tools of disconnected MCP servers " +
			"are left out. Use it to find the ids of built-in actions for `onyx_agent.tool_ids`, " +
			"because Terraform cannot create those. Custom headers are not exposed.",
		Attributes: map[string]schema.Attribute{
			"tools": schema.ListNestedAttribute{
				Computed:            true,
				MarkdownDescription: "The actions, sorted by id.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"id": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "Numeric action id.",
						},
						"name": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "Action name.",
						},
						"display_name": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "Name shown to users.",
						},
						"description": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "Action description.",
						},
						"in_code_tool_id": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "Built-in action identifier, such as `SearchTool` or `WebSearchTool`. Null for custom and MCP actions.",
						},
						"mcp_server_id": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "Id of the MCP server that provides the tool. Null for other actions.",
						},
						"enabled": schema.BoolAttribute{
							Computed:            true,
							MarkdownDescription: "Whether the action is turned on.",
						},
					},
				},
			},
		},
	}
}

func (d *toolsDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	d.client = clientFromDataSourceConfigure(req, resp)
}

func (d *toolsDataSource) Read(ctx context.Context, _ datasource.ReadRequest, resp *datasource.ReadResponse) {
	remote, err := d.client.ListTools(ctx)
	if err != nil {
		resp.Diagnostics.AddError("Failed to list Onyx actions", err.Error())
		return
	}

	sort.Slice(remote, func(i, j int) bool { return remote[i].ID < remote[j].ID })

	summaries := make([]toolSummaryModel, 0, len(remote))
	for _, t := range remote {
		mcpServerID := types.StringNull()
		if t.MCPServerID != nil {
			mcpServerID = types.StringValue(strconv.FormatInt(*t.MCPServerID, 10))
		}
		summaries = append(summaries, toolSummaryModel{
			ID:           types.StringValue(strconv.FormatInt(t.ID, 10)),
			Name:         types.StringValue(t.Name),
			DisplayName:  types.StringValue(t.DisplayName),
			Description:  types.StringValue(t.Description),
			InCodeToolID: types.StringPointerValue(t.InCodeToolID),
			MCPServerID:  mcpServerID,
			Enabled:      types.BoolValue(t.Enabled),
		})
	}

	var model toolsDataSourceModel
	tools, diags := types.ListValueFrom(ctx, types.ObjectType{AttrTypes: toolSummaryAttrTypes}, summaries)
	resp.Diagnostics.Append(diags...)
	model.Tools = tools
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, model)...)
}
