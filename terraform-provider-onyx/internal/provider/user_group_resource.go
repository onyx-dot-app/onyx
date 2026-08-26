package provider

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"time"

	"github.com/hashicorp/terraform-plugin-framework-timeouts/resource/timeouts"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/booldefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/setdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

const (
	defaultUserGroupUpdateTimeout = 10 * time.Minute
	defaultUserGroupDeleteTimeout = 10 * time.Minute
)

var (
	_ resource.Resource                   = &userGroupResource{}
	_ resource.ResourceWithConfigure      = &userGroupResource{}
	_ resource.ResourceWithImportState    = &userGroupResource{}
	_ resource.ResourceWithValidateConfig = &userGroupResource{}
)

func NewUserGroupResource() resource.Resource {
	return &userGroupResource{}
}

type userGroupResource struct {
	client *client.Client
}

type userGroupResourceModel struct {
	ID               types.String   `tfsdk:"id"`
	Name             types.String   `tfsdk:"name"`
	UserIDs          types.Set      `tfsdk:"user_ids"`
	ManagerIDs       types.Set      `tfsdk:"manager_ids"`
	Permissions      types.Set      `tfsdk:"permissions"`
	IncognitoEnabled types.Bool     `tfsdk:"incognito_enabled"`
	CCPairIDs        types.Set      `tfsdk:"cc_pair_ids"`
	DocumentSetIDs   types.Set      `tfsdk:"document_set_ids"`
	PersonaIDs       types.Set      `tfsdk:"persona_ids"`
	IsDefault        types.Bool     `tfsdk:"is_default"`
	Timeouts         timeouts.Value `tfsdk:"timeouts"`
}

func (r *userGroupResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_user_group"
}

// emptyStringSet is the default for every collection the configuration owns.
// Optional-and-computed with no default would read an unset list as "leave the
// stored one alone", which is not what an absent block means here.
func emptyStringSet() types.Set {
	return types.SetValueMust(types.StringType, nil)
}

func (r *userGroupResource) Schema(ctx context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "A user group: a roster of people, the managers among them, and the " +
			"permissions the group grants. **Enterprise Edition only** — the routes do not exist " +
			"on Community Edition, where every call answers 404.\n\n" +
			"Permissions in Onyx come only from group grants, so this resource is how a person " +
			"gets any authority at all.\n\n" +
			"What the group can *see* is not set here. Connectors, document sets, agents, LLM " +
			"providers, MCP servers and credentials each carry their own `groups` attribute, and " +
			"they own that link. This resource reads those back but never writes them, so the two " +
			"sides cannot fight over the same edge.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				PlanModifiers:       []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
				MarkdownDescription: "Group id, assigned by Onyx.",
			},
			"name": schema.StringAttribute{
				Required: true,
				MarkdownDescription: "Group name, unique across the deployment. Renaming is a " +
					"separate call that Onyx refuses while the group is syncing, so the provider " +
					"waits first.",
			},
			"user_ids": schema.SetAttribute{
				ElementType: types.StringType,
				Optional:    true,
				Computed:    true,
				Default:     setdefault.StaticValue(emptyStringSet()),
				MarkdownDescription: "Member user ids (UUIDs). The configuration owns this list: leaving it out empties the group.\n\n" +
					"Onyx refuses a removal that would leave someone in no group at all, because a " +
					"person with no group has no permissions and would keep a login that can do nothing.",
			},
			"manager_ids": schema.SetAttribute{
				ElementType: types.StringType,
				Optional:    true,
				Computed:    true,
				Default:     setdefault.StaticValue(emptyStringSet()),
				MarkdownDescription: "User ids that manage the group. Every manager must also appear " +
					"in `user_ids` — Onyx stores the flag on the membership row, so a manager is " +
					"always a member.",
			},
			"permissions": schema.SetAttribute{
				ElementType: types.StringType,
				Optional:    true,
				Computed:    true,
				Default:     setdefault.StaticValue(emptyStringSet()),
				MarkdownDescription: "Permission grants, written as Onyx's own tokens: " +
					"`manage:connectors`, `manage:document_sets`, `manage:llms`, `manage:actions`, " +
					"`manage:agents`, `add:agents`, `manage:user_groups`, `manage:bots`, " +
					"`manage:service_account_api_keys`, `create:user_api_keys`, " +
					"`read:agent_analytics`, `read:query_history`. Note these are the wire values, " +
					"not the enum names.\n\n" +
					"The configuration owns the list, so leaving it out revokes every grant the " +
					"group has.\n\n" +
					"Only toggleable permissions may be set. Onyx manages the rest itself " +
					"(`basic`, `admin`, `craft_sandbox`, `manage:skills` and the implied read " +
					"tokens); they are neither read back here nor writable, and naming one is " +
					"refused. Writing this attribute needs full admin access, so the provider only " +
					"calls the endpoint when the set actually changes.",
			},
			"incognito_enabled": schema.BoolAttribute{
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(false),
				MarkdownDescription: "Whether members may start incognito chats. Only takes effect " +
					"while the deployment restricts incognito access to groups, but it is always " +
					"storable so a roster can be staged before the mode is flipped. Writing it needs " +
					"full admin access, so the provider only calls the endpoint when it changes.",
			},
			"cc_pair_ids": schema.SetAttribute{
				ElementType: types.StringType,
				Computed:    true,
				MarkdownDescription: "Connector-credential pairs shared with this group. Read-only " +
					"here: `onyx_cc_pair` owns the link through its own `groups` attribute.",
			},
			"document_set_ids": schema.SetAttribute{
				ElementType: types.StringType,
				Computed:    true,
				MarkdownDescription: "Document sets shared with this group. Read-only here: " +
					"`onyx_document_set` owns the link.",
			},
			"persona_ids": schema.SetAttribute{
				ElementType: types.StringType,
				Computed:    true,
				MarkdownDescription: "Agents shared with this group. Read-only here: `onyx_persona` " +
					"owns the link.",
			},
			"is_default": schema.BoolAttribute{
				Computed: true,
				MarkdownDescription: "Whether this is one of the seeded system groups (`Admin`, " +
					"`Basic`). A default group holds members and nothing else: Onyx refuses to " +
					"rename it, delete it, or change its permissions or incognito setting. Importing " +
					"one and managing its roster works; anything else fails at apply time.",
			},
		},
		Blocks: map[string]schema.Block{
			"timeouts": timeouts.Block(ctx, timeouts.Opts{Update: true, Delete: true}),
		},
	}
}

func (r *userGroupResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// ValidateConfig reports at plan time what would otherwise fail mid-apply.
func (r *userGroupResource) ValidateConfig(ctx context.Context, req resource.ValidateConfigRequest, resp *resource.ValidateConfigResponse) {
	var config userGroupResourceModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}

	// Unknown values only resolve during apply, so a set that is still unknown
	// may yet satisfy this.
	if config.ManagerIDs.IsNull() || config.ManagerIDs.IsUnknown() ||
		config.UserIDs.IsNull() || config.UserIDs.IsUnknown() {
		return
	}

	managers, diags := stringSetValues(ctx, config.ManagerIDs)
	resp.Diagnostics.Append(diags...)
	users, diags := stringSetValues(ctx, config.UserIDs)
	resp.Diagnostics.Append(diags...)
	if resp.Diagnostics.HasError() {
		return
	}

	members := make(map[string]bool, len(users))
	for _, user := range users {
		members[user] = true
	}
	for _, manager := range managers {
		if !members[manager] {
			resp.Diagnostics.AddAttributeError(
				path.Root("manager_ids"),
				"Manager is not a member of the group",
				fmt.Sprintf("User %q is listed in manager_ids but not in user_ids. Onyx stores the "+
					"manager flag on the membership row, so a manager must also be a member. Add the "+
					"user to user_ids.", manager),
			)
		}
	}
}

func (r *userGroupResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan userGroupResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	userIDs, diags := stringSetValues(ctx, plan.UserIDs)
	resp.Diagnostics.Append(diags...)
	if resp.Diagnostics.HasError() {
		return
	}

	// Members ride the create body, so the roster is in place before the
	// manager calls below, which need the membership row to exist. Connector
	// links start empty: a new group has nothing shared with it yet.
	group, err := r.client.CreateUserGroup(ctx, client.UserGroupCreate{
		Name:      plan.Name.ValueString(),
		UserIDs:   userIDs,
		CCPairIDs: []int64{},
	})
	if err != nil {
		resp.Diagnostics.AddError("Unable to create user group", err.Error())
		return
	}

	// The id must reach state before any follow-up call, or a failure below
	// would leak the group: Terraform drops a resource whose create returned
	// an error without an id.
	plan.ID = types.StringValue(strconv.FormatInt(group.ID, 10))
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	// None of these three writes pass through the sync gate, so a group left
	// syncing by its own create still accepts them.
	if !r.applyManagers(ctx, group.ID, plan.ManagerIDs, &resp.Diagnostics) {
		return
	}
	if plan.IncognitoEnabled.ValueBool() {
		if _, err := r.client.SetUserGroupIncognito(ctx, group.ID, true); err != nil {
			resp.Diagnostics.AddError("Unable to set incognito access on the user group", err.Error())
			return
		}
	}
	if !r.applyPermissions(ctx, group.ID, plan.Permissions, &resp.Diagnostics) {
		return
	}

	r.readInto(ctx, group.ID, &plan, &resp.Diagnostics, resp.State.RemoveResource)
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *userGroupResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state userGroupResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "user group", &resp.Diagnostics)
	if !ok {
		return
	}

	r.readInto(ctx, id, &state, &resp.Diagnostics, resp.State.RemoveResource)
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, &state)...)
}

func (r *userGroupResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state userGroupResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "user group", &resp.Diagnostics)
	if !ok {
		return
	}
	plan.ID = state.ID

	updateTimeout, timeoutDiags := plan.Timeouts.Update(ctx, defaultUserGroupUpdateTimeout)
	resp.Diagnostics.Append(timeoutDiags...)
	if resp.Diagnostics.HasError() {
		return
	}
	// Bound the whole update, so the two waits below share one budget rather
	// than each getting the full timeout.
	ctx, cancel := context.WithTimeout(ctx, updateTimeout)
	defer cancel()

	// Renaming and changing membership both pass through the sync gate, and
	// each one leaves the group syncing again, so each waits for itself.
	if !plan.Name.Equal(state.Name) {
		if err := r.client.WaitForUserGroupSettled(ctx, id, updateTimeout); err != nil {
			resp.Diagnostics.AddError("Unable to rename the user group", err.Error())
			return
		}
		if _, err := r.client.RenameUserGroup(ctx, id, plan.Name.ValueString()); err != nil {
			resp.Diagnostics.AddError("Unable to rename the user group", err.Error())
			return
		}
	}

	if !plan.UserIDs.Equal(state.UserIDs) {
		userIDs, diags := stringSetValues(ctx, plan.UserIDs)
		resp.Diagnostics.Append(diags...)
		if resp.Diagnostics.HasError() {
			return
		}
		if err := r.client.WaitForUserGroupSettled(ctx, id, updateTimeout); err != nil {
			resp.Diagnostics.AddError("Unable to update the user group roster", err.Error())
			return
		}
		if _, err := r.client.SetUserGroupMembers(ctx, id, userIDs); err != nil {
			resp.Diagnostics.AddError("Unable to update the user group roster", err.Error())
			return
		}
	}

	// Managers are reconciled after the roster, against what the group now
	// holds: a member dropped above takes their manager flag with them, so
	// demoting them here would fail on a membership row that no longer exists.
	if !r.applyManagers(ctx, id, plan.ManagerIDs, &resp.Diagnostics) {
		return
	}

	// Incognito and permissions both need full admin access, which someone who
	// manages a group need not hold. Calling them unconditionally would fail an
	// update that never touched either.
	if !plan.IncognitoEnabled.Equal(state.IncognitoEnabled) {
		if _, err := r.client.SetUserGroupIncognito(ctx, id, plan.IncognitoEnabled.ValueBool()); err != nil {
			resp.Diagnostics.AddError("Unable to set incognito access on the user group", err.Error())
			return
		}
	}
	if !plan.Permissions.Equal(state.Permissions) {
		if !r.applyPermissions(ctx, id, plan.Permissions, &resp.Diagnostics) {
			return
		}
	}

	r.readInto(ctx, id, &plan, &resp.Diagnostics, resp.State.RemoveResource)
	if resp.Diagnostics.HasError() {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *userGroupResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state userGroupResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "user group", &resp.Diagnostics)
	if !ok {
		return
	}

	deleteTimeout, timeoutDiags := state.Timeouts.Delete(ctx, defaultUserGroupDeleteTimeout)
	resp.Diagnostics.Append(timeoutDiags...)
	if resp.Diagnostics.HasError() {
		return
	}
	ctx, cancel := context.WithTimeout(ctx, deleteTimeout)
	defer cancel()

	// The delete passes through the sync gate as well.
	if err := r.client.WaitForUserGroupSettled(ctx, id, deleteTimeout); err != nil {
		resp.Diagnostics.AddError("Unable to delete the user group", err.Error())
		return
	}

	if err := r.client.DeleteUserGroup(ctx, id); err != nil {
		if client.IsNotFound(err) {
			return
		}
		resp.Diagnostics.AddError("Unable to delete the user group", err.Error())
		return
	}

	// The row usually outlives the call: Onyx marks the group for deletion and
	// a background sync removes it. Returning early would let a replacement
	// fail on the name the group still holds.
	if err := r.client.WaitForUserGroupDeleted(ctx, id, deleteTimeout); err != nil {
		resp.Diagnostics.AddError("Unable to delete the user group", err.Error())
	}
}

func (r *userGroupResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}

// applyManagers reconciles the manager flags against what the group currently
// holds, rather than against prior state, so a change made in the admin panel
// is corrected too. Onyx has no bulk form: each promotion or demotion is its
// own call.
func (r *userGroupResource) applyManagers(ctx context.Context, id int64, planned types.Set, diags *diag.Diagnostics) bool {
	desired, valueDiags := stringSetValues(ctx, planned)
	diags.Append(valueDiags...)
	if diags.HasError() {
		return false
	}

	group, found, err := r.client.LookupUserGroup(ctx, id)
	if err != nil {
		diags.AddError("Unable to read the user group", err.Error())
		return false
	}
	if !found {
		diags.AddError(
			"User group disappeared",
			fmt.Sprintf("User group %d was not found while setting its managers.", id),
		)
		return false
	}

	want := make(map[string]bool, len(desired))
	for _, userID := range desired {
		want[userID] = true
	}
	have := make(map[string]bool, len(group.ManagerIDs))
	for _, userID := range group.ManagerIDs {
		have[userID] = true
	}

	for _, userID := range sortedKeys(want) {
		if !have[userID] {
			if err := r.client.SetGroupManager(ctx, id, userID, true); err != nil {
				diags.AddError(
					"Unable to make the user a group manager",
					fmt.Sprintf("User %s: %s", userID, err.Error()),
				)
				return false
			}
		}
	}
	for _, userID := range sortedKeys(have) {
		if !want[userID] {
			if err := r.client.SetGroupManager(ctx, id, userID, false); err != nil {
				diags.AddError(
					"Unable to revoke the group manager",
					fmt.Sprintf("User %s: %s", userID, err.Error()),
				)
				return false
			}
		}
	}
	return true
}

func (r *userGroupResource) applyPermissions(ctx context.Context, id int64, planned types.Set, diags *diag.Diagnostics) bool {
	permissions, valueDiags := stringSetValues(ctx, planned)
	diags.Append(valueDiags...)
	if diags.HasError() {
		return false
	}
	// A new group starts with no toggleable grant, so an empty set on create is
	// already true and the call is skipped. On update the caller has compared
	// against prior state, so reaching here with an empty set means a revoke.
	if len(permissions) == 0 {
		current, err := r.client.GetUserGroupPermissions(ctx, id)
		if err != nil {
			diags.AddError("Unable to read the user group permissions", err.Error())
			return false
		}
		if len(current) == 0 {
			return true
		}
	}
	if _, err := r.client.SetUserGroupPermissions(ctx, id, permissions); err != nil {
		diags.AddError("Unable to set the user group permissions", err.Error())
		return false
	}
	return true
}

// readInto refreshes model from the API. A group that has gone is removed from
// state through remove.
func (r *userGroupResource) readInto(
	ctx context.Context,
	id int64,
	model *userGroupResourceModel,
	diags *diag.Diagnostics,
	remove func(context.Context),
) {
	group, found, err := r.client.LookupUserGroup(ctx, id)
	if err != nil {
		diags.AddError("Unable to read the user group", err.Error())
		return
	}
	if !found {
		remove(ctx)
		return
	}

	permissions, err := r.client.GetUserGroupPermissions(ctx, id)
	if err != nil {
		diags.AddError("Unable to read the user group permissions", err.Error())
		return
	}

	model.ID = types.StringValue(strconv.FormatInt(group.ID, 10))
	model.Name = types.StringValue(group.Name)
	model.IsDefault = types.BoolValue(group.IsDefault)
	model.IncognitoEnabled = types.BoolValue(group.IncognitoEnabled)

	model.UserIDs = stringSetFrom(ctx, group.MemberIDs(), diags)
	model.ManagerIDs = stringSetFrom(ctx, group.ManagerIDs, diags)
	model.Permissions = stringSetFrom(ctx, permissions, diags)
	model.CCPairIDs = stringSetFrom(ctx, int64sAsStrings(group.CCPairIDs()), diags)
	model.DocumentSetIDs = stringSetFrom(ctx, namedRefIDs(group.DocumentSets), diags)
	model.PersonaIDs = stringSetFrom(ctx, namedRefIDs(group.Personas), diags)
}

// stringSetFrom builds a set from values the API returned. A nil slice becomes
// an empty set rather than null, matching the schema defaults.
func stringSetFrom(ctx context.Context, values []string, diags *diag.Diagnostics) types.Set {
	if values == nil {
		values = []string{}
	}
	value, setDiags := types.SetValueFrom(ctx, types.StringType, values)
	diags.Append(setDiags...)
	return value
}

func namedRefIDs(refs []client.UserGroupNamedRef) []string {
	ids := make([]string, 0, len(refs))
	for _, ref := range refs {
		ids = append(ids, strconv.FormatInt(ref.ID, 10))
	}
	return ids
}

func int64sAsStrings(values []int64) []string {
	out := make([]string, 0, len(values))
	for _, value := range values {
		out = append(out, strconv.FormatInt(value, 10))
	}
	return out
}

func sortedKeys(set map[string]bool) []string {
	keys := make([]string, 0, len(set))
	for key := range set {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
