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
	_ datasource.DataSource              = (*userGroupsDataSource)(nil)
	_ datasource.DataSourceWithConfigure = (*userGroupsDataSource)(nil)
)

// NewUserGroupsDataSource returns the onyx_user_groups data source.
func NewUserGroupsDataSource() datasource.DataSource {
	return &userGroupsDataSource{}
}

type userGroupsDataSource struct {
	client *client.Client
}

type userGroupSummaryModel struct {
	ID         types.String `tfsdk:"id"`
	Name       types.String `tfsdk:"name"`
	IsDefault  types.Bool   `tfsdk:"is_default"`
	IsUpToDate types.Bool   `tfsdk:"is_up_to_date"`
}

var userGroupSummaryAttrTypes = map[string]attr.Type{
	"id":            types.StringType,
	"name":          types.StringType,
	"is_default":    types.BoolType,
	"is_up_to_date": types.BoolType,
}

type userGroupsDataSourceModel struct {
	Groups types.List `tfsdk:"groups"`
}

func (d *userGroupsDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_user_groups"
}

func (d *userGroupsDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "The user groups the caller can see, including the seeded `Admin` and " +
			"`Basic` groups that `onyx_user_group` cannot create. A key with global group read " +
			"access sees every group; a scoped group manager sees only the groups it manages. Use " +
			"it to reference a group by name. Enterprise Edition only.",
		Attributes: map[string]schema.Attribute{
			"groups": schema.ListNestedAttribute{
				Computed:            true,
				MarkdownDescription: "The groups, sorted by id.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"id": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "Numeric group id.",
						},
						"name": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "Group name.",
						},
						"is_default": schema.BoolAttribute{
							Computed:            true,
							MarkdownDescription: "Whether Onyx seeded the group (`Admin`, `Basic`).",
						},
						"is_up_to_date": schema.BoolAttribute{
							Computed:            true,
							MarkdownDescription: "False while Onyx syncs the group's access to the search index.",
						},
					},
				},
			},
		},
	}
}

func (d *userGroupsDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	d.client = clientFromDataSourceConfigure(req, resp)
}

func (d *userGroupsDataSource) Read(ctx context.Context, _ datasource.ReadRequest, resp *datasource.ReadResponse) {
	remote, err := d.client.ListUserGroups(ctx)
	if err != nil {
		resp.Diagnostics.AddError("Failed to list Onyx user groups", err.Error())
		return
	}

	sort.Slice(remote, func(i, j int) bool { return remote[i].ID < remote[j].ID })

	summaries := make([]userGroupSummaryModel, 0, len(remote))
	for _, g := range remote {
		summaries = append(summaries, userGroupSummaryModel{
			ID:         types.StringValue(strconv.FormatInt(g.ID, 10)),
			Name:       types.StringValue(g.Name),
			IsDefault:  types.BoolValue(g.IsDefault),
			IsUpToDate: types.BoolValue(g.IsUpToDate),
		})
	}

	var model userGroupsDataSourceModel
	groups, diags := types.ListValueFrom(ctx, types.ObjectType{AttrTypes: userGroupSummaryAttrTypes}, summaries)
	resp.Diagnostics.Append(diags...)
	model.Groups = groups
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, model)...)
}
