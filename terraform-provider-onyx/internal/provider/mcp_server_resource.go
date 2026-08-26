package provider

import (
	"context"
	"fmt"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/booldefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                   = &mcpServerResource{}
	_ resource.ResourceWithConfigure      = &mcpServerResource{}
	_ resource.ResourceWithImportState    = &mcpServerResource{}
	_ resource.ResourceWithValidateConfig = &mcpServerResource{}
)

func NewMCPServerResource() resource.Resource {
	return &mcpServerResource{}
}

type mcpServerResource struct {
	client *client.Client
}

type mcpServerResourceModel struct {
	ID                  types.String `tfsdk:"id"`
	Name                types.String `tfsdk:"name"`
	Description         types.String `tfsdk:"description"`
	ServerURL           types.String `tfsdk:"server_url"`
	Transport           types.String `tfsdk:"transport"`
	AuthType            types.String `tfsdk:"auth_type"`
	AuthPerformer       types.String `tfsdk:"auth_performer"`
	APIToken            types.String `tfsdk:"api_token"`
	AuthTemplateHeaders types.Map    `tfsdk:"auth_template_headers"`
	AdminCredentials    types.Map    `tfsdk:"admin_credentials"`
	IsPublic            types.Bool   `tfsdk:"is_public"`
	Groups              types.Set    `tfsdk:"groups"`
	Users               types.Set    `tfsdk:"users"`
	AvailableInCraft    types.Bool   `tfsdk:"available_in_craft"`
	Owner               types.String `tfsdk:"owner"`
	Status              types.String `tfsdk:"status"`
	ToolCount           types.Int64  `tfsdk:"tool_count"`
	LastRefreshedAt     types.String `tfsdk:"last_refreshed_at"`
}

func (r *mcpServerResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_mcp_server"
}

func (r *mcpServerResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "An MCP server Onyx connects to, so its tools can be attached to agents.\n\n" +
			"Only servers that need no interactive sign-in can be managed here: `NONE` and " +
			"`API_TOKEN`. An OAuth server is refused while the plan is built, because the flow " +
			"needs a browser round-trip that Terraform cannot perform.\n\n" +
			"Which tools the server exposes is not part of this resource. Onyx learns them by " +
			"calling the server, and both the tool selection and the Craft approval policies are " +
			"rejected for a tool it has never seen.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				PlanModifiers:       []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
				MarkdownDescription: "Server id, assigned by Onyx.",
			},
			"name": schema.StringAttribute{
				Required: true,
				MarkdownDescription: "Display name. Onyx does not require it to be unique, so two " +
					"servers may share a name.",
			},
			"description": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString(""),
				MarkdownDescription: "Free-text description.",
			},
			"server_url": schema.StringAttribute{
				Required: true,
				MarkdownDescription: "URL Onyx calls the server on. Onyx refuses loopback and " +
					"link-local addresses whatever the SSRF protection level, so a server on the " +
					"Onyx host itself cannot be reached by name.",
			},
			"transport": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString("STREAMABLE_HTTP"),
				MarkdownDescription: "`STREAMABLE_HTTP` or the deprecated `SSE`.",
			},
			"auth_type": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString(client.MCPAuthNone),
				MarkdownDescription: "`NONE` or `API_TOKEN`.",
			},
			"auth_performer": schema.StringAttribute{
				Optional: true,
				Computed: true,
				Default:  stringdefault.StaticString(client.MCPPerformerAdmin),
				MarkdownDescription: "Who supplies the credentials: `ADMIN` for one shared token, " +
					"`PER_USER` for a token each user provides.",
			},
			"api_token": schema.StringAttribute{
				Optional:  true,
				Sensitive: true,
				MarkdownDescription: "Shared API token, for `auth_type = \"API_TOKEN\"` with " +
					"`auth_performer = \"ADMIN\"`. Onyx returns it masked, so Terraform never reads " +
					"it back: the configured value is the only record, and an imported server has " +
					"none.",
			},
			"auth_template_headers": schema.MapAttribute{
				Optional:    true,
				Computed:    true,
				Sensitive:   true,
				ElementType: types.StringType,
				MarkdownDescription: "Headers Onyx sends to the server, for " +
					"`auth_performer = \"PER_USER\"`. A `{placeholder}` in a value names a field " +
					"each user fills in. Onyx writes this itself for a shared token, and keeps " +
					"whatever it holds when a request states none, so switching a server from " +
					"per-user to a shared token leaves the per-user headers in place. Recreate " +
					"the server to start over.",
			},
			"admin_credentials": schema.MapAttribute{
				Optional:    true,
				Sensitive:   true,
				ElementType: types.StringType,
				MarkdownDescription: "Values for the `auth_template_headers` placeholders, required " +
					"with `auth_performer = \"PER_USER\"` and rejected otherwise — a shared token " +
					"is set through `api_token`. Onyx stores them against the identity that " +
					"applied, not the server, and returns them masked.",
			},
			"is_public": schema.BoolAttribute{
				Optional:            true,
				Computed:            true,
				Default:             booldefault.StaticBool(true),
				MarkdownDescription: "Whether every user may use the server. When `false`, only `users` and `groups` may.",
			},
			"groups": schema.SetAttribute{
				Optional:    true,
				ElementType: types.Int64Type,
				MarkdownDescription: "User group ids that may use the server when it is not public. " +
					"Onyx refuses the built-in `Admin` group here and asks for a public server " +
					"instead. The configuration owns this list: removing it clears the groups on " +
					"the server, including any added from the admin panel.",
			},
			"users": schema.SetAttribute{
				Optional:    true,
				ElementType: types.StringType,
				MarkdownDescription: "User ids (UUIDs) that may use the server when it is not " +
					"public. The configuration owns this list: removing it clears the users on " +
					"the server, including any added from the admin panel.",
			},
			"available_in_craft": schema.BoolAttribute{
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(false),
				MarkdownDescription: "Whether the Craft agent may use this server. Onyx keeps this on " +
					"a different endpoint from the rest, so setting it costs a second call.",
			},
			"owner": schema.StringAttribute{
				Computed: true,
				MarkdownDescription: "Identity that configured the server. For a Terraform run this is " +
					"the API key's synthetic address, not a real mailbox.",
			},
			"status": schema.StringAttribute{
				Computed: true,
				MarkdownDescription: "Connection state, which Onyx cycles on its own: `CREATED`, " +
					"`AWAITING_AUTH`, `FETCHING_TOOLS`, `CONNECTED` or `DISCONNECTED`.",
			},
			"tool_count": schema.Int64Attribute{
				Computed:            true,
				MarkdownDescription: "How many tools Onyx has discovered on the server.",
			},
			"last_refreshed_at": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "When Onyx last listed the server's tools.",
			},
		},
	}
}

func (r *mcpServerResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// ValidateConfig checks the authentication combinations before an apply starts.
// It runs without a configured client, so every check is local.
func (r *mcpServerResource) ValidateConfig(ctx context.Context, req resource.ValidateConfigRequest, resp *resource.ValidateConfigResponse) {
	var config mcpServerResourceModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}

	// auth_performer is checked before auth_type, because the checks below
	// return while the type is still unknown. A performer Onyx does not
	// recognise is wrong whatever the type resolves to, and leaving it until
	// after those returns let it reach the API and fail the apply instead.
	performerKnown := !config.AuthPerformer.IsUnknown()
	performer := client.MCPPerformerAdmin
	if performerKnown && config.AuthPerformer.ValueString() != "" {
		performer = config.AuthPerformer.ValueString()
	}
	if performerKnown &&
		performer != client.MCPPerformerAdmin &&
		performer != client.MCPPerformerPerUser {
		resp.Diagnostics.AddAttributeError(
			path.Root("auth_performer"),
			"Unknown authentication performer",
			fmt.Sprintf("Expected %q or %q, got %q.",
				client.MCPPerformerAdmin, client.MCPPerformerPerUser, performer),
		)
		return
	}

	if config.AuthType.IsUnknown() {
		return
	}
	// Null when the configuration leaves it out: the schema default applies to
	// the plan, not to the configuration this reads.
	authType := config.AuthType.ValueString()
	if authType == "" {
		authType = client.MCPAuthNone
	}

	if authType == client.MCPAuthOAuth || authType == client.MCPAuthPTOAuth {
		resp.Diagnostics.AddAttributeError(
			path.Root("auth_type"),
			"OAuth MCP servers cannot be managed by Terraform",
			fmt.Sprintf("%q needs a browser sign-in that Terraform cannot perform. Add the server "+
				"in the Onyx admin panel instead, and manage the rest of the deployment here.", authType),
		)
		return
	}
	if authType != client.MCPAuthNone && authType != client.MCPAuthAPIToken {
		resp.Diagnostics.AddAttributeError(
			path.Root("auth_type"),
			"Unknown authentication type",
			fmt.Sprintf("Expected %q or %q, got %q.", client.MCPAuthNone, client.MCPAuthAPIToken, authType),
		)
		return
	}

	// The credential matrix below is decided by the performer, so it can only be
	// checked once that is known.
	if !performerKnown {
		return
	}

	// A value that is still unknown cannot be checked for presence, and the
	// apply would report anything the server rejects anyway.
	tokenSet, tokenKnown := attributeIsSet(config.APIToken)
	credentialsSet, credentialsKnown := attributeIsSet(config.AdminCredentials)
	headersSet, headersKnown := attributeIsSet(config.AuthTemplateHeaders)

	if authType == client.MCPAuthNone {
		for _, unwanted := range []struct {
			name  string
			set   bool
			known bool
		}{
			{"api_token", tokenSet, tokenKnown},
			{"admin_credentials", credentialsSet, credentialsKnown},
			{"auth_template_headers", headersSet, headersKnown},
		} {
			if unwanted.known && unwanted.set {
				resp.Diagnostics.AddAttributeError(
					path.Root(unwanted.name),
					"Credentials set on a server that takes none",
					fmt.Sprintf("`%s` only applies when `auth_type` is %q.", unwanted.name, client.MCPAuthAPIToken),
				)
			}
		}
		return
	}

	if performer == client.MCPPerformerAdmin {
		if tokenKnown && !tokenSet {
			resp.Diagnostics.AddAttributeError(
				path.Root("api_token"),
				"Missing api_token",
				"A server authenticated with a shared API token needs `api_token`.",
			)
		}
		if headersKnown && headersSet {
			resp.Diagnostics.AddAttributeError(
				path.Root("auth_template_headers"),
				"Headers set on a shared-token server",
				"Onyx writes the header template itself for a shared token. Drop "+
					"`auth_template_headers`, or set `auth_performer` to \"PER_USER\" to write your own.",
			)
		}
		if credentialsKnown && credentialsSet {
			resp.Diagnostics.AddAttributeError(
				path.Root("admin_credentials"),
				"admin_credentials set on a shared-token server",
				"A shared token is set through `api_token`, which Onyx stores as the "+
					"credentials itself. Use `admin_credentials` only with "+
					"`auth_performer = \"PER_USER\"`.",
			)
		}
		return
	}

	// PER_USER: the template names the fields, and the applying admin supplies
	// their own values for them.
	if headersKnown && !headersSet {
		resp.Diagnostics.AddAttributeError(
			path.Root("auth_template_headers"),
			"Missing auth_template_headers",
			"A per-user server needs the header template that names the fields each user fills in.",
		)
	}
	if credentialsKnown && !credentialsSet {
		resp.Diagnostics.AddAttributeError(
			path.Root("admin_credentials"),
			"Missing admin_credentials",
			"Onyx requires the applying admin's own values for the template fields.",
		)
	}
	if tokenKnown && tokenSet {
		resp.Diagnostics.AddAttributeError(
			path.Root("api_token"),
			"api_token set on a per-user server",
			"`api_token` is the shared token for `auth_performer = \"ADMIN\"`. Use "+
				"`admin_credentials` for a per-user server.",
		)
	}
}

// attributeIsSet reports whether an optional attribute carries a value, and
// whether that is knowable while the plan is built.
func attributeIsSet(value interface {
	IsNull() bool
	IsUnknown() bool
}) (set bool, known bool) {
	if value.IsUnknown() {
		return false, false
	}
	return !value.IsNull(), true
}

// writeFromModel converts a plan into the upsert body.
//
// The changed flags follow the LLM provider: Terraform state holds the real
// secret, never the masked one Onyx returns, so re-asserting the configured
// value is always safe. Onyx rejects a masked value outright, which is what
// makes that safe rather than merely conventional.
func (r *mcpServerResource) writeFromModel(
	ctx context.Context,
	plan mcpServerResourceModel,
	id *int64,
	diags *diag.Diagnostics,
) (client.MCPServerWrite, bool) {
	write := client.MCPServerWrite{
		ExistingServerID: id,
		Name:             plan.Name.ValueString(),
		Description:      plan.Description.ValueString(),
		ServerURL:        plan.ServerURL.ValueString(),
		AuthType:         plan.AuthType.ValueString(),
		AuthPerformer:    plan.AuthPerformer.ValueString(),
		Transport:        plan.Transport.ValueString(),
		APIToken:         plan.APIToken.ValueStringPointer(),
		APITokenChanged:  !plan.APIToken.IsNull(),
		IsPublic:         plan.IsPublic.ValueBoolPointer(),
	}

	// Only a per-user server states its own template; Onyx writes the shared one
	// itself. The attribute is computed, so on a shared-token server the plan
	// holds whatever Onyx last stored, and echoing that back would put a value
	// Terraform never had in its configuration into the write body.
	//
	// This does not decide what the server ends up with. Onyx preserves the
	// stored template whenever the request omits one, so a server switched from
	// per-user to a shared token keeps the headers it already had either way.
	perUser := plan.AuthPerformer.ValueString() == client.MCPPerformerPerUser
	if perUser && !plan.AuthTemplateHeaders.IsNull() && !plan.AuthTemplateHeaders.IsUnknown() {
		headers := map[string]string{}
		diags.Append(plan.AuthTemplateHeaders.ElementsAs(ctx, &headers, false)...)
		write.AuthTemplate = &client.MCPAuthTemplate{Headers: headers}
	}
	if !plan.AdminCredentials.IsNull() && !plan.AdminCredentials.IsUnknown() {
		credentials := map[string]string{}
		diags.Append(plan.AdminCredentials.ElementsAs(ctx, &credentials, false)...)
		write.AdminCredentials = credentials
		changed := make(map[string]bool, len(credentials))
		for key := range credentials {
			changed[key] = true
		}
		write.AdminCredentialsChanged = changed
	}

	// Onyx reads a missing access list as "leave the stored one alone", but in a
	// configuration a missing list means there is no access list. Send an empty
	// one so the configuration stays authoritative: without this a list removed
	// from the configuration survives on the server and comes back on the next
	// read, disagreeing with the plan that had already dropped it.
	groups := []int64{}
	if !plan.Groups.IsNull() && !plan.Groups.IsUnknown() {
		configured, groupDiags := int64SetValues(ctx, plan.Groups)
		diags.Append(groupDiags...)
		groups = configured
	}
	write.Groups = &groups

	users := []string{}
	if !plan.Users.IsNull() && !plan.Users.IsUnknown() {
		configured, userDiags := stringSetValues(ctx, plan.Users)
		diags.Append(userDiags...)
		users = configured
	}
	write.Users = &users

	if diags.HasError() {
		return client.MCPServerWrite{}, false
	}
	return write, true
}

// applyRemoteMCPServer copies the stored server over the model.
//
// api_token and admin_credentials are skipped on purpose: Onyx returns them
// masked, so the configured value is the only true record and overwriting it
// here would write a row of bullets into state.
func applyRemoteMCPServer(ctx context.Context, model *mcpServerResourceModel, remote *client.MCPServer, diags *diag.Diagnostics) {
	model.ID = types.StringValue(strconv.FormatInt(remote.ID, 10))
	model.Name = types.StringValue(remote.Name)
	model.Description = types.StringValue(stringOrEmpty(remote.Description))
	model.ServerURL = types.StringValue(remote.ServerURL)
	model.Transport = types.StringValue(stringOrEmpty(remote.Transport))
	model.AuthType = types.StringValue(stringOrEmpty(remote.AuthType))
	model.AuthPerformer = types.StringValue(stringOrEmpty(remote.AuthPerformer))
	model.IsPublic = types.BoolValue(remote.IsPublic)
	model.AvailableInCraft = types.BoolValue(remote.AvailableInCraft)
	model.Owner = types.StringValue(remote.Owner)
	model.Status = types.StringValue(remote.Status)
	model.ToolCount = types.Int64Value(remote.ToolCount)

	if remote.LastRefreshedAt == nil {
		model.LastRefreshedAt = types.StringNull()
	} else {
		model.LastRefreshedAt = types.StringValue(*remote.LastRefreshedAt)
	}

	// Only fill the template in when the model holds none, which is the shared
	// one Onyx writes for itself. A header value may be a literal rather than a
	// placeholder, and Onyx masks those on the way out (`lite...-123`), so
	// refreshing over a configured template would store the mask and leave a
	// difference that never settles.
	if model.AuthTemplateHeaders.IsNull() || model.AuthTemplateHeaders.IsUnknown() {
		if remote.AuthTemplate == nil || len(remote.AuthTemplate.Headers) == 0 {
			model.AuthTemplateHeaders = types.MapNull(types.StringType)
		} else {
			headers, headerDiags := types.MapValueFrom(ctx, types.StringType, remote.AuthTemplate.Headers)
			diags.Append(headerDiags...)
			model.AuthTemplateHeaders = headers
		}
	}

	model.Groups = mcpInt64Set(ctx, model.Groups, remote.Groups, diags)
	model.Users = mcpStringSet(ctx, model.Users, remote.Users, diags)
}

// mcpInt64Set refreshes an optional id set, leaving an unset attribute unset
// when the server holds nothing either. Rewriting null as an empty set would
// report a change on every plan.
func mcpInt64Set(ctx context.Context, current types.Set, ids []int64, diags *diag.Diagnostics) types.Set {
	if len(ids) == 0 && current.IsNull() {
		return current
	}
	if ids == nil {
		ids = []int64{}
	}
	value, setDiags := types.SetValueFrom(ctx, types.Int64Type, ids)
	diags.Append(setDiags...)
	return value
}

func mcpStringSet(ctx context.Context, current types.Set, values []string, diags *diag.Diagnostics) types.Set {
	if len(values) == 0 && current.IsNull() {
		return current
	}
	if values == nil {
		values = []string{}
	}
	value, setDiags := types.SetValueFrom(ctx, types.StringType, values)
	diags.Append(setDiags...)
	return value
}

// applyCraftAvailability applies available_in_craft, which the upsert does not
// carry, and reports what ended up stored.
func (r *mcpServerResource) applyCraftAvailability(ctx context.Context, id int64, desired bool, remote *client.MCPServer) error {
	if remote != nil && remote.AvailableInCraft == desired {
		return nil
	}
	updated, err := r.client.PatchMCPServer(ctx, id, client.MCPServerPatch{AvailableInCraft: &desired})
	if err != nil {
		return err
	}
	if remote != nil {
		remote.AvailableInCraft = updated.AvailableInCraft
	}
	return nil
}

func (r *mcpServerResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan mcpServerResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	write, ok := r.writeFromModel(ctx, plan, nil, &resp.Diagnostics)
	if !ok {
		return
	}

	id, err := r.client.UpsertMCPServer(ctx, write)
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx MCP server", err.Error())
		return
	}

	// Everything from here on can fail with the server already created. Record
	// the id first so a failure leaves it tracked rather than orphaned.
	plan.ID = types.StringValue(strconv.FormatInt(id, 10))

	remote, err := r.client.GetMCPServer(ctx, id)
	if err != nil {
		resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
		resp.Diagnostics.AddError("Failed to read the new Onyx MCP server", err.Error())
		return
	}

	craftErr := r.applyCraftAvailability(ctx, id, plan.AvailableInCraft.ValueBool(), remote)

	applyRemoteMCPServer(ctx, &plan, remote, &resp.Diagnostics)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
	if craftErr != nil {
		resp.Diagnostics.AddError("Failed to set Craft availability on the new Onyx MCP server", craftErr.Error())
	}
}

func (r *mcpServerResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state mcpServerResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "MCP server", &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.GetMCPServer(ctx, id)
	if err != nil {
		if client.IsNotFound(err) {
			resp.State.RemoveResource(ctx)
			return
		}
		resp.Diagnostics.AddError("Failed to read Onyx MCP server", err.Error())
		return
	}

	applyRemoteMCPServer(ctx, &state, remote, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *mcpServerResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state mcpServerResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "MCP server", &resp.Diagnostics)
	if !ok {
		return
	}

	write, ok := r.writeFromModel(ctx, plan, &id, &resp.Diagnostics)
	if !ok {
		return
	}

	if _, err := r.client.UpsertMCPServer(ctx, write); err != nil {
		resp.Diagnostics.AddError("Failed to update Onyx MCP server", err.Error())
		return
	}

	remote, err := r.client.GetMCPServer(ctx, id)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read the updated Onyx MCP server", err.Error())
		return
	}

	craftErr := r.applyCraftAvailability(ctx, id, plan.AvailableInCraft.ValueBool(), remote)

	applyRemoteMCPServer(ctx, &plan, remote, &resp.Diagnostics)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
	if craftErr != nil {
		resp.Diagnostics.AddError("Failed to set Craft availability on the Onyx MCP server", craftErr.Error())
	}
}

func (r *mcpServerResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state mcpServerResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "MCP server", &resp.Diagnostics)
	if !ok {
		return
	}

	// The delete is real, and a server already gone answers 404 like any other
	// missing id, so there is no tombstone to check for.
	if err := r.client.DeleteMCPServer(ctx, id); err != nil && !client.IsNotFound(err) {
		resp.Diagnostics.AddError("Failed to delete Onyx MCP server", err.Error())
	}
}

func (r *mcpServerResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
