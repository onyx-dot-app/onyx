package provider

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/hashicorp/terraform-plugin-framework-jsontypes/jsontypes"
	"github.com/hashicorp/terraform-plugin-framework-validators/mapvalidator"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/booldefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                   = (*customToolResource)(nil)
	_ resource.ResourceWithConfigure      = (*customToolResource)(nil)
	_ resource.ResourceWithImportState    = (*customToolResource)(nil)
	_ resource.ResourceWithValidateConfig = (*customToolResource)(nil)
)

// NewCustomToolResource returns the onyx_custom_tool resource.
func NewCustomToolResource() resource.Resource {
	return &customToolResource{}
}

type customToolResource struct {
	client *client.Client
}

type customToolResourceModel struct {
	ID                     types.String         `tfsdk:"id"`
	Name                   types.String         `tfsdk:"name"`
	Description            types.String         `tfsdk:"description"`
	Definition             jsontypes.Normalized `tfsdk:"definition"`
	CustomHeaders          types.Map            `tfsdk:"custom_headers"`
	CustomHeadersWO        types.Map            `tfsdk:"custom_headers_wo"`
	CustomHeadersWOVersion types.Int64          `tfsdk:"custom_headers_wo_version"`
	PassthroughAuth        types.Bool           `tfsdk:"passthrough_auth"`
	OAuthConfigID          types.String         `tfsdk:"oauth_config_id"`
	Enabled                types.Bool           `tfsdk:"enabled"`
	DisplayName            types.String         `tfsdk:"display_name"`
}

func (r *customToolResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_custom_tool"
}

func (r *customToolResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "A custom action: an external HTTP API, described by an OpenAPI schema, that " +
			"assistants can call.\n\n" +
			"Attach one to an assistant through `tool_ids` on `onyx_persona`.\n\n" +
			"~> **Deleting an action detaches it from every agent that uses it**, including agents " +
			"Terraform does not manage. Onyx does not refuse the delete or warn about it.\n\n" +
			"~> **`custom_headers` holds secrets and Onyx returns them in full.** Anyone who can read " +
			"the deployment's actions can read the values, and they are stored in Terraform state in " +
			"clear text. Supply them from a secret store rather than literals.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Numeric action id.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"name": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Action name, shown to admins and to the model.",
			},
			"description": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString(""),
				MarkdownDescription: "What the action does.",
			},
			"definition": schema.StringAttribute{
				Required:   true,
				CustomType: jsontypes.NormalizedType{},
				MarkdownDescription: "The OpenAPI schema describing the API, as JSON. Onyx derives one " +
					"callable method per operation, so every operation needs an `operationId`. " +
					"Use `jsonencode(...)` or `file(...)` to supply it.",
			},
			"custom_headers": schema.MapAttribute{
				Optional:    true,
				ElementType: types.StringType,
				Sensitive:   true,
				MarkdownDescription: "Headers sent with every call the action makes, such as an API key. " +
					"Cannot carry an `Authorization` header while `passthrough_auth` is enabled. Onyx " +
					"returns these values in full, so Terraform refreshes them and reports changes made " +
					"elsewhere." + writeOnlyDescription("custom_headers"),
			},
			"custom_headers_wo": schema.MapAttribute{
				Optional:    true,
				ElementType: types.StringType,
				Sensitive:   true,
				WriteOnly:   true,
				MarkdownDescription: "Headers sent with every call the action makes, held only in " +
					"configuration. Terraform sends them on every apply and stores nothing, so they never " +
					"reach state — and, unlike `custom_headers`, they are not refreshed from Onyx either, " +
					"so a change made elsewhere goes unreported until the next apply overwrites it. Pair " +
					"with `custom_headers_wo_version` to rotate them. Needs Terraform 1.11 or later.",
				Validators: []validator.Map{
					mapvalidator.ConflictsWith(path.MatchRoot("custom_headers")),
				},
			},
			"custom_headers_wo_version": writeOnlyVersionAttribute("custom_headers_wo"),
			"passthrough_auth": schema.BoolAttribute{
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(false),
				MarkdownDescription: "Forward the calling user's Onyx credentials to the API instead of " +
					"using a fixed credential. Use it when the API enforces per-user permissions.",
			},
			"oauth_config_id": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "Id of an OAuth configuration the action authenticates with. " +
					"OAuth configurations are created in the admin panel; Terraform does not manage them yet.",
			},
			"enabled": schema.BoolAttribute{
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(true),
				MarkdownDescription: "Whether assistants may call the action. A disabled action keeps its " +
					"configuration but never runs.",
			},
			"display_name": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Name shown in the chat UI. Onyx derives it from `name`.",
			},
		},
	}
}

func (r *customToolResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// ValidateConfig reports a bad action definition before anything is applied.
//
// The local checks mirror the server's own rejections. The definition is then
// parsed by Onyx itself, which is the only way to learn whether it yields any
// callable method; that endpoint stores nothing. It needs a configured
// provider, so it is skipped during `terraform validate`, where there is no
// client, and the check happens at plan time instead.
func (r *customToolResource) ValidateConfig(ctx context.Context, req resource.ValidateConfigRequest, resp *resource.ValidateConfigResponse) {
	var config customToolResourceModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}

	headerPath := path.Root("custom_headers")
	headerKey, found := authorizationHeaderKey(config.CustomHeaders)
	if !found {
		if writeOnlyKey, writeOnlyFound := authorizationHeaderKey(config.CustomHeadersWO); writeOnlyFound {
			headerKey, found, headerPath = writeOnlyKey, true, path.Root("custom_headers_wo")
		}
	}
	if found && config.PassthroughAuth.ValueBool() {
		resp.Diagnostics.AddAttributeError(
			headerPath,
			"Conflicting authentication settings",
			fmt.Sprintf(
				"passthrough_auth forwards the calling user's credentials, so Onyx rejects the "+
					"fixed %q header set here. Drop the header, or turn passthrough_auth off.",
				headerKey,
			),
		)
	}

	if r.client == nil || config.Definition.IsNull() || config.Definition.IsUnknown() {
		return
	}
	definition, ok := jsonObjectFromNormalized(config.Definition, "definition", &resp.Diagnostics)
	if !ok {
		return
	}
	methods, err := r.client.ValidateCustomToolDefinition(ctx, definition)
	if err != nil {
		resp.Diagnostics.AddAttributeError(
			path.Root("definition"),
			"Onyx rejected the action definition",
			err.Error(),
		)
		return
	}
	if len(methods) == 0 {
		resp.Diagnostics.AddAttributeError(
			path.Root("definition"),
			"Action definition exposes no methods",
			"Onyx parsed the schema but found no operation to call. Every operation needs an "+
				"operationId, and the schema needs at least one.",
		)
	}
}

// authorizationHeaderKey reports whether the headers carry an Authorization
// header, matching the server's case-insensitive check, and returns the key as
// it was written so the diagnostic can quote it.
//
// Only the key decides this, on the server as here, so a header whose value is
// still unknown at plan time is reported like any other.
func authorizationHeaderKey(headers types.Map) (string, bool) {
	if headers.IsNull() || headers.IsUnknown() {
		return "", false
	}
	for key := range headers.Elements() {
		if strings.EqualFold(key, "authorization") {
			return key, true
		}
	}
	return "", false
}

// headersFromModel turns the header map into the list the API takes. The order
// is fixed so a request body does not churn between applies.
func headersFromModel(ctx context.Context, headers types.Map, diags *diag.Diagnostics) ([]client.Header, bool) {
	result := []client.Header{}
	if headers.IsNull() || headers.IsUnknown() {
		return result, true
	}
	var values map[string]string
	diags.Append(headers.ElementsAs(ctx, &values, false)...)
	if diags.HasError() {
		return nil, false
	}
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		result = append(result, client.Header{Key: key, Value: values[key]})
	}
	return result, true
}

// writeFromModel builds the body shared by create and update. Both replace the
// whole action, so every field is always sent.
func (r *customToolResource) writeFromModel(
	ctx context.Context,
	model customToolResourceModel,
	customHeaders types.Map,
	diags *diag.Diagnostics,
) (client.CustomToolWrite, bool) {
	definition, ok := jsonObjectFromNormalized(model.Definition, "definition", diags)
	if !ok {
		return client.CustomToolWrite{}, false
	}
	headers, ok := headersFromModel(ctx, customHeaders, diags)
	if !ok {
		return client.CustomToolWrite{}, false
	}

	var oauthConfigID *int64
	if !model.OAuthConfigID.IsNull() && !model.OAuthConfigID.IsUnknown() {
		parsed, parsedOK := parseID(model.OAuthConfigID, "OAuth config", diags)
		if !parsedOK {
			return client.CustomToolWrite{}, false
		}
		oauthConfigID = &parsed
	}

	return client.CustomToolWrite{
		Name:            model.Name.ValueString(),
		Description:     model.Description.ValueString(),
		Definition:      definition,
		CustomHeaders:   headers,
		PassthroughAuth: model.PassthroughAuth.ValueBool(),
		OAuthConfigID:   oauthConfigID,
	}, true
}

// customToolHeadersWriteOnlyKey records, in private state, that custom_headers
// came from the write-only twin. Read has no configuration to consult and Onyx
// returns header values in full, so without this marker the refresh would write
// the secret into state.
const customToolHeadersWriteOnlyKey = "custom_headers_write_only"

// applyRemoteCustomTool copies the server's view into the model.
//
// Headers are read back from the server like everything else. Onyx returns
// their values in full, so a change made outside Terraform is visible rather
// than silently kept.
func applyRemoteCustomTool(ctx context.Context, model *customToolResourceModel, remote *client.CustomTool, headersAreWriteOnly bool, diags *diag.Diagnostics) bool {
	definition, ok := normalizedFromJSONObject(remote.Definition, "definition", diags)
	if !ok {
		return false
	}
	// Onyx returns header values in full. Refreshing them is what makes an
	// out-of-band change visible, but for a write-only header map it would put
	// the very secret Terraform was told not to keep back into state.
	if !headersAreWriteOnly {
		model.CustomHeaders = headersFromRemote(ctx, model.CustomHeaders, remote, diags)
		if diags.HasError() {
			return false
		}
	}

	model.ID = types.StringValue(strconv.FormatInt(remote.ID, 10))
	model.Name = types.StringValue(remote.Name)
	model.Description = types.StringValue(remote.Description)
	model.Definition = definition
	model.PassthroughAuth = types.BoolValue(remote.PassthroughAuth)
	model.Enabled = types.BoolValue(remote.Enabled)
	model.DisplayName = types.StringValue(remote.DisplayName)
	if remote.OAuthConfigID == nil {
		model.OAuthConfigID = types.StringNull()
	} else {
		model.OAuthConfigID = types.StringValue(strconv.FormatInt(*remote.OAuthConfigID, 10))
	}
	return true
}

// headersFromRemote rebuilds the header map from the server's list. A repeated
// key keeps its last value, which is all a map can hold.
//
// An action with no headers reads back as null only when nothing was
// configured; a configuration that sets an empty map keeps one, so the applied
// result matches the plan.
func headersFromRemote(ctx context.Context, current types.Map, remote *client.CustomTool, diags *diag.Diagnostics) types.Map {
	if len(remote.CustomHeaders) == 0 && current.IsNull() {
		return types.MapNull(types.StringType)
	}
	values := make(map[string]string, len(remote.CustomHeaders))
	for _, header := range remote.CustomHeaders {
		values[header.Key] = header.Value
	}
	value, mapDiags := types.MapValueFrom(ctx, types.StringType, values)
	diags.Append(mapDiags...)
	return value
}

func (r *customToolResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan customToolResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	customHeaders, headersAreWriteOnly := resolveWriteOnlySource(
		ctx, req.Config, path.Root("custom_headers_wo"), plan.CustomHeaders, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(markWriteOnlySource(
		ctx, resp.Private, customToolHeadersWriteOnlyKey, headersAreWriteOnly)...)
	if resp.Diagnostics.HasError() {
		return
	}

	write, ok := r.writeFromModel(ctx, plan, customHeaders, &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.CreateCustomTool(ctx, write)
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx action", err.Error())
		return
	}

	// New actions are enabled. Disabling is a follow-up call, reported after
	// the state is written so a failure never loses track of the action.
	if !plan.Enabled.ValueBool() {
		if err := r.client.SetCustomToolEnabled(ctx, remote.ID, false); err != nil {
			if !applyRemoteCustomTool(ctx, &plan, remote, headersAreWriteOnly, &resp.Diagnostics) {
				return
			}
			resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
			resp.Diagnostics.AddError("Failed to disable the new Onyx action", err.Error())
			return
		}
		remote.Enabled = false
	}

	if !applyRemoteCustomTool(ctx, &plan, remote, headersAreWriteOnly, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *customToolResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state customToolResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "action", &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.GetCustomTool(ctx, id)
	if client.IsNotFound(err) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx action", err.Error())
		return
	}
	// The read endpoint answers for built-in actions too, but every write
	// endpoint refuses them. Catching it here fails an import that named one,
	// rather than recording state that can be neither updated nor destroyed.
	if remote.InCodeToolID != nil {
		resp.Diagnostics.AddError(
			"Not a custom Onyx action",
			fmt.Sprintf(
				"Action %s is the built-in %q, which Onyx does not allow an API client to change. "+
					"Only custom actions can be managed here.",
				state.ID.ValueString(), *remote.InCodeToolID,
			),
		)
		return
	}
	headersAreWriteOnly := writeOnlySourceMarked(
		ctx, req.Private, customToolHeadersWriteOnlyKey, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}
	if !applyRemoteCustomTool(ctx, &state, remote, headersAreWriteOnly, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *customToolResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state customToolResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "action", &resp.Diagnostics)
	if !ok {
		return
	}
	customHeaders, headersAreWriteOnly := resolveWriteOnlySource(
		ctx, req.Config, path.Root("custom_headers_wo"), plan.CustomHeaders, &resp.Diagnostics)
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(markWriteOnlySource(
		ctx, resp.Private, customToolHeadersWriteOnlyKey, headersAreWriteOnly)...)
	if resp.Diagnostics.HasError() {
		return
	}

	write, ok := r.writeFromModel(ctx, plan, customHeaders, &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.UpdateCustomTool(ctx, id, write)
	if err != nil {
		resp.Diagnostics.AddError("Failed to update Onyx action", err.Error())
		return
	}

	// enabled has its own endpoint, so it is only touched when it changes.
	if plan.Enabled.ValueBool() != remote.Enabled {
		if err := r.client.SetCustomToolEnabled(ctx, id, plan.Enabled.ValueBool()); err != nil {
			resp.Diagnostics.AddError("Failed to change whether the Onyx action is enabled", err.Error())
			return
		}
		remote.Enabled = plan.Enabled.ValueBool()
	}

	if !applyRemoteCustomTool(ctx, &plan, remote, headersAreWriteOnly, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *customToolResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state customToolResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "action", &resp.Diagnostics)
	if !ok {
		return
	}

	err := r.client.DeleteCustomTool(ctx, id)
	if client.IsNotFound(err) {
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to delete Onyx action", err.Error())
		return
	}
}

func (r *customToolResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
