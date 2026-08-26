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
// Optional-and-computed with no default leaves an unset list unknown and makes
// the resource invent a meaning for it. An explicit empty default says plainly
// that an absent list means an empty one.
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

	// Unknown values only resolve during apply, so anything still unknown may
	// yet satisfy this. That covers a single unknown id inside an otherwise
	// known list as well: reading one out fails the plan outright, which would
	// turn a perfectly good configuration into an error.
	if config.ManagerIDs.IsNull() || config.UserIDs.IsNull() ||
		setIsNotFullyKnown(config.ManagerIDs) || setIsNotFullyKnown(config.UserIDs) {
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

// setIsNotFullyKnown reports whether the set, or any id in it, is still
// unknown.
func setIsNotFullyKnown(set types.Set) bool {
	if set.IsUnknown() {
		return true
	}
	for _, element := range set.Elements() {
		if element.IsUnknown() {
			return true
		}
	}
	return false
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

	plan.ID = types.StringValue(strconv.FormatInt(group.ID, 10))

	// None of these three writes pass through the sync gate, so a group left
	// syncing by its own create still accepts them.
	//
	// A failure is collected rather than returned. The group exists now, so it
	// has to reach state or it is leaked, and returning here would leave the
	// computed attributes below unknown — which Terraform reports as four
	// provider bugs that bury the real reason the apply failed.
	followUps := diag.Diagnostics{}
	if r.applyManagers(ctx, group.ID, plan.ManagerIDs, &followUps) {
		if plan.IncognitoEnabled.ValueBool() {
			if _, err := r.client.SetUserGroupIncognito(ctx, group.ID, true); err != nil {
				followUps.AddError("Unable to set incognito access on the user group", err.Error())
			}
		}
		if !followUps.HasError() {
			r.applyPermissions(ctx, group.ID, plan.Permissions, &followUps)
		}
	}

	if r.readInto(ctx, group.ID, &plan, &resp.Diagnostics, resp.State.RemoveResource) {
		plan.ensureComputedKnown()
		resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
	}
	resp.Diagnostics.Append(followUps...)
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

	if !r.readInto(ctx, id, &state, &resp.Diagnostics, resp.State.RemoveResource) {
		return
	}
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

	// Read the roster up front. Converting it mid-way would need an early
	// return on failure, and every return before the refresh below leaves the
	// computed attributes unknown.
	userIDs, diags := stringSetValues(ctx, plan.UserIDs)
	resp.Diagnostics.Append(diags...)
	if resp.Diagnostics.HasError() {
		return
	}

	// Renaming and changing membership both pass through the sync gate, and
	// each one leaves the group syncing again, so each waits for itself.
	//
	// As in Create, a write failure is collected rather than returned: the
	// refresh at the end has to run either way, or the computed attributes stay
	// unknown and Terraform reports provider bugs instead of the real cause.
	writes := diag.Diagnostics{}
	if !plan.Name.Equal(state.Name) {
		if err := r.client.WaitForUserGroupSettled(ctx, id, updateTimeout); err != nil {
			writes.AddError("Unable to rename the user group", err.Error())
		} else if _, err := r.client.RenameUserGroup(ctx, id, plan.Name.ValueString()); err != nil {
			writes.AddError("Unable to rename the user group", err.Error())
		}
	}

	if !writes.HasError() && !plan.UserIDs.Equal(state.UserIDs) {
		if err := r.client.WaitForUserGroupSettled(ctx, id, updateTimeout); err != nil {
			writes.AddError("Unable to update the user group roster", err.Error())
		} else if _, err := r.client.SetUserGroupMembers(ctx, id, userIDs); err != nil {
			writes.AddError("Unable to update the user group roster", err.Error())
		}
	}

	// Managers are reconciled after the roster, against what the group now
	// holds: a member dropped above takes their manager flag with them, so
	// demoting them here would fail on a membership row that no longer exists.
	if !writes.HasError() {
		r.applyManagers(ctx, id, plan.ManagerIDs, &writes)
	}

	// Incognito and permissions both need full admin access, which someone who
	// manages a group need not hold. Calling them unconditionally would fail an
	// update that never touched either.
	if !writes.HasError() && !plan.IncognitoEnabled.Equal(state.IncognitoEnabled) {
		if _, err := r.client.SetUserGroupIncognito(ctx, id, plan.IncognitoEnabled.ValueBool()); err != nil {
			writes.AddError("Unable to set incognito access on the user group", err.Error())
		}
	}
	if !writes.HasError() && !plan.Permissions.Equal(state.Permissions) {
		r.applyPermissions(ctx, id, plan.Permissions, &writes)
	}

	if r.readInto(ctx, id, &plan, &resp.Diagnostics, resp.State.RemoveResource) {
		plan.ensureComputedKnown()
		resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
	}
	resp.Diagnostics.Append(writes...)
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

	alreadyGone, err := r.deleteUserGroup(ctx, id, deleteTimeout)
	if err != nil {
		resp.Diagnostics.AddError("Unable to delete the user group", err.Error())
		return
	}
	if alreadyGone {
		return
	}

	// The row usually outlives the call: Onyx marks the group for deletion and
	// a background sync removes it. Returning early would let a replacement
	// fail on the name the group still holds.
	if err := r.client.WaitForUserGroupDeleted(ctx, id, deleteTimeout); err != nil {
		resp.Diagnostics.AddError("Unable to delete the user group", err.Error())
	}
}

// deleteUserGroup asks Onyx to delete the group and reports whether it had
// already gone.
//
// The delete passes through the sync gate, and the route funnels every
// ValueError into not-found — the gate's "currently syncing" included. So a 404
// here does not prove the group has gone, and trusting one would drop a live
// group out of state and leave the next apply failing on the name it still
// holds. Each 404 is confirmed against the listing, and a group that turns out
// to be syncing is waited on and deleted once more.
func (r *userGroupResource) deleteUserGroup(ctx context.Context, id int64, timeout time.Duration) (alreadyGone bool, err error) {
	for attempt := 0; attempt < 2; attempt++ {
		if err := r.client.WaitForUserGroupSettled(ctx, id, timeout); err != nil {
			return false, err
		}

		err := r.client.DeleteUserGroup(ctx, id)
		if err == nil {
			return false, nil
		}
		if !client.IsNotFound(err) {
			return false, err
		}

		_, found, lookupErr := r.client.LookupUserGroup(ctx, id)
		if lookupErr != nil {
			return false, lookupErr
		}
		if !found {
			return true, nil
		}
	}
	return false, fmt.Errorf(
		"user group %d is still listed after Onyx answered not found, which is what a group "+
			"reports while it is syncing — it started syncing again between the check and the "+
			"delete, so re-run the destroy", id)
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

// readInto refreshes model from the API. A group that has gone is dropped from
// state through remove, and the false return says so: writing the model back
// afterwards would put the resource straight back into state.
func (r *userGroupResource) readInto(
	ctx context.Context,
	id int64,
	model *userGroupResourceModel,
	diags *diag.Diagnostics,
	remove func(context.Context),
) bool {
	group, found, err := r.client.LookupUserGroup(ctx, id)
	if err != nil {
		diags.AddError("Unable to read the user group", err.Error())
		return true
	}
	if !found {
		remove(ctx)
		return false
	}

	permissions, err := r.client.GetUserGroupPermissions(ctx, id)
	if err != nil {
		diags.AddError("Unable to read the user group permissions", err.Error())
		return true
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
	return true
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

// ensureComputedKnown replaces a still-unknown computed value with null.
//
// Terraform rejects an unknown value in the state an apply returns and reports
// it as a bug in the provider — four at once for this resource, which buries
// whatever actually went wrong. The refresh normally resolves them, so this
// only matters when that refresh is the thing that failed. Null is a legal
// value the next refresh fills in, and it is honest: nothing is known here.
func (m *userGroupResourceModel) ensureComputedKnown() {
	if m.CCPairIDs.IsUnknown() {
		m.CCPairIDs = types.SetNull(types.StringType)
	}
	if m.DocumentSetIDs.IsUnknown() {
		m.DocumentSetIDs = types.SetNull(types.StringType)
	}
	if m.PersonaIDs.IsUnknown() {
		m.PersonaIDs = types.SetNull(types.StringType)
	}
	if m.IsDefault.IsUnknown() {
		m.IsDefault = types.BoolNull()
	}
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
