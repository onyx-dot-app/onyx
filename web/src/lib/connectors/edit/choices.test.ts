import {
  applyBlockOf,
  buildApplyRequest,
  canAddStep,
  initialChoices,
} from "@/lib/connectors/edit/choices";
import type {
  ConnectorEditPlanResponse,
  EditPlan,
  EditStep,
} from "@/lib/connectors/edit/types";

function step(overrides: Partial<EditStep>): EditStep {
  return {
    kind: "full_reindex",
    required: false,
    reasons: ["behavior_changed"],
    field_names: [],
    backfill: null,
    ...overrides,
  };
}

function planResponse(
  plan: Partial<EditPlan>,
  validationBlocksApply = false
): ConnectorEditPlanResponse {
  return {
    plan_id: "plan-1",
    cc_pair_id: 3,
    created_at: "2026-10-06T00:00:00Z",
    expires_at: "2026-10-07T00:00:00Z",
    validation_blocks_apply: validationBlocksApply,
    plan: {
      field_changes: [],
      changed_settings: [],
      steps: [],
      reconciliation_choice: null,
      credential_choice: null,
      notes: [],
      validation: null,
      dry_run_results: [],
      indexed_document_count: 10,
      ...plan,
    },
  };
}

describe("buildApplyRequest", () => {
  it("requires the reconciliation choice and sends it", () => {
    const response = planResponse({
      reconciliation_choice: {
        field_names: ["cql_query"],
        options: ["prune", "full_reindex", "both", "nothing"],
      },
    });
    const choices = initialChoices(response.plan);

    expect(applyBlockOf(response, choices)).toBe("reconciliation");

    const chosen = { ...choices, reconciliation: "both" as const };
    expect(applyBlockOf(response, chosen)).toBeNull();
    expect(buildApplyRequest(response, chosen)).toEqual({
      plan_id: "plan-1",
      reconciliation: "both",
      credential_path: null,
      added_steps: [],
      dropped_steps: [],
    });
  });

  it("sends the credential path, the plan's default when untouched", () => {
    const response = planResponse({
      credential_choice: {
        default: "keep_indexed",
        options: ["keep_indexed", "full_reindex_and_prune"],
      },
    });
    const choices = initialChoices(response.plan);

    expect(buildApplyRequest(response, choices).credential_path).toBe(
      "keep_indexed"
    );
    expect(
      buildApplyRequest(response, {
        ...choices,
        credentialPath: "full_reindex_and_prune",
      }).credential_path
    ).toBe("full_reindex_and_prune");
  });

  it("drops only optional plan steps and adds only uncovered steps", () => {
    const response = planResponse({
      steps: [
        step({ kind: "restart_attempt", required: true }),
        step({ kind: "full_reindex", required: false }),
      ],
    });
    const choices = {
      ...initialChoices(response.plan),
      droppedSteps: ["restart_attempt" as const, "full_reindex" as const],
      addFullReindex: false,
      addPrune: true,
    };

    expect(buildApplyRequest(response, choices)).toMatchObject({
      dropped_steps: ["full_reindex"],
      added_steps: ["prune"],
    });
  });

  it("does not add a step that a kept plan step covers", () => {
    const response = planResponse({
      steps: [step({ kind: "full_reindex_then_prune", required: true })],
    });
    const choices = {
      ...initialChoices(response.plan),
      addFullReindex: true,
      addPrune: true,
    };

    expect(canAddStep(response.plan, choices, "full_reindex")).toBe(false);
    expect(canAddStep(response.plan, choices, "prune")).toBe(false);
    expect(buildApplyRequest(response, choices).added_steps).toEqual([]);
  });

  it("blocks apply when validation fails", () => {
    const response = planResponse({}, true);

    expect(applyBlockOf(response, initialChoices(response.plan))).toBe(
      "validation"
    );
  });
});
