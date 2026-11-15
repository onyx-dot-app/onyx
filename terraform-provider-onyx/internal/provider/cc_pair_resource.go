package provider

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/hashicorp/terraform-plugin-framework-jsontypes/jsontypes"
	"github.com/hashicorp/terraform-plugin-framework-timeouts/resource/timeouts"
	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/booldefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/setplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                   = (*ccPairResource)(nil)
	_ resource.ResourceWithConfigure      = (*ccPairResource)(nil)
	_ resource.ResourceWithImportState    = (*ccPairResource)(nil)
	_ resource.ResourceWithValidateConfig = (*ccPairResource)(nil)
)

// Access types whose readers come from data-access groups.
var ccPairDataAccessTypes = map[string]bool{"private": true, "sync_restricted": true}

// defaultCCPairDeleteTimeout bounds the wait for Celery to remove a pair and
// the documents it indexed. Large connectors take minutes, not seconds.
const defaultCCPairDeleteTimeout = 30 * time.Minute

// NewCCPairResource returns the onyx_cc_pair resource.
func NewCCPairResource() resource.Resource {
	return &ccPairResource{}
}

type ccPairResource struct {
	client *client.Client
}

type ccPairResourceModel struct {
	ID                     types.String         `tfsdk:"id"`
	ConnectorID            types.String         `tfsdk:"connector_id"`
	CredentialID           types.String         `tfsdk:"credential_id"`
	Name                   types.String         `tfsdk:"name"`
	AccessType             types.String         `tfsdk:"access_type"`
	AutoSyncOptions        jsontypes.Normalized `tfsdk:"auto_sync_options"`
	Groups                 types.Set            `tfsdk:"groups"`
	DataAccessGroupIDs     types.Set            `tfsdk:"data_access_group_ids"`
	ProcessingMode         types.String         `tfsdk:"processing_mode"`
	Paused                 types.Bool           `tfsdk:"paused"`
	Status                 types.String         `tfsdk:"status"`
	NumDocsIndexed         types.Int64          `tfsdk:"num_docs_indexed"`
	LastIndexAttemptStatus types.String         `tfsdk:"last_index_attempt_status"`
	Timeouts               timeouts.Value       `tfsdk:"timeouts"`
}

func (r *ccPairResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_cc_pair"
}

func (r *ccPairResource) Schema(ctx context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "A connector-credential pair: the object that actually indexes. It joins an " +
			"`onyx_connector` to an `onyx_credential` and carries the access control for the documents " +
			"they produce.\n\n" +
			"Creating a pair starts indexing. Destroying one removes the indexed documents too, which " +
			"runs in the background — Terraform waits for it to finish.\n\n" +
			"~> **Replacement re-indexes.** Onyx has no update route for `access_type`, `groups`, " +
			"`auto_sync_options` or `processing_mode`, so a change to one of them replaces the pair: " +
			"Onyx deletes its documents and indexes them again. Terraform reads these attributes back, " +
			"so a change made in the admin panel to an attribute in the configuration also shows as a " +
			"replacement. An attribute left out of the configuration keeps the value Onyx reports.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Numeric connector-credential pair id.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"connector_id": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Id of the connector to pair, e.g. `onyx_connector.docs.id`.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"credential_id": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Id of the credential to pair, e.g. `onyx_credential.docs.id`.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"name": schema.StringAttribute{
				Required: true,
				MarkdownDescription: "Pair name, shown in the admin panel. Onyx does not require it to " +
					"be unique, but a connector and credential can only be paired once.",
			},
			"access_type": schema.StringAttribute{
				Optional: true,
				Computed: true,
				Default:  stringdefault.StaticString("public"),
				MarkdownDescription: "Who may read the indexed documents: `public` (everyone), `private` " +
					"(the groups below), `sync` (mirrored from the source system), or `sync_restricted` " +
					"(mirrored from the source system, and only for members of " +
					"`data_access_group_ids`). `sync` and `sync_restricted` need a Business tier license " +
					"and a source that supports permission sync. `sync_restricted` needs Onyx v5.0 or " +
					"later: v4.9 knows the value but refuses to create such a pair. Unset means `public`, " +
					"also after an import: set it to match an imported pair, or the next apply replaces " +
					"the pair.",
				Validators: []validator.String{
					stringvalidator.OneOf("public", "private", "sync", "sync_restricted"),
				},
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"auto_sync_options": schema.StringAttribute{
				Optional:   true,
				Computed:   true,
				CustomType: jsontypes.NormalizedType{},
				MarkdownDescription: "Permission-sync settings as a JSON object. Only meaningful with " +
					"`access_type = \"sync\"` or `\"sync_restricted\"`.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
					stringplanmodifier.RequiresReplace(),
				},
			},
			"groups": schema.SetAttribute{
				Optional:    true,
				Computed:    true,
				ElementType: types.Int64Type,
				MarkdownDescription: "User group ids linked to the pair. With `access_type = \"private\"` " +
					"their members may read the documents, unless `data_access_group_ids` names other " +
					"groups. From Onyx v5.0 these groups also manage the pair.",
				PlanModifiers: []planmodifier.Set{
					setplanmodifier.UseStateForUnknown(),
					setplanmodifier.RequiresReplace(),
				},
			},
			"data_access_group_ids": schema.SetAttribute{
				Optional:    true,
				ElementType: types.Int64Type,
				MarkdownDescription: "User group ids whose members may read the documents of a `private` " +
					"or `sync_restricted` pair. Required for `sync_restricted`. Unset on create means the " +
					"`groups` above. A change is applied in place. Needs Onyx v5.0 or later and " +
					"Enterprise Edition; on other servers, apply fails rather than skip the setting. " +
					"Terraform refreshes this attribute only while it is set. Removing it, or importing " +
					"a pair, leaves the groups in Onyx as they are, and they can differ from `groups`.",
			},
			"processing_mode": schema.StringAttribute{
				Optional: true,
				Computed: true,
				MarkdownDescription: "How fetched documents are processed. Defaults to `REGULAR`, the full " +
					"index pipeline. `RAW_BINARY` stores the file without extracting text. `FILE_SYSTEM` " +
					"is deprecated and produces documents that cannot be searched.",
				Validators: []validator.String{
					stringvalidator.OneOf("REGULAR", "RAW_BINARY", "FILE_SYSTEM"),
				},
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
					stringplanmodifier.RequiresReplace(),
				},
			},
			"paused": schema.BoolAttribute{
				Optional: true,
				Computed: true,
				Default:  booldefault.StaticBool(false),
				MarkdownDescription: "Pause indexing. A paused pair keeps its documents but runs no new " +
					"index attempts.",
			},
			"status": schema.StringAttribute{
				Computed: true,
				MarkdownDescription: "Server status: `SCHEDULED`, `INITIAL_INDEXING`, `ACTIVE`, `PAUSED`, " +
					"`DELETING` or `INVALID`. Onyx cycles it as indexing progresses; use `paused` to change it.",
			},
			"num_docs_indexed": schema.Int64Attribute{
				Computed:            true,
				MarkdownDescription: "Documents currently indexed by this pair.",
			},
			"last_index_attempt_status": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Status of the most recent index attempt, or null before the first one runs.",
			},
		},
		Blocks: map[string]schema.Block{
			"timeouts": timeouts.Block(ctx, timeouts.Opts{Delete: true}),
		},
	}
}

func (r *ccPairResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

// ValidateConfig reports at plan time the data-access rules Onyx enforces at
// create time.
func (r *ccPairResource) ValidateConfig(ctx context.Context, req resource.ValidateConfigRequest, resp *resource.ValidateConfigResponse) {
	var config ccPairResourceModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() || config.AccessType.IsUnknown() || config.DataAccessGroupIDs.IsUnknown() {
		return
	}
	accessType := config.AccessType.ValueString()
	if config.AccessType.IsNull() {
		accessType = "public"
	}
	setsDataAccess := !config.DataAccessGroupIDs.IsNull()
	hasDataAccess := setsDataAccess && len(config.DataAccessGroupIDs.Elements()) > 0
	if accessType == "sync_restricted" && !hasDataAccess {
		resp.Diagnostics.AddAttributeError(path.Root("data_access_group_ids"),
			"Missing data-access groups",
			"access_type = \"sync_restricted\" needs at least one group in data_access_group_ids.")
	}
	// Onyx refuses the data-access route for other types, even with an empty list.
	if setsDataAccess && !ccPairDataAccessTypes[accessType] {
		resp.Diagnostics.AddAttributeError(path.Root("data_access_group_ids"),
			"Data-access groups need a private or restricted pair",
			fmt.Sprintf("Onyx accepts data_access_group_ids only with access_type \"private\" or "+
				"\"sync_restricted\", not %q.", accessType))
	}
}

// applyRemoteCCPair copies the server's view into the model. Data-access
// groups have their own route; see refreshDataAccess.
func applyRemoteCCPair(ctx context.Context, model *ccPairResourceModel, remote *client.CCPair, diags *diag.Diagnostics) {
	model.ID = types.StringValue(strconv.FormatInt(remote.ID, 10))
	model.ConnectorID = types.StringValue(strconv.FormatInt(remote.Connector.ID, 10))
	model.CredentialID = types.StringValue(strconv.FormatInt(remote.Credential.ID, 10))
	model.Name = types.StringValue(remote.Name)
	model.AccessType = types.StringValue(remote.AccessType)
	model.Status = types.StringValue(remote.Status)
	model.Paused = types.BoolValue(remote.Status == client.CCPairStatusPaused)
	model.NumDocsIndexed = types.Int64Value(remote.NumDocsIndexed)
	model.LastIndexAttemptStatus = types.StringPointerValue(remote.LastIndexAttemptStatus)

	// Onyx before v4.8 does not return these fields. Keep what Terraform knows,
	// so an older server does not plan a replacement.
	if remote.ProcessingMode == "" {
		if model.Groups.IsUnknown() {
			model.Groups = types.SetValueMust(types.Int64Type, nil)
		}
		if model.AutoSyncOptions.IsUnknown() {
			model.AutoSyncOptions = jsontypes.NewNormalizedNull()
		}
		if model.ProcessingMode.IsUnknown() {
			model.ProcessingMode = types.StringValue("REGULAR")
		}
		return
	}
	model.ProcessingMode = types.StringValue(remote.ProcessingMode)

	groups := remote.Groups
	if groups == nil {
		groups = []int64{}
	}
	groupSet, setDiags := types.SetValueFrom(ctx, types.Int64Type, groups)
	diags.Append(setDiags...)
	model.Groups = groupSet

	if remote.AutoSyncOptions == nil {
		model.AutoSyncOptions = jsontypes.NewNormalizedNull()
	} else if value, ok := normalizedFromJSONObject(remote.AutoSyncOptions, "auto_sync_options", diags); ok {
		model.AutoSyncOptions = value
	}
}

// refreshDataAccess reads the data-access groups while the configuration
// sets them. A 403 keeps the known value. A 404 means Onyx before v5.0 or
// Community Edition: a read keeps the known value, but after a write it is an
// error, because Onyx dropped the groups.
func (r *ccPairResource) refreshDataAccess(ctx context.Context, id int64, model *ccPairResourceModel, afterWrite bool, diags *diag.Diagnostics) {
	if model.DataAccessGroupIDs.IsNull() || model.DataAccessGroupIDs.IsUnknown() ||
		!ccPairDataAccessTypes[model.AccessType.ValueString()] {
		return
	}
	groupIDs, err := r.client.GetCCPairDataAccess(ctx, id)
	if client.IsNotFound(err) && afterWrite {
		diags.AddAttributeError(path.Root("data_access_group_ids"),
			"Onyx did not store the data-access groups",
			"data_access_group_ids needs Onyx v5.0 or later and Enterprise Edition. This server has "+
				"no data-access route, so readers are not restricted to these groups. Upgrade Onyx "+
				"or remove the attribute.")
		return
	}
	if client.IsNotFound(err) || client.IsForbidden(err) {
		return
	}
	if err != nil {
		diags.AddError("Failed to read the data-access groups of the Onyx connector-credential pair", err.Error())
		return
	}
	value, setDiags := types.SetValueFrom(ctx, types.Int64Type, groupIDs)
	diags.Append(setDiags...)
	model.DataAccessGroupIDs = value
}

func (r *ccPairResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan ccPairResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	connectorID, ok := parseID(plan.ConnectorID, "connector", &resp.Diagnostics)
	if !ok {
		return
	}
	credentialID, ok := parseID(plan.CredentialID, "credential", &resp.Diagnostics)
	if !ok {
		return
	}
	autoSyncOptions, ok := jsonObjectFromNormalized(plan.AutoSyncOptions, "auto_sync_options", &resp.Diagnostics)
	if !ok {
		return
	}
	groups, groupDiags := int64SetValues(ctx, plan.Groups)
	resp.Diagnostics.Append(groupDiags...)
	if resp.Diagnostics.HasError() {
		return
	}
	processingMode := plan.ProcessingMode.ValueString()
	if plan.ProcessingMode.IsNull() || plan.ProcessingMode.IsUnknown() {
		processingMode = "REGULAR"
	}
	var dataAccess *[]int64
	if !plan.DataAccessGroupIDs.IsNull() && !plan.DataAccessGroupIDs.IsUnknown() {
		ids, idDiags := int64SetValues(ctx, plan.DataAccessGroupIDs)
		resp.Diagnostics.Append(idDiags...)
		if resp.Diagnostics.HasError() {
			return
		}
		dataAccess = &ids
	}

	id, err := r.client.CreateCCPair(ctx, connectorID, credentialID, client.CCPairCreate{
		Name:            plan.Name.ValueString(),
		AccessType:      plan.AccessType.ValueString(),
		AutoSyncOptions: autoSyncOptions,
		Groups:          groups,
		DataAccess:      dataAccess,
		ProcessingMode:  processingMode,
	})
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx connector-credential pair", err.Error())
		r.warnIfConnectorWasRolledBack(ctx, connectorID, &resp.Diagnostics)
		return
	}

	// The pair starts unpaused; pause it as a follow-up when asked. A failure
	// here is reported after the read below, so state still describes the pair
	// that now exists rather than the one that was planned.
	var pauseErr error
	if plan.Paused.ValueBool() {
		pauseErr = r.client.SetCCPairStatus(ctx, id, client.CCPairStatusPaused)
	}

	remote, err := r.client.GetCCPair(ctx, id)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read back the new Onyx connector-credential pair", err.Error())
		// Persist the id so the next apply updates instead of creating a duplicate.
		plan.ID = types.StringValue(strconv.FormatInt(id, 10))
		plan.ensureComputedKnown()
		resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
		return
	}
	applyRemoteCCPair(ctx, &plan, remote, &resp.Diagnostics)
	r.refreshDataAccess(ctx, id, &plan, true, &resp.Diagnostics)
	if pauseErr != nil {
		resp.Diagnostics.AddError("Failed to pause the new Onyx connector-credential pair", pauseErr.Error())
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

// warnIfConnectorWasRolledBack reports the endpoint's destructive rollback.
// An IntegrityError on the insert makes the handler delete the whole connector
// before answering, so an onyx_connector resource that applied a moment ago now
// points at nothing. The pair's key is (connector_id, credential_id) and the
// handler pre-checks it, so in practice this needs a concurrent create of the
// same pair to slip past that check.
func (r *ccPairResource) warnIfConnectorWasRolledBack(ctx context.Context, connectorID int64, diags *diag.Diagnostics) {
	if _, err := r.client.GetConnector(ctx, connectorID); !client.IsNotFound(err) {
		return
	}
	diags.AddError(
		"Onyx deleted the connector while rejecting the pair",
		fmt.Sprintf("Connector %d no longer exists. Onyx deletes the connector when the pair cannot "+
			"be inserted, so the onyx_connector resource in state is now stale.\n\n"+
			"This usually means something created the same pair at the same time. Run "+
			"`terraform apply` again — Terraform recreates the connector, because it can no longer "+
			"read it, and then retries the pair.", connectorID),
	)
}

func (r *ccPairResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state ccPairResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "connector-credential pair", &resp.Diagnostics)
	if !ok {
		return
	}

	remote, err := r.client.GetCCPair(ctx, id)
	if client.IsNotFound(err) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx connector-credential pair", err.Error())
		return
	}
	// A pair stuck in DELETING stays in state on purpose. A failed deletion
	// never leaves that status, and dropping it here would hide a pair that
	// still exists and still holds its (connector, credential) key.
	applyRemoteCCPair(ctx, &state, remote, &resp.Diagnostics)
	r.refreshDataAccess(ctx, id, &state, false, &resp.Diagnostics)
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *ccPairResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state ccPairResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "connector-credential pair", &resp.Diagnostics)
	if !ok {
		return
	}

	// Name, status and data access have separate endpoints; everything else
	// replaces.
	if !plan.Name.Equal(state.Name) {
		if err := r.client.SetCCPairName(ctx, id, plan.Name.ValueString()); err != nil {
			resp.Diagnostics.AddError("Failed to rename Onyx connector-credential pair", err.Error())
			return
		}
	}
	if !plan.Paused.Equal(state.Paused) {
		status := client.CCPairStatusActive
		if plan.Paused.ValueBool() {
			status = client.CCPairStatusPaused
		}
		if err := r.client.SetCCPairStatus(ctx, id, status); err != nil {
			resp.Diagnostics.AddError("Failed to change Onyx connector-credential pair status", err.Error())
			return
		}
	}

	if !plan.DataAccessGroupIDs.IsNull() && !plan.DataAccessGroupIDs.Equal(state.DataAccessGroupIDs) {
		groupIDs, idDiags := int64SetValues(ctx, plan.DataAccessGroupIDs)
		resp.Diagnostics.Append(idDiags...)
		if resp.Diagnostics.HasError() {
			return
		}
		if _, err := r.client.SetCCPairDataAccess(ctx, id, groupIDs); err != nil {
			resp.Diagnostics.AddError("Failed to set the data-access groups of the Onyx connector-credential pair", err.Error())
			return
		}
	}

	remote, err := r.client.GetCCPair(ctx, id)
	if err != nil {
		resp.Diagnostics.AddError("Failed to read back the Onyx connector-credential pair", err.Error())
		return
	}
	applyRemoteCCPair(ctx, &plan, remote, &resp.Diagnostics)
	r.refreshDataAccess(ctx, id, &plan, !plan.DataAccessGroupIDs.Equal(state.DataAccessGroupIDs), &resp.Diagnostics)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *ccPairResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state ccPairResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "connector-credential pair", &resp.Diagnostics)
	if !ok {
		return
	}
	connectorID, ok := parseID(state.ConnectorID, "connector", &resp.Diagnostics)
	if !ok {
		return
	}
	credentialID, ok := parseID(state.CredentialID, "credential", &resp.Diagnostics)
	if !ok {
		return
	}
	deleteTimeout, timeoutDiags := state.Timeouts.Delete(ctx, defaultCCPairDeleteTimeout)
	resp.Diagnostics.Append(timeoutDiags...)
	if resp.Diagnostics.HasError() {
		return
	}

	err := r.client.DeleteCCPair(ctx, connectorID, credentialID)
	if client.IsNotFound(err) {
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to delete Onyx connector-credential pair", err.Error())
		return
	}

	// Deletion only schedules background work, so wait for the row to go.
	// Returning early would let the connector's own delete fail while a pair
	// still references it, and a replacement pair would answer "already
	// associated" — the pair's key is (connector_id, credential_id).
	err = client.Poll(ctx, deleteTimeout, "the connector-credential pair to be deleted",
		func(ctx context.Context) (bool, string, error) {
			remote, err := r.client.GetCCPair(ctx, id)
			if client.IsNotFound(err) {
				return true, "", nil
			}
			if err != nil {
				return false, "", err
			}
			if remote.DeletionFailureMessage != nil && *remote.DeletionFailureMessage != "" {
				return false, "", fmt.Errorf("onyx could not delete the pair: %s", *remote.DeletionFailureMessage)
			}
			return false, fmt.Sprintf("status is %s with %d documents left",
				remote.Status, remote.NumDocsIndexed), nil
		})
	if err != nil {
		resp.Diagnostics.AddError("Failed to delete Onyx connector-credential pair", err.Error())
	}
}

func (r *ccPairResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}

// ensureComputedKnown replaces a still-unknown computed value with null, so a
// failed read-back does not also report provider bugs for unknown state.
func (m *ccPairResourceModel) ensureComputedKnown() {
	if m.Groups.IsUnknown() {
		m.Groups = types.SetNull(types.Int64Type)
	}
	if m.AutoSyncOptions.IsUnknown() {
		m.AutoSyncOptions = jsontypes.NewNormalizedNull()
	}
	if m.ProcessingMode.IsUnknown() {
		m.ProcessingMode = types.StringNull()
	}
	if m.Status.IsUnknown() {
		m.Status = types.StringNull()
	}
	if m.NumDocsIndexed.IsUnknown() {
		m.NumDocsIndexed = types.Int64Null()
	}
	if m.LastIndexAttemptStatus.IsUnknown() {
		m.LastIndexAttemptStatus = types.StringNull()
	}
}
