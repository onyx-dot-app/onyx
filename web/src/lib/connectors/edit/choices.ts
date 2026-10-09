import type {
  AddableEditStepKind,
  ConnectorEditApplyRequest,
  ConnectorEditPlanResponse,
  CredentialPath,
  EditPlan,
  EditStep,
  EditStepKind,
  ReconciliationOption,
} from "@/lib/connectors/edit/types";

/** The admin's answers to a plan, as the plan preview holds them. */
export interface EditPlanChoices {
  /** Required when the plan has a reconciliation choice. */
  reconciliation: ReconciliationOption | null;
  credentialPath: CredentialPath | null;
  /** Optional plan steps the admin does not want. */
  droppedSteps: EditStepKind[];
  addFullReindex: boolean;
  addPrune: boolean;
}

export type ExtraStep = "full_reindex" | "prune";

export function initialChoices(plan: EditPlan): EditPlanChoices {
  return {
    reconciliation: null,
    credentialPath: plan.credential_choice?.default ?? null,
    droppedSteps: [],
    addFullReindex: false,
    addPrune: false,
  };
}

// A full re-index then prune covers both a re-index and a prune.
const COVERED_BY: Record<ExtraStep, EditStepKind[]> = {
  full_reindex: ["full_reindex", "full_reindex_then_prune"],
  prune: ["prune", "full_reindex_then_prune"],
};

function keptSteps(plan: EditPlan, choices: EditPlanChoices): EditStep[] {
  return plan.steps.filter(
    (step) => step.required || !choices.droppedSteps.includes(step.kind)
  );
}

/** Whether the admin can add the step: no kept plan step covers it. */
export function canAddStep(
  plan: EditPlan,
  choices: EditPlanChoices,
  extra: ExtraStep
): boolean {
  return !keptSteps(plan, choices).some((step) =>
    COVERED_BY[extra].includes(step.kind)
  );
}

export type ApplyBlock = "validation" | "reconciliation";

/** Why Apply is disabled, or null when the plan can be applied. */
export function applyBlockOf(
  planResponse: ConnectorEditPlanResponse,
  choices: EditPlanChoices
): ApplyBlock | null {
  if (planResponse.validation_blocks_apply) return "validation";
  if (
    planResponse.plan.reconciliation_choice !== null &&
    choices.reconciliation === null
  ) {
    return "reconciliation";
  }
  return null;
}

/** The apply request for the admin's choices. */
export function buildApplyRequest(
  planResponse: ConnectorEditPlanResponse,
  choices: EditPlanChoices
): ConnectorEditApplyRequest {
  const { plan } = planResponse;
  const addedSteps: AddableEditStepKind[] = [];
  if (choices.addFullReindex && canAddStep(plan, choices, "full_reindex")) {
    addedSteps.push("full_reindex");
  }
  if (choices.addPrune && canAddStep(plan, choices, "prune")) {
    addedSteps.push("prune");
  }
  return {
    plan_id: planResponse.plan_id,
    reconciliation:
      plan.reconciliation_choice === null ? null : choices.reconciliation,
    credential_path:
      plan.credential_choice === null
        ? null
        : (choices.credentialPath ?? plan.credential_choice.default),
    added_steps: addedSteps,
    dropped_steps: plan.steps
      .filter(
        (step) => !step.required && choices.droppedSteps.includes(step.kind)
      )
      .map((step) => step.kind),
  };
}
