package provider

import (
	"context"
	"strconv"

	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/onyx-dot-app/onyx/terraform-provider-onyx/internal/client"
)

var (
	_ resource.Resource                = (*agentLabelResource)(nil)
	_ resource.ResourceWithConfigure   = (*agentLabelResource)(nil)
	_ resource.ResourceWithImportState = (*agentLabelResource)(nil)
)

// NewAgentLabelResource returns the onyx_agent_label resource.
func NewAgentLabelResource() resource.Resource {
	return &agentLabelResource{}
}

type agentLabelResource struct {
	client *client.Client
}

type agentLabelResourceModel struct {
	ID   types.String `tfsdk:"id"`
	Name types.String `tfsdk:"name"`
}

func (r *agentLabelResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_agent_label"
}

func (r *agentLabelResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "A label that groups agents in the agent list. Reference its `id` from " +
			"`onyx_agent.label_ids`. Deleting a label removes it from every agent. Any user can " +
			"create a label, but rename and delete need full admin access, so manage labels with " +
			"an admin API key. Import with the numeric label id.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "Numeric label id.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"name": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "Label name. Names are unique. A change renames the label in place.",
				Validators: []validator.String{
					stringvalidator.LengthAtLeast(1),
				},
			},
		},
	}
}

func (r *agentLabelResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	r.client = clientFromResourceConfigure(req, resp)
}

func (r *agentLabelResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan agentLabelResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	label, err := r.client.CreateAgentLabel(ctx, plan.Name.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Failed to create Onyx agent label", err.Error())
		return
	}

	plan.ID = types.StringValue(strconv.FormatInt(label.ID, 10))
	plan.Name = types.StringValue(label.Name)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *agentLabelResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state agentLabelResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "agent label", &resp.Diagnostics)
	if !ok {
		return
	}

	label, err := r.client.GetAgentLabel(ctx, id)
	if client.IsNotFound(err) {
		resp.State.RemoveResource(ctx)
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Failed to read Onyx agent label", err.Error())
		return
	}

	state.Name = types.StringValue(label.Name)
	resp.Diagnostics.Append(resp.State.Set(ctx, state)...)
}

func (r *agentLabelResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan, state agentLabelResourceModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "agent label", &resp.Diagnostics)
	if !ok {
		return
	}

	if err := r.client.RenameAgentLabel(ctx, id, plan.Name.ValueString()); err != nil {
		resp.Diagnostics.AddError("Failed to rename Onyx agent label", err.Error())
		return
	}

	plan.ID = state.ID
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}

func (r *agentLabelResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state agentLabelResourceModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	id, ok := parseID(state.ID, "agent label", &resp.Diagnostics)
	if !ok {
		return
	}

	if err := r.client.DeleteAgentLabel(ctx, id); err != nil && !client.IsNotFound(err) {
		resp.Diagnostics.AddError("Failed to delete Onyx agent label", err.Error())
	}
}

func (r *agentLabelResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
