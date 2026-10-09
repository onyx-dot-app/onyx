"""Computes the plan for a connector edit: a pure function of the current and
proposed pair states and of inputs the caller gathers (pair status, source
capabilities, validation results). It decides which propagation steps the edit
needs; it reads and writes nothing.

Each config field change maps to steps by its field class (see
``field_policy``), unless the source's planning rule decides the steps for
that field (``RuleSteps``). The planner then merges the steps so that a full re-index
replaces the backfills and a re-index followed by a prune replaces a plain
prune.
"""

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from onyx.background.indexing.models import BackfillSpec
from onyx.connectors.capability_checks.models import CapabilityCheckStatus
from onyx.connectors.config_diff import (
    ConfigFieldChange,
    build_source_scoped_backfill_config,
    classify_source_config_change,
    source_change_override,
)
from onyx.connectors.edit_plan.models import (
    CredentialChoice,
    CurrentPairState,
    EditNote,
    EditNoteKind,
    EditNoteSeverity,
    EditPlan,
    EditPlanInputs,
    EditStep,
    EditStepKind,
    EditStepReason,
    PairState,
    ProposedPairState,
    ReconciliationChoice,
)
from onyx.connectors.field_policy import FieldClass, ScopeDirection
from onyx.connectors.planning_rule import ConnectorChangeOverride, RuleSteps
from onyx.connectors.planning_rule_registry import (
    CREDENTIAL_SWAP_FULL_PATH_SOURCES,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_NAME_SETTING = "name"
_REFRESH_FREQ_SETTING = "refresh_freq"
_PRUNE_FREQ_SETTING = "prune_freq"

_STEP_ORDER: tuple[EditStepKind, ...] = (
    EditStepKind.ACCESS_GROUPS,
    EditStepKind.ACCESS_TYPE,
    EditStepKind.ENTER_PERM_SYNC,
    EditStepKind.LEAVE_PERM_SYNC,
    EditStepKind.RESTART_ATTEMPT,
    EditStepKind.FULL_REINDEX_THEN_PRUNE,
    EditStepKind.FULL_REINDEX,
    EditStepKind.SCOPED_BACKFILL,
    EditStepKind.WINDOW_BACKFILL,
    EditStepKind.PRUNE,
)
_BACKFILL_KINDS = (EditStepKind.SCOPED_BACKFILL, EditStepKind.WINDOW_BACKFILL)
# Each kind replaces the kinds it maps to: its run covers their work. Tuples in
# apply order, so merged reasons have a stable order.
_SUBSUMES: dict[EditStepKind, tuple[EditStepKind, ...]] = {
    EditStepKind.FULL_REINDEX_THEN_PRUNE: (
        EditStepKind.FULL_REINDEX,
        *_BACKFILL_KINDS,
        EditStepKind.PRUNE,
    ),
    EditStepKind.FULL_REINDEX: _BACKFILL_KINDS,
}

_ATTEMPT_RESTARTED_MESSAGE = (
    "An index attempt runs with the current settings. It stops, and a new "
    "attempt starts with the new settings."
)
_PAUSED_MESSAGE = (
    "The connector is paused. Indexing steps run when it is resumed. Access "
    "changes apply at once."
)
_INVALID_MESSAGE = (
    "The connector is invalid. A successful validation of the new settings "
    "makes it active again."
)
_INDEXING_START_LATER_MESSAGE = (
    "The indexing start date is later. Documents older than the new date stay indexed."
)
_CREDENTIAL_FULL_PATH_MESSAGE = (
    "On this source, a new credential usually sees different content (for "
    "example a scoped token). A full re-index and prune is usually needed."
)
_ACCESS_AFTER_METADATA_SYNC_MESSAGE = (
    "The connector access filter is not enforced. The access change applies to "
    "search results only after the metadata sync of the connector's documents."
)
_STALE_SYNCED_ACLS_MESSAGE = (
    "The connector access filter is not enforced. The synced permissions stay "
    "on the documents and keep granting access until the filter is enforced."
)
_CHECKS_STILL_RUNNING_MESSAGE = (
    "Some checks did not finish in time. Run a dry run of the connector to see "
    "their results."
)
_UNFINISHED_CHECK_FAILED_MESSAGE = (
    "Some checks that did not finish in time failed in an earlier dry run: {}. "
    "Run a dry run again to see if they pass now."
)


def ensure_edit_is_plannable(
    current: CurrentPairState, proposed: ProposedPairState
) -> None:
    """Raises ``OnyxError`` for an edit no plan can carry out."""
    if current.status == ConnectorCredentialPairStatus.DELETING:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"Connector credential pair {current.cc_pair_id} is being deleted.",
        )
    if proposed.source != current.source:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "The source of a connector cannot change. Create a new connector.",
        )
    if proposed.input_type != current.input_type:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "The input type of a connector cannot change. Create a new connector.",
        )
    if (
        proposed.connector_specific_config != current.connector_specific_config
        and current.source not in CONNECTOR_CLASS_MAP
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{current.source.value} has no connector configuration to edit.",
        )


def _step(
    kind: EditStepKind,
    reason: EditStepReason,
    *,
    required: bool = False,
    field_names: Iterable[str] = (),
    backfill: BackfillSpec | None = None,
) -> EditStep:
    return EditStep(
        kind=kind,
        required=required,
        reasons=[reason],
        field_names=list(field_names),
        backfill=backfill,
    )


def _backfill_window(
    start: datetime | None,
    end: datetime,
    config_override: dict[str, Any] | None = None,
) -> BackfillSpec | None:
    """None when the window is empty, e.g. an indexing start in the future."""
    window_start = start or _EPOCH
    if window_start >= end:
        return None
    return BackfillSpec(
        window_start=window_start,
        window_end=end,
        connector_config_override=config_override,
    )


def _widen_steps(
    current: PairState,
    proposed: ProposedPairState,
    inputs: EditPlanInputs,
    override: ConnectorChangeOverride | None,
    field_names: list[str],
) -> list[EditStep]:
    """A backfill of only the added items over [indexing_start, now] when the
    source can run a window and the change has a delta config; otherwise a
    full re-index."""
    delta_config = (
        build_source_scoped_backfill_config(
            current.source,
            current.connector_specific_config,
            proposed.connector_specific_config,
            override,
        )
        if inputs.supports_windowed_runs
        else None
    )
    window = (
        _backfill_window(proposed.indexing_start, inputs.now, delta_config)
        if delta_config is not None
        else None
    )
    if window is None:
        return [
            _step(
                EditStepKind.FULL_REINDEX,
                EditStepReason.SCOPE_WIDENED,
                field_names=field_names,
            )
        ]
    return [
        _step(
            EditStepKind.SCOPED_BACKFILL,
            EditStepReason.SCOPE_WIDENED,
            field_names=field_names,
            backfill=window,
        )
    ]


def _field_change_steps(
    changes: list[ConfigFieldChange],
    current: PairState,
    proposed: ProposedPairState,
    inputs: EditPlanInputs,
    override: ConnectorChangeOverride | None,
) -> list[EditStep]:
    steps: list[EditStep] = []
    identity_fields: list[str] = []
    behavior_fields: list[str] = []
    widened_fields: list[str] = []
    narrowed_fields: list[str] = []
    for change in changes:
        if change.field_class == FieldClass.IDENTITY:
            identity_fields.append(change.field_name)
        elif change.field_class == FieldClass.BEHAVIOR:
            behavior_fields.append(change.field_name)
        elif change.field_class == FieldClass.SCOPE:
            if change.scope_direction in (ScopeDirection.WIDEN, ScopeDirection.BOTH):
                widened_fields.append(change.field_name)
            if change.scope_direction in (ScopeDirection.NARROW, ScopeDirection.BOTH):
                narrowed_fields.append(change.field_name)

    if identity_fields:
        steps.append(
            _step(
                EditStepKind.FULL_REINDEX_THEN_PRUNE,
                EditStepReason.IDENTITY_CHANGED,
                field_names=identity_fields,
            )
        )
    if behavior_fields:
        steps.append(
            _step(
                EditStepKind.FULL_REINDEX,
                EditStepReason.BEHAVIOR_CHANGED,
                field_names=behavior_fields,
            )
        )
    if widened_fields:
        steps.extend(_widen_steps(current, proposed, inputs, override, widened_fields))
    if narrowed_fields:
        steps.append(
            _step(
                EditStepKind.PRUNE,
                EditStepReason.SCOPE_NARROWED,
                field_names=narrowed_fields,
            )
        )
    return steps


def _rule_steps(
    rule_steps: RuleSteps,
    changes: list[ConfigFieldChange],
    proposed: ProposedPairState,
    inputs: EditPlanInputs,
) -> list[EditStep]:
    """The steps a planning rule decided for its fields. Its backfill config
    limits the run, so it does not need a source that fetches a window."""
    field_names = [
        change.field_name
        for change in changes
        if change.field_name in rule_steps.field_names
    ]
    steps: list[EditStep] = []
    if rule_steps.backfill_config is not None:
        # The config names what to index, so an empty window (e.g. an
        # indexing start in the future) runs over all time, not a re-index.
        window = _backfill_window(
            proposed.indexing_start, inputs.now, rule_steps.backfill_config
        ) or _backfill_window(None, inputs.now, rule_steps.backfill_config)
        steps.append(
            _step(
                EditStepKind.SCOPED_BACKFILL,
                EditStepReason.ITEMS_ADDED_OR_CHANGED,
                field_names=field_names,
                backfill=window,
            )
        )
    if rule_steps.prune:
        steps.append(
            _step(
                EditStepKind.PRUNE,
                EditStepReason.ITEMS_REMOVED,
                field_names=field_names,
            )
        )
    return steps


def _indexing_start_steps(
    current: PairState, proposed: ProposedPairState, inputs: EditPlanInputs
) -> tuple[list[EditStep], list[EditNote]]:
    old_start = current.indexing_start
    new_start = proposed.indexing_start
    if old_start == new_start:
        return [], []
    # No start means no floor, the earliest start there is.
    if old_start is None or (new_start is not None and new_start > old_start):
        return [], [
            EditNote(
                kind=EditNoteKind.INDEXING_START_LATER,
                severity=EditNoteSeverity.INFO,
                message=_INDEXING_START_LATER_MESSAGE,
            )
        ]
    window = (
        _backfill_window(new_start, min(old_start, inputs.now))
        if inputs.supports_windowed_runs
        else None
    )
    if window is None:
        return [
            _step(EditStepKind.FULL_REINDEX, EditStepReason.INDEXING_START_EARLIER)
        ], []
    return [
        _step(
            EditStepKind.WINDOW_BACKFILL,
            EditStepReason.INDEXING_START_EARLIER,
            backfill=window,
        )
    ], []


def _access_steps(
    current: PairState, proposed: ProposedPairState, inputs: EditPlanInputs
) -> tuple[list[EditStep], list[EditNote]]:
    """Access transitions as ``apply_access_change__no_commit`` carries them
    out. All are required: they decide who can read the documents."""
    old_type = current.access_type
    new_type = proposed.access_type
    if (
        old_type == new_type
        and current.data_access_group_ids == proposed.data_access_group_ids
    ):
        return [], []

    steps: list[EditStep] = []
    notes: list[EditNote] = []
    if old_type == new_type:
        kind = EditStepKind.ACCESS_GROUPS
    elif new_type.is_perm_synced() and not old_type.is_perm_synced():
        kind = EditStepKind.ENTER_PERM_SYNC
    elif old_type.is_perm_synced() and not new_type.is_perm_synced():
        kind = EditStepKind.LEAVE_PERM_SYNC
    else:
        kind = EditStepKind.ACCESS_TYPE
    steps.append(_step(kind, EditStepReason.ACCESS_CHANGED, required=True))

    # The pair hides its documents until they carry synced permissions, and
    # these sources get them only from a run from the beginning.
    if kind == EditStepKind.ENTER_PERM_SYNC and (
        inputs.fetches_permissions_during_indexing
    ):
        steps.append(
            _step(
                EditStepKind.FULL_REINDEX,
                EditStepReason.PERMISSIONS_FETCHED_DURING_INDEXING,
                required=True,
            )
        )

    if not inputs.access_filter_enforced:
        notes.append(
            EditNote(
                kind=EditNoteKind.ACCESS_AFTER_METADATA_SYNC,
                severity=EditNoteSeverity.WARNING,
                message=_ACCESS_AFTER_METADATA_SYNC_MESSAGE,
            )
        )
        if kind == EditStepKind.LEAVE_PERM_SYNC:
            notes.append(
                EditNote(
                    kind=EditNoteKind.STALE_SYNCED_ACLS,
                    severity=EditNoteSeverity.WARNING,
                    message=_STALE_SYNCED_ACLS_MESSAGE,
                )
            )
    return steps, notes


def _merge_into(kind: EditStepKind, steps: list[EditStep]) -> EditStep:
    """One step of ``kind`` that carries the work of ``steps``. Only a
    backfill kind keeps a window: a run from the beginning has none."""
    backfills = [
        step.backfill
        for step in steps
        if step.kind == kind and step.backfill is not None
    ]
    if any(backfill != backfills[0] for backfill in backfills):
        raise ValueError(f"Two {kind.value} steps have different windows.")
    return EditStep(
        kind=kind,
        required=any(step.required for step in steps),
        reasons=list(dict.fromkeys(r for step in steps for r in step.reasons)),
        field_names=list(
            dict.fromkeys(name for step in steps for name in step.field_names)
        ),
        backfill=backfills[0] if backfills else None,
    )


def normalize_steps(steps: list[EditStep]) -> list[EditStep]:
    """Merges duplicate kinds, folds subsumed steps into the step that covers
    them, and orders the steps for apply. A merged step is required if any of
    its parts is, and keeps all their reasons and fields."""
    by_kind: dict[EditStepKind, list[EditStep]] = {}
    for step in steps:
        by_kind.setdefault(step.kind, []).append(step)

    # A full re-index and a prune together are a re-index, then a prune. They
    # merge only when both are required or both are not, so a merged step
    # does not make optional work required.
    reindex_steps = by_kind.get(EditStepKind.FULL_REINDEX)
    prune_steps = by_kind.get(EditStepKind.PRUNE)
    if (
        reindex_steps
        and prune_steps
        and any(step.required for step in reindex_steps)
        == any(step.required for step in prune_steps)
    ):
        by_kind.setdefault(EditStepKind.FULL_REINDEX_THEN_PRUNE, [])
    for kind, subsumed_kinds in _SUBSUMES.items():
        if kind not in by_kind:
            continue
        for subsumed_kind in subsumed_kinds:
            by_kind[kind].extend(by_kind.pop(subsumed_kind, []))

    return [
        _merge_into(kind, kind_steps)
        for kind in _STEP_ORDER
        if (kind_steps := by_kind.get(kind))
    ]


def _state_notes(
    current: CurrentPairState, inputs: EditPlanInputs, restarts: bool
) -> list[EditNote]:
    notes: list[EditNote] = []
    if restarts:
        notes.append(
            EditNote(
                kind=EditNoteKind.ATTEMPT_RESTARTED,
                severity=EditNoteSeverity.INFO,
                message=_ATTEMPT_RESTARTED_MESSAGE,
            )
        )
    if current.status == ConnectorCredentialPairStatus.PAUSED:
        notes.append(
            EditNote(
                kind=EditNoteKind.PAUSED,
                severity=EditNoteSeverity.INFO,
                message=_PAUSED_MESSAGE,
            )
        )
    # Apply clears INVALID only through a validation that passes.
    validation = inputs.validation
    if (
        current.status == ConnectorCredentialPairStatus.INVALID
        and validation is not None
        and not validation.blocks_pairing
    ):
        notes.append(
            EditNote(
                kind=EditNoteKind.INVALID_CLEARED_BY_VALIDATION,
                severity=EditNoteSeverity.INFO,
                message=_INVALID_MESSAGE,
            )
        )
    if validation is not None and validation.unfinished_check_ids:
        notes.append(
            EditNote(
                kind=EditNoteKind.CHECKS_STILL_RUNNING,
                severity=EditNoteSeverity.INFO,
                message=_CHECKS_STILL_RUNNING_MESSAGE,
            )
        )
        failed_names: list[str] = [
            result.display_name
            for result in inputs.dry_run_results
            if result.check_id in validation.unfinished_check_ids
            and result.status == CapabilityCheckStatus.FAILED
        ]
        if failed_names:
            notes.append(
                EditNote(
                    kind=EditNoteKind.UNFINISHED_CHECK_FAILED_IN_DRY_RUN,
                    severity=EditNoteSeverity.WARNING,
                    message=_UNFINISHED_CHECK_FAILED_MESSAGE.format(
                        ", ".join(failed_names)
                    ),
                )
            )
    return notes


def _changed_settings(current: PairState, proposed: ProposedPairState) -> list[str]:
    settings = {
        _NAME_SETTING: (current.name, proposed.name),
        _REFRESH_FREQ_SETTING: (current.refresh_freq, proposed.refresh_freq),
        _PRUNE_FREQ_SETTING: (current.prune_freq, proposed.prune_freq),
    }
    return [name for name, (old, new) in settings.items() if old != new]


def compute_edit_plan(
    current: CurrentPairState, proposed: ProposedPairState, inputs: EditPlanInputs
) -> EditPlan:
    """The plan for moving the pair from ``current`` to ``proposed``.

    Raises:
        OnyxError: See ``ensure_edit_is_plannable``.
    """
    ensure_edit_is_plannable(current, proposed)

    config_changed: bool = (
        proposed.connector_specific_config != current.connector_specific_config
    )
    override: ConnectorChangeOverride | None = (
        source_change_override(
            current.source,
            current.connector_specific_config,
            proposed.connector_specific_config,
            inputs.rule_data,
        )
        if config_changed
        else None
    )
    field_changes: list[ConfigFieldChange] = (
        classify_source_config_change(
            current.source,
            current.connector_specific_config,
            proposed.connector_specific_config,
            override,
        )
        if config_changed
        else []
    )
    rule_steps: RuleSteps | None = override.rule_steps if override else None
    credential_changed: bool = proposed.credential_id != current.credential_id

    default_changes = [
        change
        for change in field_changes
        if rule_steps is None or change.field_name not in rule_steps.field_names
    ]
    steps = _field_change_steps(default_changes, current, proposed, inputs, override)
    if rule_steps is not None:
        steps.extend(_rule_steps(rule_steps, field_changes, proposed, inputs))
    indexing_start_steps, notes = _indexing_start_steps(current, proposed, inputs)
    steps.extend(indexing_start_steps)
    access_steps, access_notes = _access_steps(current, proposed, inputs)
    steps.extend(access_steps)
    notes.extend(access_notes)

    # The running attempt fetches with the old config, credential and start. A
    # cosmetic change, or one with no effect (e.g. reordered items, defaults
    # written out), does not change what it fetches.
    fetched_config_changed: bool = any(
        change.field_class != FieldClass.COSMETIC for change in field_changes
    )
    restarts: bool = inputs.attempt_running and (
        fetched_config_changed
        or credential_changed
        or proposed.indexing_start != current.indexing_start
    )
    if restarts:
        steps.append(
            _step(
                EditStepKind.RESTART_ATTEMPT,
                EditStepReason.ATTEMPT_RUNNING,
                required=True,
            )
        )
    notes.extend(_state_notes(current, inputs, restarts))

    opaque_fields = [
        change.field_name
        for change in default_changes
        if change.scope_direction == ScopeDirection.UNKNOWN
    ]

    credential_choice: CredentialChoice | None = None
    if credential_changed:
        # TODO(evan-onyx): when the new credential has the same access as the
        # old one, the plan can skip the choice.
        credential_choice = CredentialChoice()
        if current.source in CREDENTIAL_SWAP_FULL_PATH_SOURCES:
            notes.append(
                EditNote(
                    kind=EditNoteKind.CREDENTIAL_SWAP_USUALLY_NEEDS_FULL_PATH,
                    severity=EditNoteSeverity.INFO,
                    message=_CREDENTIAL_FULL_PATH_MESSAGE,
                )
            )

    return EditPlan(
        field_changes=field_changes,
        changed_settings=_changed_settings(current, proposed),
        steps=normalize_steps(steps),
        reconciliation_choice=(
            ReconciliationChoice(field_names=opaque_fields) if opaque_fields else None
        ),
        credential_choice=credential_choice,
        notes=notes,
        validation=inputs.validation,
        dry_run_results=inputs.dry_run_results,
        indexed_document_count=inputs.indexed_document_count,
    )
