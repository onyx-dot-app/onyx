"""Applies an admin's choices to an edit plan. The admin may always add work,
and may drop only steps that are not required."""

from onyx.connectors.edit_plan.models import (
    CredentialPath,
    EditPlan,
    EditPlanChoices,
    EditStep,
    EditStepKind,
    EditStepReason,
    ReconciliationOption,
)
from onyx.connectors.edit_plan.planner import normalize_steps
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

# Steps an admin can add. Backfills need a window, and access and restart
# steps follow from the proposed state.
ADDABLE_STEP_KINDS = frozenset(
    {
        EditStepKind.FULL_REINDEX,
        EditStepKind.FULL_REINDEX_THEN_PRUNE,
        EditStepKind.PRUNE,
    }
)

_RECONCILIATION_STEP_KINDS: dict[ReconciliationOption, list[EditStepKind]] = {
    ReconciliationOption.PRUNE: [EditStepKind.PRUNE],
    ReconciliationOption.FULL_REINDEX: [EditStepKind.FULL_REINDEX],
    ReconciliationOption.BOTH: [EditStepKind.FULL_REINDEX_THEN_PRUNE],
    ReconciliationOption.NOTHING: [],
}


def _invalid(message: str) -> OnyxError:
    return OnyxError(OnyxErrorCode.INVALID_INPUT, message)


def _choice_steps(plan: EditPlan, choices: EditPlanChoices) -> list[EditStep]:
    steps: list[EditStep] = []

    if plan.reconciliation_choice is None:
        if choices.reconciliation is not None:
            raise _invalid("This edit has no scope change to reconcile.")
    else:
        if choices.reconciliation is None:
            raise _invalid(
                "Choose how to reconcile the changes to "
                f"{', '.join(plan.reconciliation_choice.field_names)}."
            )
        steps.extend(
            EditStep(
                kind=kind,
                required=False,
                reasons=[EditStepReason.OPAQUE_SCOPE_CHOICE],
                field_names=plan.reconciliation_choice.field_names,
            )
            for kind in _RECONCILIATION_STEP_KINDS[choices.reconciliation]
        )

    if plan.credential_choice is None:
        if choices.credential_path is not None:
            raise _invalid("This edit does not change the credential.")
    elif (
        choices.credential_path or plan.credential_choice.default
    ) == CredentialPath.FULL_REINDEX_AND_PRUNE:
        steps.append(
            EditStep(
                kind=EditStepKind.FULL_REINDEX_THEN_PRUNE,
                required=False,
                reasons=[EditStepReason.CREDENTIAL_FULL_PATH],
            )
        )
    return steps


def resolve_edit_steps(plan: EditPlan, choices: EditPlanChoices) -> list[EditStep]:
    """The steps apply runs: the plan's steps with the steps of the admin's
    choices, without the dropped steps, then with the added steps.

    Drops apply to the merged steps the admin sees. Dropping a step also drops
    the work it covers (e.g. a full re-index covers a backfill).

    Raises:
        OnyxError: INVALID_INPUT for a missing reconciliation choice, a choice
            the plan does not offer, a drop of a required or absent step, or an
            added step that cannot be added.
    """
    steps = normalize_steps([*plan.steps, *_choice_steps(plan, choices)])

    dropped_kinds = set(choices.dropped_steps)
    present_kinds = {step.kind for step in steps}
    if absent_kinds := dropped_kinds - present_kinds:
        raise _invalid(
            "The plan has no step to drop: "
            f"{', '.join(sorted(kind.value for kind in absent_kinds))}."
        )
    if required_kinds := [
        step.kind.value
        for step in steps
        if step.kind in dropped_kinds and step.required
    ]:
        raise _invalid(
            f"Required steps cannot be dropped: {', '.join(required_kinds)}."
        )

    if not_addable := set(choices.added_steps) - ADDABLE_STEP_KINDS:
        raise _invalid(
            "These steps cannot be added: "
            f"{', '.join(sorted(kind.value for kind in not_addable))}."
        )
    kept_steps = [step for step in steps if step.kind not in dropped_kinds]
    added_steps = [
        EditStep(kind=kind, required=False, reasons=[EditStepReason.ADMIN_ADDED])
        for kind in choices.added_steps
    ]
    return normalize_steps([*kept_steps, *added_steps])
