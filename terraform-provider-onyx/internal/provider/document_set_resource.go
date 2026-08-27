package provider

import (
	"context"
	"strconv"
	"time"

	"github.com/hashicorp/terraform-plugin-framework-jsontypes/jsontypes"
	"github.com/hashicorp/terraform-plugin-framework-timeouts/resource/timeouts"
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
	_ resource.Resource                   = (*documentSetResource)(nil)
	_ resource.ResourceWithConfigure      = (*documentSetResource)(nil)
	_ resource.ResourceWithImportState    = (*documentSetResource)(nil)
	_ resource.ResourceWithValidateConfig = (*documentSetResource)(nil)
)

// Bounds for the background sync waits. Onyx rejects a change to a set that is
// still syncing, so every mutation waits for the previous one to land.
const (
	defaultDocumentSetUpdateTimeout = 10 * time.Minute
	defaultDocumentSetDeleteTimeout = 10 * time.Minute
)

// NewDocumentSetResource returns the onyx_document_set resource.
func NewDocumentSetResource() resource.Resource {
	return &documentSetResource{}
}

type documentSetResource struct {
	client *client.Client
}

type documentSetResourceModel struct {
	ID                  types.String   `tfsdk:"id"`
	Name                types.String   `tfsdk:"name"`
	Description         types.String   `tfsdk:"description"`
	CCPairIDs           types.Set      `tfsdk:"cc_pair_ids"`
	IsPublic            types.Bool     `tfsdk:"is_public"`
	Users               types.Set      `tfsdk:"users"`
	Groups              types.Set      `tfsdk:"groups"`
	FederatedConnectors types.Set      `tfsdk:"federated_connectors"`
	IsUpToDate          types.Bool     `tfsdk:"is_up_to_date"`
	Timeouts            timeouts.Value `tfsdk:"timeouts"`
}

// federatedConnectorAttrTypes mirrors the nested block, for building set values.
var federatedConnectorAttrTypes = map[string]attr.Type{
	"federated_connector_id": types.StringType,
	"entities":               jsontypes.NormalizedType{},
}

type federatedConnectorModel struct {
	FederatedConnectorID types.String         `tfsdk:"federated_connector_id"`
	Entities             jsontypes.Normalized `tfsdk:"entities"`
}

func (r *documentSetResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_document_set"
}

func (r *documentSetResource) Schema(ctx context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "A document set: a named group of connector-credential pairs that users and " +
			"assistants can search as one unit.\n\n" +
			"Onyx propagates changes to the search index in the background. `is_up_to_date` reports " +
			"whether that has finished, and usually reads `false` right after an apply.\n\n" +
			"~> **Private sets need Enterprise Edition.** `users` and `groups` are rejected on " +
			"Community Edition. `is_public = false` with neither set makes a set nobody can use.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Numeric document set id.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"name": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Document set name. Must be unique across the deployment.",
			},
			"description": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString(""),
				MarkdownDescription: "What the set contains, shown in the admin panel.",
			},
			"cc_pair_ids": schema.SetAttribute{
				Required:            true,
				ElementType:         types.StringType,
				MarkdownDescription: "Ids of the connector-credential pairs in the set, e.g. `[onyx_cc_pair.docs.id]`. Onyx rejects a set with no pairs and no federated connectors, so this may only be empty when `federated_connectors` is not.",
			},
			"is_public": schema.BoolAttribute{
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(true),
				MarkdownDescription: "Whether every user can see the set. When `false`, only the `users` and " +
					"`groups` below can. Onyx defaults new sets to public.",
			},
			"users": schema.SetAttribute{
				Optional:    true,
				ElementType: types.StringType,
				MarkdownDescription: "User ids (UUIDs) that may use the set when it is not public. " +
					"Enterprise Edition only — Community Edition rejects a set with users or groups.",
			},
			"groups": schema.SetAttribute{
				Optional:    true,
				ElementType: types.Int64Type,
				MarkdownDescription: "User group ids that may use the set when it is not public. " +
					"Enterprise Edition only — Community Edition rejects a set with users or groups.",
			},
			"is_up_to_date": schema.BoolAttribute{
				Computed: true,
				MarkdownDescription: "Whether Onyx has finished applying the set to the search index. " +
					"Reads `false` while the background sync is pending. Onyx refuses to change or " +
					"delete a set that is still syncing, so Terraform waits for this before it does either.",
			},
			"federated_connectors": schema.SetNestedAttribute{
				Optional:            true,
				MarkdownDescription: "Federated connectors searched as part of this set.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"federated_connector_id": schema.StringAttribute{
							Required:            true,
							MarkdownDescription: "Id of the federated connector.",
						},
						"entities": schema.StringAttribute{
							Required:            true,
							CustomType:          jsontypes.NormalizedType{},
							MarkdownDescription: "Which entities of that connector to search, as a JSON object.",
						},
					},
				},
			},
		},
		Blocks: map[string]schema.Block{
			"timeouts": timeouts.Block(ctx, timeouts.Opts{Update: true, Delete: true}),
		},
	}
}

func (r *documentSetResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// ValidateConfig rejects an empty set at plan time. Onyx refuses to create or
// update a document set that holds no connectors of either kind, and catching
// it here reports the problem before anything is applied.
func (r *documentSetResource) ValidateConfig(ctx context.Context, req resource.ValidateConfigRequest, resp *resource.ValidateConfigResponse) {
	var config documentSetResourceModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}
	// Unknown values are only resolved during apply, so they may still turn
	// out to be non-empty.
	if config.CCPairIDs.IsUnknown() || config.FederatedConnectors.IsUnknown() {
		return
	}
	if len(config.CCPairIDs.Elements()) > 0 || len(config.FederatedConnectors.Elements()) > 0 {
		return
	}
	resp.Diagnostics.AddAttributeError(
		path.Root("cc_pair_ids"),
		"Document set has no connectors",
		"Onyx rejects a document set that holds nothing. Give it at least one entry in "+
			"cc_pair_ids or in federated_connectors.",
	)
}

// waitForDocumentSetSync waits until Onyx has applied the set to the search
// index. Both update and delete are rejected outright while a previous change
// is still syncing, and a create leaves the set syncing, so every mutation
// waits first rather than failing an otherwise valid apply.
func (r *documentSetResource) waitForDocumentSetSync(ctx context.Context, id int64, timeout time.Duration) error {
	return client.Poll(ctx, timeout, "the document set to finish syncing",
		func(ctx context.Context) (bool, string, error) {
			remote, err := r.client.GetDocumentSet(ctx, id)
			if client.IsNotFound(err) {
				// Already gone: there is nothing left to sync.
				return true, "", nil
			}
			if err != nil {
				return false, "", err
			}
			return remote.IsUpToDate, "a previous change is still syncing", nil
		})
}

// writeFieldsFromModel builds the shared body of the create and update
// requests. Both are full replaces, so every field is always sent.
func (r *documentSetResource) writeFieldsFromModel(
	ctx context.Context,
	model documentSetResourceModel,
	diags *diag.Diagnostics,
) (ccPairIDs []int64, users []string, groups []int64, federated []client.FederatedConnectorConfig, ok bool) {
	ccPairIDs, idDiags := stringSetToInt64s(ctx, model.CCPairIDs, "cc_pair_ids")
	diags.Append(idDiags...)

	users, userDiags := stringSetValues(ctx, model.Users)
	diags.Append(userDiags...)

	groups, groupDiags := int64SetValues(ctx, model.Groups)
	diags.Append(groupDiags...)

	federated = []client.FederatedConnectorConfig{}
	if !model.FederatedConnectors.IsNull() && !model.FederatedConnectors.IsUnknown() {
		var entries []federatedConnectorModel
		diags.Append(model.FederatedConnectors.ElementsAs(ctx, &entries, false)...)
		for _, entry := range entries {
			id, parsed := parseID(entry.FederatedConnectorID, "federated connector", diags)
			if !parsed {
				continue
			}
			entities, entitiesOK := jsonObjectFromNormalized(entry.Entities, "entities", diags)
			if !entitiesOK {
				continue
			}
			federated = append(federated, client.FederatedConnectorConfig{
				FederatedConnectorID: id,
				Entities:             entities,
			})
		}
	}

	if diags.HasError() {
		return nil, nil, nil, nil, false
	}
	return ccPairIDs, users, groups, federated, true
}

// stringSetToInt64s reads a set of numeric id strings. Ids are strings in the
// schema so they can reference another resource's id attribute directly.
func stringSetToInt64s(ctx context.Context, set types.Set, attribute string) ([]int64, diag.Diagnostics) {
	var diags diag.Diagnostics
	raw, rawDiags := stringSetValues(ctx, set)
	diags.Append(rawDiags...)
	if diags.HasError() {
		return nil, diags
	}
	ids := make([]int64, 0, len(raw))
	for _, value := range raw {
		parsed, err := strconv.ParseInt(value, 10, 64)
		if err != nil {
			diags.AddError(
				"Invalid "+attribute,
				"Expected numeric ids, got "+value+".",
			)
			continue
		}
		ids = append(ids, parsed)
	}
	return ids, diags
}

// applyRemoteDocumentSet copies the server's view into the model. Optional
// collections stay null when the server reports nothing and the configuration
// left them unset, so an empty result never looks like a change.
func applyRemoteDocumentSet(ctx context.Context, model *documentSetResourceModel, remote *client.DocumentSet, diags *diag.Diagnostics) bool {
	ccPairIDs := make([]string, 0, len(remote.CCPairSummaries))
	for _, id := range remote.CCPairIDs() {
		ccPairIDs = append(ccPairIDs, strconv.FormatInt(id, 10))
	}
	ccPairSet, setDiags := types.SetValueFrom(ctx, types.StringType, ccPairIDs)
	diags.Append(setDiags...)

	users := model.Users
	if len(remote.Users) > 0 || !model.Users.IsNull() {
		value, userDiags := types.SetValueFrom(ctx, types.StringType, remote.Users)
		diags.Append(userDiags...)
		users = value
	}

	groups := model.Groups
	if len(remote.Groups) > 0 || !model.Groups.IsNull() {
		value, groupDiags := types.SetValueFrom(ctx, types.Int64Type, remote.Groups)
		diags.Append(groupDiags...)
		groups = value
	}

	federated := model.FederatedConnectors
	if len(remote.FederatedConnectorSummaries) > 0 || !model.FederatedConnectors.IsNull() {
		entries := make([]federatedConnectorModel, 0, len(remote.FederatedConnectorSummaries))
		for _, summary := range remote.FederatedConnectorSummaries {
			entities, ok := normalizedFromJSONObject(summary.Entities, "entities", diags)
			if !ok {
				return false
			}
			entries = append(entries, federatedConnectorModel{
				FederatedConnectorID: types.StringValue(strconv.FormatInt(summary.ID, 10)),
				Entities:             entities,
			})
		}
		value, federatedDiags := types.SetValueFrom(ctx, types.ObjectType{AttrTypes: federatedConnectorAttrTypes}, entries)
		diags.Append(federatedDiags...)
		federated = value
	}

	if diags.HasError() {
		return false
	}

	model.ID = types.StringValue(strconv.FormatInt(remote.ID, 10))
	model.Name = types.StringValue(remote.Name)
	// description is required on write but nullable on read, so an unset one
	// round-trips as the empty string rather than flipping to null.
	if remote.Description == nil {
		model.Description = types.StringValue("")
	} else {
		model.Description = types.StringValue(*remote.Description)
	}
	model.CCPairIDs = ccPairSet
	model.IsPublic = types.BoolValue(remote.IsPublic)
	model.Users = users
	model.Groups = groups
	model.FederatedConnectors = federated
	model.IsUpToDate = types.BoolValue(remote.IsUpToDate)
	return true
}

func (r *documentSetResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan documentSetResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	ccPairIDs, users, groups, federated, ok := r.writeFieldsFromModel(ctx, plan, &resp.Diagnostics)
	if !ok {
		return
	}

	id, err := r.client.CreateDocumentSet(ctx, client.DocumentSetCreate{
		Name:                plan.Name.ValueString(),
		Description:         plan.Description.ValueString(),
		CCPairIDs:           ccPairIDs,
		IsPublic:            plan.IsPublic.ValueBool(),
		Users:               users,
		Groups:              groups,
		FederatedConnectors: federated,
	})
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx document set", err.Error())
		return
	}

	remote, err := r.client.GetDocumentSet(ctx, id)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read back the new Onyx document set", err.Error())
		// Persist the id so the next apply updates instead of creating a duplicate.
		plan.ID = types.StringValue(strconv.FormatInt(id, 10))
		resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
		return
	}
	if !applyRemoteDocumentSet(ctx, &plan, remote, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *documentSetResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state documentSetResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "document set", &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.GetDocumentSet(ctx, id)
	if client.IsNotFound(err) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx document set", err.Error())
		return
	}
	if !applyRemoteDocumentSet(ctx, &state, remote, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *documentSetResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state documentSetResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "document set", &resp.Diagnostics)
	if !ok {
		return
	}
	ccPairIDs, users, groups, federated, ok := r.writeFieldsFromModel(ctx, plan, &resp.Diagnostics)
	if !ok {
		return
	}
	updateTimeout, timeoutDiags := plan.Timeouts.Update(ctx, defaultDocumentSetUpdateTimeout)
	resp.Diagnostics.Append(timeoutDiags...)
	if resp.Diagnostics.HasError() {
		return
	}
	// One deadline for the whole update, so the wait and the write together
	// stay inside the configured timeout.
	ctx, cancel := context.WithTimeout(ctx, updateTimeout)
	defer cancel()

	if err := r.waitForDocumentSetSync(ctx, id, updateTimeout); err != nil {
		resp.Diagnostics.AddError("Failed to update Onyx document set", err.Error())
		return
	}

	err := r.client.UpdateDocumentSet(ctx, client.DocumentSetUpdate{
		ID:                  id,
		Name:                plan.Name.ValueString(),
		Description:         plan.Description.ValueString(),
		CCPairIDs:           ccPairIDs,
		IsPublic:            plan.IsPublic.ValueBool(),
		Users:               users,
		Groups:              groups,
		FederatedConnectors: federated,
	})
	if err != nil {
		resp.Diagnostics.AddError("Failed to update Onyx document set", err.Error())
		return
	}

	remote, err := r.client.GetDocumentSet(ctx, id)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read back the Onyx document set", err.Error())
		return
	}
	if !applyRemoteDocumentSet(ctx, &plan, remote, &resp.Diagnostics) {
		return
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *documentSetResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state documentSetResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "document set", &resp.Diagnostics)
	if !ok {
		return
	}
	deleteTimeout, timeoutDiags := state.Timeouts.Delete(ctx, defaultDocumentSetDeleteTimeout)
	resp.Diagnostics.Append(timeoutDiags...)
	if resp.Diagnostics.HasError() {
		return
	}
	// One deadline for the whole destroy: the wait for the previous sync, the
	// delete itself, and the wait for the row to go.
	ctx, cancel := context.WithTimeout(ctx, deleteTimeout)
	defer cancel()

	if err := r.waitForDocumentSetSync(ctx, id, deleteTimeout); err != nil {
		resp.Diagnostics.AddError("Failed to delete Onyx document set", err.Error())
		return
	}

	err := r.client.DeleteDocumentSet(ctx, id)
	if client.IsNotFound(err) {
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to delete Onyx document set", err.Error())
		return
	}

	// Delete only marks the set; the background sync drops the row. Names are
	// unique, so a replacement cannot apply until that finishes.
	err = client.Poll(ctx, deleteTimeout, "the document set to be deleted",
		func(ctx context.Context) (bool, string, error) {
			_, err := r.client.GetDocumentSet(ctx, id)
			if client.IsNotFound(err) {
				return true, "", nil
			}
			if err != nil {
				return false, "", err
			}
			return false, "the document set is still marked for deletion", nil
		})
	if err != nil {
		resp.Diagnostics.AddError("Failed to delete Onyx document set", err.Error())
	}
}

func (r *documentSetResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
