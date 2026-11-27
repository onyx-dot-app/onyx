package provider

import (
	"context"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework-validators/mapvalidator"
	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/boolplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                = (*integrationResource)(nil)
	_ resource.ResourceWithConfigure   = (*integrationResource)(nil)
	_ resource.ResourceWithImportState = (*integrationResource)(nil)
)

// NewIntegrationResource returns the onyx_integration resource.
func NewIntegrationResource() resource.Resource {
	return &integrationResource{}
}

type integrationResource struct {
	client *client.Client
}

type integrationResourceModel struct {
	ID                               types.String `tfsdk:"id"`
	Name                             types.String `tfsdk:"name"`
	Description                      types.String `tfsdk:"description"`
	ServerURL                        types.String `tfsdk:"server_url"`
	Transport                        types.String `tfsdk:"transport"`
	OpenAPIDocument                  types.String `tfsdk:"openapi_document"`
	AuthMode                         types.String `tfsdk:"auth_mode"`
	AuthMethod                       types.String `tfsdk:"auth_method"`
	HeaderTemplate                   types.Map    `tfsdk:"header_template"`
	OrganizationCredentialsWO        types.Map    `tfsdk:"organization_credentials_wo"`
	OrganizationCredentialsWOVersion types.Int64  `tfsdk:"organization_credentials_wo_version"`
	Enabled                          types.Bool   `tfsdk:"enabled"`
	InstallationPolicy               types.String `tfsdk:"installation_policy"`
	Kind                             types.String `tfsdk:"kind"`
}

func (r *integrationResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_integration"
}

// replaceOnShapeChange replaces the integration when the configuration moves
// between an MCP server and an OpenAPI document. Onyx cannot change the shape
// of an existing integration.
func replaceOnShapeChange() planmodifier.String {
	return stringplanmodifier.RequiresReplaceIf(
		func(_ context.Context, req planmodifier.StringRequest, resp *stringplanmodifier.RequiresReplaceIfFuncResponse) {
			resp.RequiresReplace = req.StateValue.IsNull() != req.PlanValue.IsNull()
		},
		"Changing between `server_url` and `openapi_document` replaces the integration.",
		"Changing between `server_url` and `openapi_document` replaces the integration.",
	)
}

func (r *integrationResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "An integration: an MCP server or an HTTP API from an OpenAPI document, " +
			"managed on the Onyx integrations API (`/admin/integrations`). Set exactly one of " +
			"`server_url` and `openapi_document`. This resource replaces `onyx_mcp_server` and " +
			"`onyx_custom_tool`. Needs Onyx v5.1 or later. Import with the numeric integration id.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Numeric integration id.",
				PlanModifiers:       []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"name": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Name that users see.",
				Validators:          []validator.String{stringvalidator.LengthAtLeast(1)},
			},
			"description": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Description that users and the model see.",
			},
			"server_url": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "URL of the MCP server. Conflicts with `openapi_document`. When Onyx " +
					"can sign in at once (`auth_mode = \"none\"`), it calls the server on create and update " +
					"to load its actions, so the server must answer.",
				Validators: []validator.String{
					stringvalidator.ExactlyOneOf(path.MatchRoot("openapi_document")),
				},
				PlanModifiers: []planmodifier.String{replaceOnShapeChange()},
			},
			"transport": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				MarkdownDescription: "MCP transport: `STREAMABLE_HTTP` (the default) or `SSE`. Only with `server_url`.",
				Validators: []validator.String{
					stringvalidator.OneOf("STREAMABLE_HTTP", "SSE"),
					stringvalidator.AlsoRequires(path.MatchRoot("server_url")),
				},
				PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"openapi_document": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "OpenAPI document of the HTTP API, as JSON or YAML text, for example " +
					"`file(\"openapi.yaml\")`. Each operation becomes an action. Onyx does not return the " +
					"document as sent, so the provider keeps the configured text and a refresh does not " +
					"detect changes made outside Terraform.",
				PlanModifiers: []planmodifier.String{replaceOnShapeChange()},
			},
			"auth_mode": schema.StringAttribute{
				Required: true,
				MarkdownDescription: "Who signs in: `none`, `shared` (one connection for the organization) " +
					"or `individual` (each user connects).",
				Validators: []validator.String{stringvalidator.OneOf("none", "shared", "individual")},
			},
			"auth_method": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "How to sign in: `api_key`, `oauth2` or `onyx_login`. Required unless " +
					"`auth_mode` is `none`.",
				Validators: []validator.String{stringvalidator.OneOf("api_key", "oauth2", "onyx_login")},
			},
			"header_template": schema.MapAttribute{
				Optional:    true,
				ElementType: types.StringType,
				MarkdownDescription: "HTTP headers sent on each call. Values can use `{placeholder}` fields, " +
					"for example `{ Authorization = \"Bearer {api_key}\" }`. The connection supplies the " +
					"field values.",
			},
			"organization_credentials_wo": schema.MapAttribute{
				Optional:    true,
				Sensitive:   true,
				WriteOnly:   true,
				ElementType: types.StringType,
				MarkdownDescription: "Values of the `header_template` fields for the organization connection, " +
					"for example `{ api_key = var.api_key }`. Use with `auth_mode = \"shared\"`. Terraform " +
					"sends them on create and stores nothing. Raise `organization_credentials_wo_version` " +
					"to send new values. Needs Terraform 1.11 or later.",
				Validators: []validator.Map{mapvalidator.SizeAtLeast(1)},
			},
			"organization_credentials_wo_version": writeOnlyVersionAttribute("organization_credentials_wo"),
			"enabled": schema.BoolAttribute{
				Optional:            true,
				Computed:            true,
				MarkdownDescription: "When `false`, no user can use the integration. Onyx sets `true` on create.",
				PlanModifiers:       []planmodifier.Bool{boolplanmodifier.UseStateForUnknown()},
			},
			"installation_policy": schema.StringAttribute{
				Optional: true,
				Computed: true,
				MarkdownDescription: "Company install setting: `REQUIRED`, `DEFAULT`, `AVAILABLE` (the " +
					"default) or `NOT_AVAILABLE`. With `NOT_AVAILABLE`, the integration is private: only " +
					"the API key's user and the integration's shares can use it.",
				Validators: []validator.String{
					stringvalidator.OneOf("REQUIRED", "DEFAULT", "AVAILABLE", "NOT_AVAILABLE"),
				},
				PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"kind": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "`mcp` for an MCP server or `api` for an HTTP API.",
				PlanModifiers:       []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
		},
	}
}

func (r *integrationResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

func integrationConfigFromModel(model integrationResourceModel) client.IntegrationConfig {
	if !model.ServerURL.IsNull() {
		return client.IntegrationConfig{
			Shape:     client.IntegrationShapeMCPServer,
			ServerURL: stringPointer(model.ServerURL),
			Transport: stringPointer(model.Transport),
		}
	}
	return client.IntegrationConfig{
		Shape:           client.IntegrationShapeOpenAPI,
		OpenAPIDocument: stringPointer(model.OpenAPIDocument),
	}
}

func stringMapFromModel(ctx context.Context, value types.Map, diags *diag.Diagnostics) map[string]string {
	values := map[string]string{}
	if value.IsNull() || value.IsUnknown() {
		return values
	}
	diags.Append(value.ElementsAs(ctx, &values, false)...)
	return values
}

// applyRemoteIntegration copies the fields Onyx returns into the model. The
// OpenAPI document and the credentials stay as configured.
func applyRemoteIntegration(ctx context.Context, model *integrationResourceModel, remote *client.Integration, diags *diag.Diagnostics) {
	model.ID = types.StringValue(strconv.FormatInt(remote.ID, 10))
	model.Name = types.StringValue(remote.Name)
	model.Description = types.StringPointerValue(remote.Description)
	model.AuthMode = types.StringValue(remote.AuthMode)
	model.AuthMethod = types.StringPointerValue(remote.AuthMethod)
	model.Enabled = types.BoolValue(remote.Enabled)
	model.InstallationPolicy = types.StringValue(remote.InstallationPolicy)
	model.Kind = types.StringValue(remote.Kind)
	if remote.Config.Shape == client.IntegrationShapeMCPServer {
		model.ServerURL = types.StringPointerValue(remote.Config.ServerURL)
		model.Transport = types.StringPointerValue(remote.Config.Transport)
	} else {
		model.Transport = types.StringNull()
	}
	if len(remote.HeaderTemplate) == 0 {
		model.HeaderTemplate = types.MapNull(types.StringType)
		return
	}
	headers, mapDiags := types.MapValueFrom(ctx, types.StringType, remote.HeaderTemplate)
	diags.Append(mapDiags...)
	model.HeaderTemplate = headers
}

// applyFollowUps sends the settings that create and update cannot carry: the
// organization credentials, the switch and the install setting.
func (r *integrationResource) applyFollowUps(
	ctx context.Context,
	id int64,
	plan integrationResourceModel,
	remote *client.Integration,
	credentials map[string]string,
	diags *diag.Diagnostics,
) *client.Integration {
	if len(credentials) > 0 {
		if err := r.client.SaveIntegrationOrganizationConnection(ctx, id, credentials); err != nil {
			diags.AddError("Failed to save the Onyx integration organization credentials", err.Error())
			return nil
		}
	}
	if !plan.Enabled.IsNull() && !plan.Enabled.IsUnknown() && plan.Enabled.ValueBool() != remote.Enabled {
		enabled := plan.Enabled.ValueBool()
		var err error
		remote, err = r.client.UpdateIntegrationEnabled(ctx, id, enabled)
		if err != nil {
			diags.AddError("Failed to set the Onyx integration switch", err.Error())
			return nil
		}
	}
	if !plan.InstallationPolicy.IsNull() && !plan.InstallationPolicy.IsUnknown() &&
		plan.InstallationPolicy.ValueString() != remote.InstallationPolicy {
		if err := r.client.SetIntegrationInstallationPolicy(ctx, id, plan.InstallationPolicy.ValueString()); err != nil {
			diags.AddError("Failed to set the Onyx integration install setting", err.Error())
			return nil
		}
	}
	refreshed, err := r.client.GetIntegration(ctx, id)
	if err != nil {
		diags.AddError("Failed to read Onyx integration", err.Error())
		return nil
	}
	return refreshed
}

func (r *integrationResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan integrationResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	var credentials types.Map
	resp.Diagnostics.Append(req.Config.GetAttribute(ctx, path.Root("organization_credentials_wo"), &credentials)...)
	headers := stringMapFromModel(ctx, plan.HeaderTemplate, &resp.Diagnostics)
	credentialValues := stringMapFromModel(ctx, credentials, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}

	created, err := r.client.CreateIntegration(ctx, client.IntegrationCreate{
		ForOrganization: plan.InstallationPolicy.ValueString() != "NOT_AVAILABLE",
		Name:            plan.Name.ValueString(),
		Description:     stringPointer(plan.Description),
		AuthMode:        plan.AuthMode.ValueString(),
		AuthMethod:      stringPointer(plan.AuthMethod),
		HeaderTemplate:  headers,
		Config:          integrationConfigFromModel(plan),
	})
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx integration", err.Error())
		return
	}
	// Save the id first so a failed follow-up leaves a resource to fix or destroy.
	plan.ID = types.StringValue(strconv.FormatInt(created.ID, 10))
	applyRemoteIntegration(ctx, &plan, created, &resp.Diagnostics)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)

	remote := r.applyFollowUps(ctx, created.ID, plan, created, credentialValues, &resp.Diagnostics)
	if remote == nil {
		return
	}
	applyRemoteIntegration(ctx, &plan, remote, &resp.Diagnostics)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *integrationResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state integrationResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	id, ok := parseID(state.ID, "integration", &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.GetIntegration(ctx, id)
	if client.IsNotFound(err) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx integration", err.Error())
		return
	}
	applyRemoteIntegration(ctx, &state, remote, &resp.Diagnostics)
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *integrationResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state integrationResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	headers := stringMapFromModel(ctx, plan.HeaderTemplate, &resp.Diagnostics)
	var credentialValues map[string]string
	if writeOnlyVersionChanged(plan.OrganizationCredentialsWOVersion, state.OrganizationCredentialsWOVersion) {
		var credentials types.Map
		resp.Diagnostics.Append(req.Config.GetAttribute(ctx, path.Root("organization_credentials_wo"), &credentials)...)
		credentialValues = stringMapFromModel(ctx, credentials, &resp.Diagnostics)
	}
	if resp.Diagnostics.HasError() {
		return
	}
	id, ok := parseID(state.ID, "integration", &resp.Diagnostics)
	if !ok {
		return
	}

	updated, err := r.client.UpdateIntegration(ctx, id, client.IntegrationUpdate{
		Name:           plan.Name.ValueString(),
		Description:    stringPointer(plan.Description),
		AuthMode:       plan.AuthMode.ValueString(),
		AuthMethod:     stringPointer(plan.AuthMethod),
		HeaderTemplate: headers,
		Config:         integrationConfigFromModel(plan),
	})
	if err != nil {
		resp.Diagnostics.AddError("Failed to update Onyx integration", err.Error())
		return
	}
	remote := r.applyFollowUps(ctx, id, plan, updated, credentialValues, &resp.Diagnostics)
	if remote == nil {
		return
	}
	applyRemoteIntegration(ctx, &plan, remote, &resp.Diagnostics)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *integrationResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state integrationResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}
	id, ok := parseID(state.ID, "integration", &resp.Diagnostics)
	if !ok {
		return
	}
	if err := r.client.DeleteIntegration(ctx, id); err != nil && !client.IsNotFound(err) {
		resp.Diagnostics.AddError("Failed to delete Onyx integration", err.Error())
	}
}

func (r *integrationResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
