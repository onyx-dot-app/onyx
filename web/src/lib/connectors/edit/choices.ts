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

// Mirrors `normalize_steps` in `onyx/connectors/edit_plan/planner.py`.
const STEP_ORDER: EditStepKind[] = [
  "access_groups",
  "access_type",
  "enter_perm_sync",
  "leave_perm_sync",
  "restart_attempt",
  "full_reindex_then_prune",
  "full_reindex",
  "scoped_backfill",
  "window_backfill",
  "prune",
];
const SUBSUMES: [EditStepKind, EditStepKind[]][] = [
  [
    "full_reindex_then_prune",
    ["full_reindex", "scoped_backfill", "window_backfill", "prune"],
  ],
  ["full_reindex", ["scoped_backfill", "window_backfill"]],
];
const RECONCILIATION_STEP_KINDS: Record<ReconciliationOption, EditStepKind[]> =
  {
    prune: ["prune"],
    full_reindex: ["full_reindex"],
    both: ["full_reindex_then_prune"],
    nothing: [],
  };

function mergeInto(kind: EditStepKind, steps: EditStep[]): EditStep {
  return {
    kind,
    required: steps.some((step) => step.required),
    reasons: [...new Set(steps.flatMap((step) => step.reasons))],
    field_names: [...new Set(steps.flatMap((step) => step.field_names))],
    backfill:
      steps.find((step) => step.kind === kind && step.backfill !== null)
        ?.backfill ?? null,
  };
}

/** Merges duplicate kinds and folds each step into the step that covers it. */
export function normalizeSteps(steps: EditStep[]): EditStep[] {
  const byKind = new Map<EditStepKind, EditStep[]>();
  for (const step of steps) {
    byKind.set(step.kind, [...(byKind.get(step.kind) ?? []), step]);
  }
  // A re-index and a prune merge only when both are required or both are not.
  const reindex = byKind.get("full_reindex");
  const prune = byKind.get("prune");
  if (
    reindex &&
    prune &&
    reindex.some((step) => step.required) ===
      prune.some((step) => step.required)
  ) {
    byKind.set(
      "full_reindex_then_prune",
      byKind.get("full_reindex_then_prune") ?? []
    );
  }
  for (const [kind, subsumed] of SUBSUMES) {
    const kindSteps = byKind.get(kind);
    if (!kindSteps) continue;
    for (const subsumedKind of subsumed) {
      kindSteps.push(...(byKind.get(subsumedKind) ?? []));
      byKind.delete(subsumedKind);
    }
  }
  return STEP_ORDER.flatMap((kind) => {
    const kindSteps = byKind.get(kind);
    return kindSteps && kindSteps.length > 0
      ? [mergeInto(kind, kindSteps)]
      : [];
  });
}

function choiceSteps(plan: EditPlan, choices: EditPlanChoices): EditStep[] {
  const steps: EditStep[] = [];
  const reconciliation = plan.reconciliation_choice;
  if (reconciliation !== null && choices.reconciliation !== null) {
    steps.push(
      ...RECONCILIATION_STEP_KINDS[choices.reconciliation].map((kind) => ({
        kind,
        required: false,
        reasons: ["opaque_scope_choice" as const],
        field_names: reconciliation.field_names,
        backfill: null,
      }))
    );
  }
  if (
    plan.credential_choice !== null &&
    (choices.credentialPath ?? plan.credential_choice.default) ===
      "full_reindex_and_prune"
  ) {
    steps.push({
      kind: "full_reindex_then_prune",
      required: false,
      reasons: ["credential_full_path"],
      field_names: [],
      backfill: null,
    });
  }
  return steps;
}

/**
 * The plan's steps merged with the steps of the admin's choices, as apply
 * resolves them. Drops apply to these steps.
 */
export function resolvedSteps(
  plan: EditPlan,
  choices: EditPlanChoices
): EditStep[] {
  return normalizeSteps([...plan.steps, ...choiceSteps(plan, choices)]);
}

function keptSteps(plan: EditPlan, choices: EditPlanChoices): EditStep[] {
  return resolvedSteps(plan, choices).filter(
    (step) => step.required || !choices.droppedSteps.includes(step.kind)
  );
}

/** Whether the admin can add the step: no kept step covers it. */
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
    dropped_steps: resolvedSteps(plan, choices)
      .filter(
        (step) => !step.required && choices.droppedSteps.includes(step.kind)
      )
      .map((step) => step.kind),
  };
}
