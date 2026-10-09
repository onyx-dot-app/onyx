"""The admin's choices on a connector edit plan: opaque scope changes need a
reconciliation choice, a credential change takes a path, more work can always
be added, and only steps that are not required can be dropped."""

from datetime import datetime, timezone

import pytest

from onyx.background.indexing.models import BackfillSpec
from onyx.connectors.edit_plan.models import (
    CredentialChoice,
    CredentialPath,
    EditPlan,
    EditPlanChoices,
    EditStep,
    EditStepKind,
    EditStepReason,
    ReconciliationChoice,
    ReconciliationOption,
)
from onyx.connectors.edit_plan.overrides import resolve_edit_steps
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_BACKFILL = BackfillSpec(
    window_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
    window_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
    connector_config_override={"channels": ["b"]},
)


def _step(kind: EditStepKind, *, required: bool = False) -> EditStep:
    return EditStep(
        kind=kind,
        required=required,
        reasons=[EditStepReason.SCOPE_WIDENED],
        backfill=_BACKFILL if kind == EditStepKind.SCOPED_BACKFILL else None,
    )


def _plan(
    *steps: EditStep,
    reconciliation: bool = False,
    credential_changed: bool = False,
) -> EditPlan:
    return EditPlan(
        field_changes=[],
        changed_settings=[],
        steps=list(steps),
        reconciliation_choice=(
            ReconciliationChoice(field_names=["cql_query"]) if reconciliation else None
        ),
        credential_choice=CredentialChoice() if credential_changed else None,
        notes=[],
        dry_run_results=[],
        indexed_document_count=0,
    )


def _kinds(steps: list[EditStep]) -> list[EditStepKind]:
    return [step.kind for step in steps]


def _invalid(plan: EditPlan, choices: EditPlanChoices) -> None:
    with pytest.raises(OnyxError) as exc:
        resolve_edit_steps(plan, choices)
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_no_choices_keep_the_plan() -> None:
    plan = _plan(_step(EditStepKind.SCOPED_BACKFILL), _step(EditStepKind.PRUNE))

    assert resolve_edit_steps(plan, EditPlanChoices()) == plan.steps


@pytest.mark.parametrize(
    "option, expected",
    [
        (ReconciliationOption.PRUNE, [EditStepKind.PRUNE]),
        (ReconciliationOption.FULL_REINDEX, [EditStepKind.FULL_REINDEX]),
        (ReconciliationOption.BOTH, [EditStepKind.FULL_REINDEX_THEN_PRUNE]),
        (ReconciliationOption.NOTHING, []),
    ],
)
def test_reconciliation_options(
    option: ReconciliationOption, expected: list[EditStepKind]
) -> None:
    steps = resolve_edit_steps(
        _plan(reconciliation=True), EditPlanChoices(reconciliation=option)
    )

    assert _kinds(steps) == expected
    assert all(step.field_names == ["cql_query"] for step in steps)


def test_reconciliation_choice_is_required() -> None:
    _invalid(_plan(reconciliation=True), EditPlanChoices())


def test_reconciliation_choice_without_an_opaque_change_is_rejected() -> None:
    _invalid(_plan(), EditPlanChoices(reconciliation=ReconciliationOption.PRUNE))


def test_reconciliation_reindex_subsumes_a_backfill() -> None:
    plan = _plan(_step(EditStepKind.SCOPED_BACKFILL), reconciliation=True)
    steps = resolve_edit_steps(
        plan, EditPlanChoices(reconciliation=ReconciliationOption.FULL_REINDEX)
    )

    assert _kinds(steps) == [EditStepKind.FULL_REINDEX]
    assert steps[0].reasons == [
        EditStepReason.OPAQUE_SCOPE_CHOICE,
        EditStepReason.SCOPE_WIDENED,
    ]


@pytest.mark.parametrize(
    "path, expected",
    [
        (None, []),
        (CredentialPath.KEEP_INDEXED, []),
        (CredentialPath.FULL_REINDEX_AND_PRUNE, [EditStepKind.FULL_REINDEX_THEN_PRUNE]),
    ],
)
def test_credential_paths(
    path: CredentialPath | None, expected: list[EditStepKind]
) -> None:
    steps = resolve_edit_steps(
        _plan(credential_changed=True), EditPlanChoices(credential_path=path)
    )

    assert _kinds(steps) == expected


def test_credential_path_without_a_credential_change_is_rejected() -> None:
    _invalid(_plan(), EditPlanChoices(credential_path=CredentialPath.KEEP_INDEXED))


def test_skippable_step_can_be_dropped() -> None:
    plan = _plan(
        _step(EditStepKind.ACCESS_TYPE, required=True),
        _step(EditStepKind.PRUNE),
    )
    steps = resolve_edit_steps(
        plan, EditPlanChoices(dropped_steps=[EditStepKind.PRUNE])
    )

    assert _kinds(steps) == [EditStepKind.ACCESS_TYPE]


def test_required_step_cannot_be_dropped() -> None:
    plan = _plan(_step(EditStepKind.ENTER_PERM_SYNC, required=True))

    _invalid(plan, EditPlanChoices(dropped_steps=[EditStepKind.ENTER_PERM_SYNC]))


def test_absent_step_cannot_be_dropped() -> None:
    _invalid(_plan(), EditPlanChoices(dropped_steps=[EditStepKind.PRUNE]))


def test_step_from_a_choice_can_be_dropped() -> None:
    steps = resolve_edit_steps(
        _plan(reconciliation=True),
        EditPlanChoices(
            reconciliation=ReconciliationOption.PRUNE,
            dropped_steps=[EditStepKind.PRUNE],
        ),
    )

    assert steps == []


def test_added_reindex_subsumes_a_backfill() -> None:
    plan = _plan(_step(EditStepKind.SCOPED_BACKFILL))
    steps = resolve_edit_steps(
        plan, EditPlanChoices(added_steps=[EditStepKind.FULL_REINDEX])
    )

    assert _kinds(steps) == [EditStepKind.FULL_REINDEX]
    assert steps[0].backfill is None
    assert steps[0].reasons == [
        EditStepReason.ADMIN_ADDED,
        EditStepReason.SCOPE_WIDENED,
    ]


def test_added_prune_merges_with_a_reindex() -> None:
    plan = _plan(_step(EditStepKind.FULL_REINDEX))
    steps = resolve_edit_steps(plan, EditPlanChoices(added_steps=[EditStepKind.PRUNE]))

    assert _kinds(steps) == [EditStepKind.FULL_REINDEX_THEN_PRUNE]
    assert not steps[0].required


def test_added_prune_stays_apart_from_a_required_reindex() -> None:
    plan = _plan(_step(EditStepKind.FULL_REINDEX, required=True))
    steps = resolve_edit_steps(plan, EditPlanChoices(added_steps=[EditStepKind.PRUNE]))

    assert _kinds(steps) == [EditStepKind.FULL_REINDEX, EditStepKind.PRUNE]
    assert [step.required for step in steps] == [True, False]


def test_choices_the_plan_does_not_offer_are_rejected() -> None:
    plan = _plan(credential_changed=True)
    assert plan.credential_choice is not None
    plan.credential_choice.options = [CredentialPath.KEEP_INDEXED]
    _invalid(
        plan, EditPlanChoices(credential_path=CredentialPath.FULL_REINDEX_AND_PRUNE)
    )

    plan = _plan(reconciliation=True)
    assert plan.reconciliation_choice is not None
    plan.reconciliation_choice.options = [ReconciliationOption.FULL_REINDEX]
    _invalid(plan, EditPlanChoices(reconciliation=ReconciliationOption.NOTHING))


@pytest.mark.parametrize(
    "kind",
    [
        EditStepKind.SCOPED_BACKFILL,
        EditStepKind.WINDOW_BACKFILL,
        EditStepKind.RESTART_ATTEMPT,
        EditStepKind.ACCESS_TYPE,
    ],
)
def test_steps_that_cannot_be_added(kind: EditStepKind) -> None:
    _invalid(_plan(), EditPlanChoices(added_steps=[kind]))


def test_drop_then_add_keeps_the_reindex_without_the_prune() -> None:
    plan = _plan(_step(EditStepKind.FULL_REINDEX_THEN_PRUNE))
    steps = resolve_edit_steps(
        plan,
        EditPlanChoices(
            dropped_steps=[EditStepKind.FULL_REINDEX_THEN_PRUNE],
            added_steps=[EditStepKind.FULL_REINDEX],
        ),
    )

    assert _kinds(steps) == [EditStepKind.FULL_REINDEX]
