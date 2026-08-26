package provider

import (
	"context"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework/attr"
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
	_ resource.Resource                = (*personaResource)(nil)
	_ resource.ResourceWithConfigure   = (*personaResource)(nil)
	_ resource.ResourceWithImportState = (*personaResource)(nil)
)

// NewPersonaResource returns the onyx_persona resource.
func NewPersonaResource() resource.Resource {
	return &personaResource{}
}

type personaResource struct {
	client *client.Client
}

type personaResourceModel struct {
	ID                          types.String `tfsdk:"id"`
	Name                        types.String `tfsdk:"name"`
	Description                 types.String `tfsdk:"description"`
	SystemPrompt                types.String `tfsdk:"system_prompt"`
	TaskPrompt                  types.String `tfsdk:"task_prompt"`
	ReplaceBaseSystemPrompt     types.Bool   `tfsdk:"replace_base_system_prompt"`
	DatetimeAware               types.Bool   `tfsdk:"datetime_aware"`
	DocumentSetIDs              types.Set    `tfsdk:"document_set_ids"`
	ToolIDs                     types.Set    `tfsdk:"tool_ids"`
	IsPublic                    types.Bool   `tfsdk:"is_public"`
	IsListed                    types.Bool   `tfsdk:"is_listed"`
	IsFeatured                  types.Bool   `tfsdk:"is_featured"`
	DisplayPriority             types.Int64  `tfsdk:"display_priority"`
	IconName                    types.String `tfsdk:"icon_name"`
	StarterMessages             types.List   `tfsdk:"starter_messages"`
	LabelIDs                    types.Set    `tfsdk:"label_ids"`
	DefaultModelConfigurationID types.String `tfsdk:"default_model_configuration_id"`
	SearchStartDate             types.String `tfsdk:"search_start_date"`
	Users                       types.Set    `tfsdk:"users"`
	Groups                      types.Set    `tfsdk:"groups"`
	BuiltinPersona              types.Bool   `tfsdk:"builtin_persona"`
}

// starterMessageAttrTypes mirrors the nested block, for building list values.
var starterMessageAttrTypes = map[string]attr.Type{
	"name":    types.StringType,
	"message": types.StringType,
}

type starterMessageModel struct {
	Name    types.String `tfsdk:"name"`
	Message types.String `tfsdk:"message"`
}

func (r *personaResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_persona"
}

func (r *personaResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "An agent (assistant): a named set of instructions, knowledge and actions " +
			"that users can chat with.\n\n" +
			"Agent names are unique. Creating one under a name another agent already holds fails; " +
			"creating one under the name of a *deleted* agent revives that agent instead, keeping its " +
			"original id.\n\n" +
			"~> **Deleting an agent leaves a tombstone.** Onyx marks it deleted rather than removing " +
			"the row, so the name stays taken. Creating an agent under that name later revives the " +
			"tombstone, which is why a destroy followed by an apply returns the same agent id.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Numeric agent id.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"name": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Agent name. Must be unique across the deployment.",
			},
			"description": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString(""),
				MarkdownDescription: "One line describing the agent, shown on its card.",
			},
			"system_prompt": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString(""),
				MarkdownDescription: "The agent's instructions, added to the system prompt.",
			},
			"task_prompt": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString(""),
				MarkdownDescription: "Extra instructions appended to each user message.",
			},
			"replace_base_system_prompt": schema.BoolAttribute{
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(false),
				MarkdownDescription: "Use `system_prompt` on its own instead of adding it to Onyx's " +
					"base prompt. Replacing the base prompt drops the instructions that make " +
					"citations and search work, so leave it off unless the agent needs full control.",
			},
			"datetime_aware": schema.BoolAttribute{
				Optional:            true,
				Computed:            true,
				Default:             booldefault.StaticBool(false),
				MarkdownDescription: "Tell the agent the current date and time.",
			},
			"document_set_ids": schema.SetAttribute{
				Optional:            true,
				ElementType:         types.StringType,
				MarkdownDescription: "Ids of the document sets the agent can search, e.g. `[onyx_document_set.handbook.id]`.",
			},
			"tool_ids": schema.SetAttribute{
				Optional:    true,
				ElementType: types.StringType,
				MarkdownDescription: "Ids of the actions the agent can call, e.g. `[onyx_custom_tool.weather.id]`. " +
					"Onyx keeps two built-in actions out of its own API responses, so attaching one of " +
					"those produces a permanent difference; attach custom actions and the ordinary " +
					"built-ins instead.",
			},
			"is_public": schema.BoolAttribute{
				Optional:            true,
				Computed:            true,
				Default:             booldefault.StaticBool(true),
				MarkdownDescription: "Whether every user can use the agent. When `false`, only `users` and `groups` can.",
			},
			"is_listed": schema.BoolAttribute{
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(true),
				MarkdownDescription: "Whether the agent appears in the assistant list. A hidden agent still " +
					"works for anyone holding a link to it. Onyx sets this through its own endpoint, so " +
					"Terraform applies it as a second call after the agent is written.",
			},
			"is_featured": schema.BoolAttribute{
				Optional:            true,
				Computed:            true,
				Default:             booldefault.StaticBool(false),
				MarkdownDescription: "Whether Onyx promotes the agent to users. Requires agent-management permission.",
			},
			"display_priority": schema.Int64Attribute{
				Optional: true,
				Computed: true,
				MarkdownDescription: "Sort position in the assistant list. Lower sorts first. " +
					"Onyx reads this from the agent only when it is created, so a later change is " +
					"applied through its own endpoint as a second call. Removing the attribute " +
					"leaves the last value in place rather than clearing it.",
			},
			"icon_name": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Name of the built-in icon shown on the agent's card.",
			},
			"label_ids": schema.SetAttribute{
				Optional:            true,
				ElementType:         types.Int64Type,
				MarkdownDescription: "Ids of the labels the agent is filed under. Labels are created in the admin panel.",
			},
			"default_model_configuration_id": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "Id of the model configuration the agent uses. Leave unset to use the " +
					"deployment default.",
			},
			"search_start_date": schema.StringAttribute{
				Optional: true,
				MarkdownDescription: "Ignore documents older than this date, as `YYYY-MM-DD` or a full " +
					"timestamp.\n\n" +
					"~> Onyx does not return this field, so Terraform cannot detect a change made " +
					"outside it. The configured value is re-sent on every apply.",
			},
			"users": schema.SetAttribute{
				Optional:    true,
				ElementType: types.StringType,
				MarkdownDescription: "User ids (UUIDs) that may use the agent when it is not public. " +
					"Enterprise Edition only.",
			},
			"groups": schema.SetAttribute{
				Optional:    true,
				ElementType: types.Int64Type,
				MarkdownDescription: "User group ids that may use the agent when it is not public. " +
					"Enterprise Edition only.",
			},
			"builtin_persona": schema.BoolAttribute{
				Computed: true,
				MarkdownDescription: "Whether Onyx ships the agent as a built-in. Built-in agents are " +
					"configured in the deployment, not through the API.",
			},
			"starter_messages": schema.ListNestedAttribute{
				Optional:            true,
				MarkdownDescription: "Suggested opening prompts, shown in the order given.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"name": schema.StringAttribute{
							Required:            true,
							MarkdownDescription: "Short label shown on the button.",
						},
						"message": schema.StringAttribute{
							Required:            true,
							MarkdownDescription: "Message sent when the user picks it.",
						},
					},
				},
			},
		},
	}
}

func (r *personaResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// writeFromModel builds the body shared by create and update. Both replace the
// whole agent, so every managed field is always sent.
func (r *personaResource) writeFromModel(
	ctx context.Context,
	model personaResourceModel,
	diags *diag.Diagnostics,
) (client.PersonaWrite, bool) {
	documentSetIDs, setDiags := stringSetToInt64s(ctx, model.DocumentSetIDs, "document_set_ids")
	diags.Append(setDiags...)

	toolIDs, toolDiags := stringSetToInt64s(ctx, model.ToolIDs, "tool_ids")
	diags.Append(toolDiags...)

	labelIDs, labelDiags := int64SetValues(ctx, model.LabelIDs)
	diags.Append(labelDiags...)

	users, userDiags := stringSetValues(ctx, model.Users)
	diags.Append(userDiags...)

	groups, groupDiags := int64SetValues(ctx, model.Groups)
	diags.Append(groupDiags...)

	starterMessages := []client.StarterMessage{}
	if !model.StarterMessages.IsNull() && !model.StarterMessages.IsUnknown() {
		var entries []starterMessageModel
		diags.Append(model.StarterMessages.ElementsAs(ctx, &entries, false)...)
		for _, entry := range entries {
			starterMessages = append(starterMessages, client.StarterMessage{
				Name:    entry.Name.ValueString(),
				Message: entry.Message.ValueString(),
			})
		}
	}

	var defaultModelConfigurationID *int64
	if !model.DefaultModelConfigurationID.IsNull() && !model.DefaultModelConfigurationID.IsUnknown() {
		parsed, ok := parseID(model.DefaultModelConfigurationID, "model configuration", diags)
		if !ok {
			return client.PersonaWrite{}, false
		}
		defaultModelConfigurationID = &parsed
	}

	if diags.HasError() {
		return client.PersonaWrite{}, false
	}

	isPublic := model.IsPublic.ValueBool()
	isFeatured := model.IsFeatured.ValueBool()
	return client.PersonaWrite{
		Name:                        model.Name.ValueString(),
		Description:                 model.Description.ValueString(),
		DocumentSetIDs:              documentSetIDs,
		ToolIDs:                     toolIDs,
		SystemPrompt:                model.SystemPrompt.ValueString(),
		TaskPrompt:                  model.TaskPrompt.ValueString(),
		DatetimeAware:               model.DatetimeAware.ValueBool(),
		ReplaceBaseSystemPrompt:     model.ReplaceBaseSystemPrompt.ValueBool(),
		IsPublic:                    &isPublic,
		IsFeatured:                  &isFeatured,
		IconName:                    stringPointer(model.IconName),
		DisplayPriority:             int64Pointer(model.DisplayPriority),
		StarterMessages:             starterMessages,
		LabelIDs:                    labelIDs,
		DefaultModelConfigurationID: defaultModelConfigurationID,
		SearchStartDate:             stringPointer(model.SearchStartDate),
		Users:                       users,
		Groups:                      groups,
		HierarchyNodeIDs:            []int64{},
		DocumentIDs:                 []string{},
	}, true
}

// applyRemotePersona copies the server's view into the model.
//
// search_start_date is left alone. Onyx parses it into a timestamp and returns
// that, so reading it back would rewrite a plain date into a form the
// configuration never used and report a change on every plan.
func applyRemotePersona(ctx context.Context, model *personaResourceModel, remote *client.Persona, diags *diag.Diagnostics) bool {
	documentSetIDs := idSetFromInt64s(ctx, model.DocumentSetIDs, remote.DocumentSetIDs(), diags)
	toolIDs := idSetFromInt64s(ctx, model.ToolIDs, remote.ToolIDs(), diags)

	labelIDs := model.LabelIDs
	if len(remote.LabelIDs()) > 0 || !model.LabelIDs.IsNull() {
		value, labelDiags := types.SetValueFrom(ctx, types.Int64Type, remote.LabelIDs())
		diags.Append(labelDiags...)
		labelIDs = value
	}

	users := model.Users
	if len(remote.UserIDs()) > 0 || !model.Users.IsNull() {
		value, userDiags := types.SetValueFrom(ctx, types.StringType, remote.UserIDs())
		diags.Append(userDiags...)
		users = value
	}

	groups := model.Groups
	if len(remote.Groups) > 0 || !model.Groups.IsNull() {
		value, groupDiags := types.SetValueFrom(ctx, types.Int64Type, remote.Groups)
		diags.Append(groupDiags...)
		groups = value
	}

	starterMessages := model.StarterMessages
	if len(remote.StarterMessages) > 0 || !model.StarterMessages.IsNull() {
		entries := make([]starterMessageModel, 0, len(remote.StarterMessages))
		for _, message := range remote.StarterMessages {
			entries = append(entries, starterMessageModel{
				Name:    types.StringValue(message.Name),
				Message: types.StringValue(message.Message),
			})
		}
		value, messageDiags := types.ListValueFrom(ctx, types.ObjectType{AttrTypes: starterMessageAttrTypes}, entries)
		diags.Append(messageDiags...)
		starterMessages = value
	}

	if diags.HasError() {
		return false
	}

	model.ID = types.StringValue(strconv.FormatInt(remote.ID, 10))
	model.Name = types.StringValue(remote.Name)
	model.Description = types.StringValue(remote.Description)
	// The prompts are required on write but nullable on read, so an unset one
	// round-trips as the empty string rather than flipping to null.
	model.SystemPrompt = types.StringValue(stringOrEmpty(remote.SystemPrompt))
	model.TaskPrompt = types.StringValue(stringOrEmpty(remote.TaskPrompt))
	model.ReplaceBaseSystemPrompt = types.BoolValue(remote.ReplaceBaseSystemPrompt)
	model.DatetimeAware = types.BoolValue(remote.DatetimeAware)
	model.DocumentSetIDs = documentSetIDs
	model.ToolIDs = toolIDs
	model.IsPublic = types.BoolValue(remote.IsPublic)
	model.IsListed = types.BoolValue(remote.IsListed)
	model.IsFeatured = types.BoolValue(remote.IsFeatured)
	model.BuiltinPersona = types.BoolValue(remote.BuiltinPersona)
	model.StarterMessages = starterMessages
	model.LabelIDs = labelIDs
	model.Users = users
	model.Groups = groups
	if remote.IconName == nil {
		model.IconName = types.StringNull()
	} else {
		model.IconName = types.StringValue(*remote.IconName)
	}
	if remote.DisplayPriority == nil {
		model.DisplayPriority = types.Int64Null()
	} else {
		model.DisplayPriority = types.Int64Value(*remote.DisplayPriority)
	}
	if remote.DefaultModelConfigurationID == nil {
		model.DefaultModelConfigurationID = types.StringNull()
	} else {
		model.DefaultModelConfigurationID = types.StringValue(
			strconv.FormatInt(*remote.DefaultModelConfigurationID, 10))
	}
	return true
}

// idSetFromInt64s renders ids as a set of strings, keeping an unset attribute
// null when the server reports nothing so an empty result is not a change.
func idSetFromInt64s(ctx context.Context, current types.Set, ids []int64, diags *diag.Diagnostics) types.Set {
	if len(ids) == 0 && current.IsNull() {
		return current
	}
	values := make([]string, 0, len(ids))
	for _, id := range ids {
		values = append(values, strconv.FormatInt(id, 10))
	}
	value, setDiags := types.SetValueFrom(ctx, types.StringType, values)
	diags.Append(setDiags...)
	return value
}

// stringOrEmpty reads a nullable string, mapping null to the empty string.
func stringOrEmpty(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

// applyListed applies is_listed, which has its own endpoint, and reports the
// value that ended up stored.
func (r *personaResource) applyListed(ctx context.Context, id int64, desired bool, remote *client.Persona) error {
	if remote.IsListed == desired {
		return nil
	}
	if err := r.client.SetPersonaListed(ctx, id, desired); err != nil {
		return err
	}
	remote.IsListed = desired
	return nil
}

// applyDisplayPriority applies display_priority, which the upsert ignores once
// the agent exists, and reports the value that ended up stored.
//
// The endpoint can only set a number, so an attribute cleared in the
// configuration is left as it is. Marking it computed makes that the declared
// behaviour rather than a difference that never settles.
func (r *personaResource) applyDisplayPriority(ctx context.Context, id int64, desired types.Int64, remote *client.Persona) error {
	if desired.IsNull() || desired.IsUnknown() {
		return nil
	}
	if remote.DisplayPriority != nil && *remote.DisplayPriority == desired.ValueInt64() {
		return nil
	}
	if err := r.client.SetPersonaDisplayPriority(ctx, id, desired.ValueInt64()); err != nil {
		return err
	}
	priority := desired.ValueInt64()
	remote.DisplayPriority = &priority
	return nil
}

func (r *personaResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan personaResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	write, ok := r.writeFromModel(ctx, plan, &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.CreatePersona(ctx, write)
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx agent", err.Error())
		return
	}

	// is_listed is a follow-up call. A failure is reported after the state is
	// written, so the agent that now exists stays tracked.
	listedErr := r.applyListed(ctx, remote.ID, plan.IsListed.ValueBool(), remote)

	if !applyRemotePersona(ctx, &plan, remote, &resp.Diagnostics) {
		// Record the id even so. Names are unique, so an agent left out of
		// state would fail every later apply as a duplicate.
		plan.ID = types.StringValue(strconv.FormatInt(remote.ID, 10))
		resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
	if listedErr != nil {
		resp.Diagnostics.AddError("Failed to set whether the new Onyx agent is listed", listedErr.Error())
	}
}

func (r *personaResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state personaResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "agent", &resp.Diagnostics)
	if !ok {
		return
	}

	remote, found, err := r.client.LookupPersona(ctx, id)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx agent", err.Error())
		return
	}
	if !found {
		resp.State.RemoveResource(ctx)
		return
	}
	if !applyRemotePersona(ctx, &state, remote, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *personaResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state personaResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "agent", &resp.Diagnostics)
	if !ok {
		return
	}
	write, ok := r.writeFromModel(ctx, plan, &resp.Diagnostics)
	if !ok {
		return
	}

	// The update replaces the whole agent, and an omitted folder or document
	// list clears it. Terraform does not manage those, so carry over whatever
	// the agent holds rather than dropping it.
	//
	// Reading them back is the only option the API leaves: both fields are
	// plain lists on the request model, so omitting one clears it and sending
	// null is rejected outright (422, "Input should be a valid list"). That
	// leaves a narrow window in which an attachment added between this read and
	// the write below is reverted. Making the two fields nullable server-side,
	// so null means "leave unchanged", would remove the read and the window
	// with it.
	current, err := r.client.GetPersona(ctx, id)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read the Onyx agent before updating it", err.Error())
		return
	}
	write.HierarchyNodeIDs = current.HierarchyNodeIDs()
	write.DocumentIDs = current.DocumentIDs()

	remote, err := r.client.UpdatePersona(ctx, id, write)
	if err != nil {
		resp.Diagnostics.AddError("Failed to update Onyx agent", err.Error())
		return
	}

	// The agent itself is already written, so a failure here is reported after
	// the state is saved rather than leaving state describing the old agent.
	listedErr := r.applyListed(ctx, id, plan.IsListed.ValueBool(), remote)
	if listedErr == nil {
		listedErr = r.applyDisplayPriority(ctx, id, plan.DisplayPriority, remote)
	}

	if !applyRemotePersona(ctx, &plan, remote, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
	if listedErr != nil {
		resp.Diagnostics.AddError("Failed to finish updating the Onyx agent", listedErr.Error())
	}
}

func (r *personaResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state personaResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "agent", &resp.Diagnostics)
	if !ok {
		return
	}

	err := r.client.DeletePersona(ctx, id)
	if err == nil || client.IsNotFound(err) {
		return
	}
	// An agent that is already a tombstone fails this call, and not with a 404:
	// the lookup behind it rejects a deleted agent, and the handler reports that
	// as a permission error. Confirm it is really gone before failing a destroy.
	if _, found, lookupErr := r.client.LookupPersona(ctx, id); lookupErr == nil && !found {
		return
	}
	resp.Diagnostics.AddError("Failed to delete Onyx agent", err.Error())
}

func (r *personaResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
