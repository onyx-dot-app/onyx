"""The connector edit planner maps each change between the current and
proposed pair states to propagation steps, merges and orders the steps, and
adds notes for the pair's state."""

from datetime import datetime, timezone
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CredentialCapability,
    ProposedPairingValidation,
)
from onyx.connectors.edit_plan.models import (
    CredentialPath,
    CurrentPairState,
    EditNoteKind,
    EditNoteSeverity,
    EditPlan,
    EditPlanInputs,
    EditStep,
    EditStepKind,
    EditStepReason,
    ProposedPairState,
)
from onyx.connectors.edit_plan.planner import compute_edit_plan, normalize_steps
from onyx.connectors.edit_plan.store import compute_base_state_hash
from onyx.connectors.field_policy import FieldClass, ScopeDirection
from onyx.connectors.file.models import FilePlanningData
from onyx.connectors.github.config import GithubConnectorConfig
from onyx.connectors.models import InputType
from onyx.connectors.planning_rule import (
    ConnectorChangeOverride,
    PlanningData,
    RuleSteps,
    planning_rule_with_data,
)
from onyx.connectors.planning_rule_registry import PLANNING_RULES
from onyx.db.backfill_models import BackfillSpec
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import StoredFileFacts

_NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
_EARLIER_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
_CONFLUENCE_SITE: dict[str, Any] = {
    "wiki_base": "https://example.atlassian.net",
    "is_cloud": True,
}
_JIRA_SITE: dict[str, Any] = {"jira_base_url": "https://example.atlassian.net"}


def _current(
    source: DocumentSource = DocumentSource.SLACK,
    config: dict[str, Any] | None = None,
    *,
    access_type: AccessType = AccessType.PUBLIC,
    data_access_group_ids: list[int] | None = None,
    status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.ACTIVE,
    indexing_start: datetime | None = None,
    connector_pair_count: int = 1,
) -> CurrentPairState:
    return CurrentPairState(
        cc_pair_id=1,
        connector_id=2,
        status=status,
        connector_pair_count=connector_pair_count,
        source=source,
        input_type=InputType.POLL,
        connector_specific_config=config or {},
        access_type=access_type,
        data_access_group_ids=data_access_group_ids or [],
        credential_id=3,
        indexing_start=indexing_start,
        name="pair",
        refresh_freq=3600,
        prune_freq=86400,
    )


def _proposed(current: CurrentPairState, **changes: Any) -> ProposedPairState:
    return ProposedPairState.model_validate(
        current.model_dump(
            exclude={"cc_pair_id", "connector_id", "status", "connector_pair_count"}
        )
        | changes
    )


def _inputs(**overrides: Any) -> EditPlanInputs:
    return EditPlanInputs.model_validate(
        {
            "supports_windowed_runs": True,
            "prune_honors_indexing_start": True,
            "fetches_permissions_during_indexing": False,
            "access_filter_enforced": True,
            "attempt_running": False,
            "indexed_document_count": 10,
            "now": _NOW,
        }
        | overrides
    )


def _plan(
    current: CurrentPairState, inputs: EditPlanInputs | None = None, **changes: Any
) -> EditPlan:
    return compute_edit_plan(
        current, _proposed(current, **changes), inputs or _inputs()
    )


def _kinds(plan: EditPlan) -> list[EditStepKind]:
    return [step.kind for step in plan.steps]


def _notes(plan: EditPlan) -> list[EditNoteKind]:
    return [note.kind for note in plan.notes]


def _step(plan: EditPlan, kind: EditStepKind) -> EditStep:
    return next(step for step in plan.steps if step.kind == kind)


# Field classes


def test_identity_change_reindexes_then_prunes() -> None:
    current = _current(DocumentSource.GITHUB, {"repo_owner": "onyx"})
    plan = _plan(current, connector_specific_config={"repo_owner": "other"})

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX_THEN_PRUNE]
    step = plan.steps[0]
    assert step.reasons == [EditStepReason.IDENTITY_CHANGED]
    assert step.field_names == ["repo_owner"]
    assert not step.required
    assert plan.field_changes[0].field_class == FieldClass.IDENTITY


def test_behavior_change_reindexes() -> None:
    current = _current(DocumentSource.CONFLUENCE, _CONFLUENCE_SITE)
    plan = _plan(
        current,
        connector_specific_config=_CONFLUENCE_SITE | {"timezone_offset": 5.0},
    )

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX]
    assert plan.steps[0].reasons == [EditStepReason.BEHAVIOR_CHANGED]


def test_cosmetic_change_has_no_steps() -> None:
    current = _current(config={"channels": ["a"]})
    plan = _plan(
        current, connector_specific_config={"channels": ["a"], "batch_size": 7}
    )

    assert plan.steps == []
    assert [change.field_class for change in plan.field_changes] == [
        FieldClass.COSMETIC
    ]


# Scope directions


def test_slack_channel_added_is_a_scoped_backfill() -> None:
    current = _current(config={"channels": ["a"]})
    plan = _plan(current, connector_specific_config={"channels": ["a", "b"]})

    assert _kinds(plan) == [EditStepKind.SCOPED_BACKFILL]
    step = plan.steps[0]
    assert step.backfill == BackfillSpec(
        window_start=_EPOCH,
        window_end=_NOW,
        connector_config_override={"channels": ["b"]},
    )
    assert step.field_names == ["channels"]


def test_scoped_backfill_starts_at_the_indexing_start() -> None:
    current = _current(config={"channels": ["a"]}, indexing_start=_START)
    plan = _plan(current, connector_specific_config={"channels": ["a", "b"]})

    backfill = _step(plan, EditStepKind.SCOPED_BACKFILL).backfill
    assert backfill is not None
    assert backfill.window_start == _START


def test_widening_on_a_load_state_source_reindexes() -> None:
    current = _current(config={"channels": ["a"]})
    plan = _plan(
        current,
        _inputs(supports_windowed_runs=False),
        connector_specific_config={"channels": ["a", "b"]},
    )

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX]
    assert plan.steps[0].reasons == [EditStepReason.SCOPE_WIDENED]


def test_widening_to_everything_reindexes() -> None:
    current = _current(config={"channels": ["a"]})
    plan = _plan(current, connector_specific_config={"channels": None})

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX]


def test_narrowing_prunes() -> None:
    current = _current(config={"channels": ["a", "b"]})
    plan = _plan(current, connector_specific_config={"channels": ["a"]})

    assert _kinds(plan) == [EditStepKind.PRUNE]
    assert plan.steps[0].reasons == [EditStepReason.SCOPE_NARROWED]


def test_both_directions_reindex_then_prune() -> None:
    current = _current(config={"channels": ["a", "b"]})
    plan = _plan(current, connector_specific_config={"channels": ["a", "c"]})

    assert plan.field_changes[0].scope_direction == ScopeDirection.BOTH
    assert _kinds(plan) == [EditStepKind.FULL_REINDEX_THEN_PRUNE]
    assert plan.steps[0].reasons == [
        EditStepReason.SCOPE_WIDENED,
        EditStepReason.SCOPE_NARROWED,
    ]


def test_widen_and_narrow_on_two_fields() -> None:
    current = _current(config={"channels": ["a"], "exclude_channels": ["x"]})
    plan = _plan(
        current,
        connector_specific_config={
            "channels": ["a", "b"],
            "exclude_channels": ["x", "y"],
        },
    )

    # The narrowing blocks the delta config, so the widening is a re-index.
    assert _kinds(plan) == [EditStepKind.FULL_REINDEX_THEN_PRUNE]


def test_github_repo_owner_change_reindexes_then_prunes() -> None:
    current = _current(
        DocumentSource.GITHUB, {"repo_owner": "onyx", "repositories": "a"}
    )
    plan = _plan(
        current,
        connector_specific_config={"repo_owner": "acme", "repositories": "a"},
    )

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX_THEN_PRUNE]
    assert plan.steps[0].field_names == ["repo_owner"]


def test_confluence_cql_change_needs_a_reconciliation_choice() -> None:
    current = _current(
        DocumentSource.CONFLUENCE, _CONFLUENCE_SITE | {"cql_query": "type=page"}
    )
    plan = _plan(
        current,
        connector_specific_config=_CONFLUENCE_SITE | {"cql_query": "type=blogpost"},
    )

    assert plan.steps == []
    assert plan.reconciliation_choice is not None
    assert plan.reconciliation_choice.field_names == ["cql_query"]
    assert len(plan.reconciliation_choice.options) == 4


def test_opaque_and_directed_changes_together() -> None:
    current = _current(
        DocumentSource.CONFLUENCE, _CONFLUENCE_SITE | {"cql_query": "type=page"}
    )
    plan = _plan(
        current,
        connector_specific_config=_CONFLUENCE_SITE
        | {"cql_query": "type=blogpost", "timezone_offset": 3.0},
    )

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX]
    assert plan.reconciliation_choice is not None


# indexing_start


def test_indexing_start_earlier_is_a_window_backfill() -> None:
    current = _current(indexing_start=_START)
    plan = _plan(current, indexing_start=_EARLIER_START)

    assert _kinds(plan) == [EditStepKind.WINDOW_BACKFILL]
    assert plan.steps[0].backfill == BackfillSpec(
        window_start=_EARLIER_START, window_end=_START
    )


def test_indexing_start_removed_backfills_from_the_epoch() -> None:
    current = _current(indexing_start=_START)
    plan = _plan(current, indexing_start=None)

    assert plan.steps[0].backfill == BackfillSpec(
        window_start=_EPOCH, window_end=_START
    )


def test_indexing_start_earlier_on_a_load_state_source_reindexes() -> None:
    current = _current(indexing_start=_START)
    plan = _plan(
        current, _inputs(supports_windowed_runs=False), indexing_start=_EARLIER_START
    )

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX]
    assert plan.steps[0].reasons == [EditStepReason.INDEXING_START_EARLIER]


@pytest.mark.parametrize(
    "old_start, new_start", [(_EARLIER_START, _START), (None, _START)]
)
def test_indexing_start_later_prunes(
    old_start: datetime | None, new_start: datetime
) -> None:
    current = _current(indexing_start=old_start)
    plan = _plan(current, indexing_start=new_start)

    assert _kinds(plan) == [EditStepKind.PRUNE]
    step = plan.steps[0]
    assert step.reasons == [EditStepReason.INDEXING_START_LATER]
    assert not step.required
    assert _notes(plan) == [EditNoteKind.INDEXING_START_LATER]


@pytest.mark.parametrize(
    "old_start, new_start", [(_EARLIER_START, _START), (None, _START)]
)
def test_indexing_start_later_without_a_dated_prune_only_notes(
    old_start: datetime | None, new_start: datetime
) -> None:
    """A load-state source, or one whose prune lists all documents."""
    current = _current(indexing_start=old_start)
    plan = _plan(
        current,
        _inputs(prune_honors_indexing_start=False),
        indexing_start=new_start,
    )

    assert plan.steps == []
    assert _notes(plan) == [EditNoteKind.INDEXING_START_LATER]
    assert "stay indexed" in plan.notes[0].message


def test_indexing_start_later_and_a_reindex_reindex_then_prune() -> None:
    current = _current(
        DocumentSource.CONFLUENCE, _CONFLUENCE_SITE, indexing_start=_EARLIER_START
    )
    plan = _plan(
        current,
        connector_specific_config=_CONFLUENCE_SITE | {"timezone_offset": 5.0},
        indexing_start=_START,
    )

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX_THEN_PRUNE]
    assert plan.steps[0].reasons == [
        EditStepReason.BEHAVIOR_CHANGED,
        EditStepReason.INDEXING_START_LATER,
    ]


def test_indexing_start_later_prune_folds_into_an_identity_change() -> None:
    current = _current(
        DocumentSource.GITHUB, {"repo_owner": "onyx"}, indexing_start=_EARLIER_START
    )
    plan = _plan(
        current,
        connector_specific_config={"repo_owner": "other"},
        indexing_start=_START,
    )

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX_THEN_PRUNE]
    assert plan.steps[0].reasons == [
        EditStepReason.IDENTITY_CHANGED,
        EditStepReason.INDEXING_START_LATER,
    ]


def test_naive_indexing_start_is_utc() -> None:
    current = _current(indexing_start=_START.replace(tzinfo=None))
    plan = _plan(current, indexing_start=_START)

    assert plan.steps == []
    assert plan.notes == []


def test_scoped_and_window_backfills_together() -> None:
    current = _current(config={"channels": ["a"]}, indexing_start=_START)
    plan = _plan(
        current,
        connector_specific_config={"channels": ["a", "b"]},
        indexing_start=_EARLIER_START,
    )

    assert _kinds(plan) == [
        EditStepKind.SCOPED_BACKFILL,
        EditStepKind.WINDOW_BACKFILL,
    ]
    scoped = _step(plan, EditStepKind.SCOPED_BACKFILL).backfill
    assert scoped is not None
    assert scoped.window_start == _EARLIER_START


# Credential


@pytest.mark.parametrize(
    "source, config, expect_note",
    [
        (DocumentSource.SLACK, {}, False),
        (DocumentSource.CONFLUENCE, _CONFLUENCE_SITE, True),
        (DocumentSource.JIRA, _JIRA_SITE, True),
    ],
)
def test_credential_change_offers_a_choice(
    source: DocumentSource, config: dict[str, Any], expect_note: bool
) -> None:
    current = _current(source, config)
    plan = _plan(current, credential_id=99)

    assert plan.steps == []
    assert plan.credential_choice is not None
    assert plan.credential_choice.default == CredentialPath.KEEP_INDEXED
    assert (
        EditNoteKind.CREDENTIAL_SWAP_USUALLY_NEEDS_FULL_PATH in _notes(plan)
    ) == expect_note


def test_no_credential_choice_without_a_credential_change() -> None:
    assert _plan(_current(), name="renamed").credential_choice is None


# Access


@pytest.mark.parametrize(
    "old_type, old_groups, new_type, new_groups, expected_kind",
    [
        (
            AccessType.PRIVATE,
            [1],
            AccessType.PRIVATE,
            [1, 2],
            EditStepKind.ACCESS_GROUPS,
        ),
        (AccessType.PUBLIC, [], AccessType.PRIVATE, [1], EditStepKind.ACCESS_TYPE),
        (AccessType.PRIVATE, [1], AccessType.PUBLIC, [], EditStepKind.ACCESS_TYPE),
        (AccessType.PUBLIC, [], AccessType.SYNC, [], EditStepKind.ENTER_PERM_SYNC),
        (
            AccessType.PRIVATE,
            [1],
            AccessType.SYNC_RESTRICTED,
            [1],
            EditStepKind.ENTER_PERM_SYNC,
        ),
        (AccessType.SYNC, [], AccessType.PUBLIC, [], EditStepKind.LEAVE_PERM_SYNC),
        (
            AccessType.SYNC,
            [],
            AccessType.SYNC_RESTRICTED,
            [1],
            EditStepKind.ACCESS_TYPE,
        ),
    ],
)
def test_access_transitions(
    old_type: AccessType,
    old_groups: list[int],
    new_type: AccessType,
    new_groups: list[int],
    expected_kind: EditStepKind,
) -> None:
    current = _current(access_type=old_type, data_access_group_ids=old_groups)
    plan = _plan(current, access_type=new_type, data_access_group_ids=new_groups)

    assert _kinds(plan) == [expected_kind]
    assert plan.steps[0].required
    assert plan.notes == []


def test_group_order_is_not_a_change() -> None:
    current = _current(access_type=AccessType.PRIVATE, data_access_group_ids=[2, 1])
    plan = _plan(current, data_access_group_ids=[1, 2, 2])

    assert plan.steps == []


def test_entering_sync_reindexes_when_permissions_come_from_indexing() -> None:
    current = _current()
    plan = _plan(
        current,
        _inputs(fetches_permissions_during_indexing=True),
        access_type=AccessType.SYNC,
    )

    assert _kinds(plan) == [EditStepKind.ENTER_PERM_SYNC, EditStepKind.FULL_REINDEX]
    reindex = _step(plan, EditStepKind.FULL_REINDEX)
    assert reindex.required
    assert reindex.reasons == [EditStepReason.PERMISSIONS_FETCHED_DURING_INDEXING]


def test_leaving_sync_does_not_reindex_for_indexing_permissions() -> None:
    current = _current(access_type=AccessType.SYNC)
    plan = _plan(
        current,
        _inputs(fetches_permissions_during_indexing=True),
        access_type=AccessType.PUBLIC,
    )

    assert _kinds(plan) == [EditStepKind.LEAVE_PERM_SYNC]


def test_access_change_without_enforce_warns() -> None:
    current = _current()
    plan = _plan(
        current, _inputs(access_filter_enforced=False), access_type=AccessType.PRIVATE
    )

    assert _notes(plan) == [EditNoteKind.ACCESS_AFTER_METADATA_SYNC]


def test_leaving_sync_without_enforce_warns_of_stale_acls() -> None:
    current = _current(access_type=AccessType.SYNC)
    plan = _plan(
        current, _inputs(access_filter_enforced=False), access_type=AccessType.PUBLIC
    )

    assert _kinds(plan) == [EditStepKind.LEAVE_PERM_SYNC]
    assert _notes(plan) == [
        EditNoteKind.ACCESS_AFTER_METADATA_SYNC,
        EditNoteKind.STALE_SYNCED_ACLS,
    ]


# Subsumption


def _raw(kind: EditStepKind, *, required: bool = False) -> EditStep:
    backfill = (
        BackfillSpec(window_start=_EPOCH, window_end=_NOW)
        if kind in (EditStepKind.SCOPED_BACKFILL, EditStepKind.WINDOW_BACKFILL)
        else None
    )
    return EditStep(
        kind=kind,
        required=required,
        reasons=[EditStepReason.ADMIN_ADDED],
        backfill=backfill,
    )


def test_full_reindex_subsumes_backfills() -> None:
    steps = normalize_steps(
        [
            _raw(EditStepKind.WINDOW_BACKFILL),
            _raw(EditStepKind.SCOPED_BACKFILL),
            _raw(EditStepKind.FULL_REINDEX),
        ]
    )

    assert [step.kind for step in steps] == [EditStepKind.FULL_REINDEX]
    assert steps[0].backfill is None


@pytest.mark.parametrize("required", [True, False])
def test_reindex_and_prune_become_prune_after_reindex(required: bool) -> None:
    steps = normalize_steps(
        [
            _raw(EditStepKind.PRUNE, required=required),
            _raw(EditStepKind.FULL_REINDEX, required=required),
            _raw(EditStepKind.SCOPED_BACKFILL),
        ]
    )

    assert [step.kind for step in steps] == [EditStepKind.FULL_REINDEX_THEN_PRUNE]
    assert steps[0].required == required


def test_required_reindex_keeps_an_optional_prune_apart() -> None:
    steps = normalize_steps(
        [_raw(EditStepKind.PRUNE), _raw(EditStepKind.FULL_REINDEX, required=True)]
    )

    assert [(step.kind, step.required) for step in steps] == [
        (EditStepKind.FULL_REINDEX, True),
        (EditStepKind.PRUNE, False),
    ]


def test_prune_after_reindex_subsumes_a_prune() -> None:
    steps = normalize_steps(
        [_raw(EditStepKind.PRUNE), _raw(EditStepKind.FULL_REINDEX_THEN_PRUNE)]
    )

    assert [step.kind for step in steps] == [EditStepKind.FULL_REINDEX_THEN_PRUNE]


def test_steps_are_deduplicated_and_ordered() -> None:
    steps = normalize_steps(
        [
            _raw(EditStepKind.PRUNE),
            _raw(EditStepKind.PRUNE),
            _raw(EditStepKind.SCOPED_BACKFILL),
            _raw(EditStepKind.RESTART_ATTEMPT, required=True),
            _raw(EditStepKind.ACCESS_TYPE, required=True),
        ]
    )

    assert [step.kind for step in steps] == [
        EditStepKind.ACCESS_TYPE,
        EditStepKind.RESTART_ATTEMPT,
        EditStepKind.SCOPED_BACKFILL,
        EditStepKind.PRUNE,
    ]


def test_backfills_of_one_kind_with_different_windows_raise() -> None:
    other = _raw(EditStepKind.WINDOW_BACKFILL)
    other.backfill = BackfillSpec(window_start=_START, window_end=_NOW)

    with pytest.raises(ValueError):
        normalize_steps([_raw(EditStepKind.WINDOW_BACKFILL), other])


def test_identity_and_narrowing_merge_into_one_step() -> None:
    current = _current(
        DocumentSource.GITHUB, {"repo_owner": "onyx", "repositories": "a,b"}
    )
    plan = _plan(
        current,
        connector_specific_config={"repo_owner": "acme", "repositories": "a"},
    )

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX_THEN_PRUNE]
    assert plan.steps[0].reasons == [
        EditStepReason.IDENTITY_CHANGED,
        EditStepReason.SCOPE_NARROWED,
    ]
    assert plan.steps[0].field_names == ["repo_owner", "repositories"]


# Pair state


def test_running_attempt_restarts_on_a_config_change() -> None:
    current = _current(config={"channels": ["a", "b"]})
    plan = _plan(
        current,
        _inputs(attempt_running=True),
        connector_specific_config={"channels": ["a"]},
    )

    assert _kinds(plan) == [EditStepKind.RESTART_ATTEMPT, EditStepKind.PRUNE]
    assert _step(plan, EditStepKind.RESTART_ATTEMPT).required
    assert _notes(plan) == [EditNoteKind.ATTEMPT_RESTARTED]


@pytest.mark.parametrize(
    "old_config, new_config",
    [
        # Cosmetic only.
        ({"channels": ["a"]}, {"channels": ["a"], "batch_size": 5}),
        # The same scope: reordered items, a default written out.
        ({"channels": ["a", "b"]}, {"channels": ["b", "a"]}),
        ({"channels": ["a"]}, {"channels": ["a"], "include_bot_messages": False}),
    ],
)
def test_running_attempt_is_kept_when_what_it_fetches_is_the_same(
    old_config: dict[str, Any], new_config: dict[str, Any]
) -> None:
    plan = _plan(
        _current(config=old_config),
        _inputs(attempt_running=True),
        connector_specific_config=new_config,
    )

    assert EditStepKind.RESTART_ATTEMPT not in _kinds(plan)


def test_running_attempt_restarts_on_a_credential_change() -> None:
    plan = _plan(_current(), _inputs(attempt_running=True), credential_id=99)

    assert _kinds(plan) == [EditStepKind.RESTART_ATTEMPT]


def test_running_attempt_is_kept_for_an_access_change() -> None:
    plan = _plan(
        _current(), _inputs(attempt_running=True), access_type=AccessType.PRIVATE
    )

    assert _kinds(plan) == [EditStepKind.ACCESS_TYPE]
    assert EditNoteKind.ATTEMPT_RESTARTED not in _notes(plan)


def test_paused_note() -> None:
    plan = _plan(_current(status=ConnectorCredentialPairStatus.PAUSED), name="x")

    assert _notes(plan) == [EditNoteKind.PAUSED]


@pytest.mark.parametrize(
    "validation, expected_notes",
    [
        (ProposedPairingValidation(), [EditNoteKind.INVALID_CLEARED_BY_VALIDATION]),
        # Nothing that validation checks changed, so apply does not validate.
        (None, []),
        (ProposedPairingValidation(validation_error="bad token"), []),
    ],
)
def test_invalid_note_needs_a_passed_validation(
    validation: ProposedPairingValidation | None, expected_notes: list[EditNoteKind]
) -> None:
    plan = _plan(
        _current(status=ConnectorCredentialPairStatus.INVALID),
        _inputs(validation=validation),
        name="renamed",
    )

    assert _notes(plan) == expected_notes


def test_deleting_pair_is_refused() -> None:
    with pytest.raises(OnyxError) as exc:
        _plan(_current(status=ConnectorCredentialPairStatus.DELETING), name="x")

    assert exc.value.error_code == OnyxErrorCode.CONFLICT


@pytest.mark.parametrize(
    "changes",
    [{"source": DocumentSource.GITHUB}, {"input_type": InputType.LOAD_STATE}],
)
def test_source_and_input_type_changes_are_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(OnyxError) as exc:
        _plan(_current(), **changes)

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    "changes",
    [
        {"connector_specific_config": {"channels": ["general"]}},
        {"indexing_start": datetime(2025, 1, 1, tzinfo=timezone.utc)},
        {"refresh_freq": 7200},
        {"prune_freq": 172800},
    ],
)
def test_connector_field_edit_of_a_shared_connector_is_refused(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(OnyxError) as exc:
        _plan(_current(connector_pair_count=2), **changes)

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_pair_field_edit_of_a_shared_connector_is_planned() -> None:
    plan = _plan(
        _current(connector_pair_count=2),
        name="renamed",
        access_type=AccessType.PRIVATE,
    )

    assert plan.changed_settings == ["name"]


def test_config_edit_of_a_source_without_a_config_model_is_refused() -> None:
    current = _current(DocumentSource.INGESTION_API, {})

    with pytest.raises(OnyxError) as exc:
        _plan(current, connector_specific_config={"a": 1})

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_settings_changes_have_no_steps() -> None:
    plan = _plan(_current(), name="renamed", refresh_freq=60, prune_freq=600)

    assert plan.steps == []
    assert plan.changed_settings == ["name", "refresh_freq", "prune_freq"]


# Validation


def _check_result(
    required: bool, status: CapabilityCheckStatus
) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=CredentialCapability.INDEXING,
        check_id="check",
        display_name="Check",
        required=required,
        status=status,
    )


@pytest.mark.parametrize(
    "validation, blocks",
    [
        (None, False),
        (ProposedPairingValidation(), False),
        (ProposedPairingValidation(validation_error="bad token"), True),
        (
            ProposedPairingValidation(
                check_results=[_check_result(True, CapabilityCheckStatus.FAILED)]
            ),
            True,
        ),
        (
            ProposedPairingValidation(
                check_results=[_check_result(False, CapabilityCheckStatus.FAILED)]
            ),
            False,
        ),
    ],
)
def test_validation_blocks_apply(
    validation: ProposedPairingValidation | None, blocks: bool
) -> None:
    plan = _plan(_current(), _inputs(validation=validation), credential_id=99)

    assert plan.validation == validation
    assert plan.validation_blocks_apply == blocks


def test_unfinished_checks_point_to_the_dry_run() -> None:
    validation = ProposedPairingValidation(unfinished_check_ids=frozenset({"slow"}))
    dry_run = [_check_result(True, CapabilityCheckStatus.PASSED)]
    plan = _plan(
        _current(),
        _inputs(validation=validation, dry_run_results=dry_run),
        credential_id=99,
    )

    assert EditNoteKind.CHECKS_STILL_RUNNING in _notes(plan)
    assert plan.dry_run_results == dry_run
    assert not plan.validation_blocks_apply


def test_unfinished_check_with_a_failed_dry_run_warns() -> None:
    validation = ProposedPairingValidation(unfinished_check_ids=frozenset({"check"}))
    dry_run = [_check_result(True, CapabilityCheckStatus.FAILED)]
    plan = _plan(
        _current(),
        _inputs(validation=validation, dry_run_results=dry_run),
        credential_id=99,
    )

    assert _notes(plan) == [
        EditNoteKind.CHECKS_STILL_RUNNING,
        EditNoteKind.UNFINISHED_CHECK_FAILED_IN_DRY_RUN,
    ]
    warning = plan.notes[1]
    assert warning.severity == EditNoteSeverity.WARNING
    assert "Check" in warning.message


@pytest.mark.parametrize(
    "changes",
    [{"source": DocumentSource.GITHUB}, {"input_type": InputType.LOAD_STATE}],
)
def test_base_state_hash_covers_source_and_input_type(changes: dict[str, Any]) -> None:
    current = _current()

    assert compute_base_state_hash(current) != compute_base_state_hash(
        current.model_copy(update=changes)
    )


# Planning rule steps


class _RuleData(PlanningData):
    backfill_repositories: str


def _github_rule(
    old: GithubConnectorConfig,  # noqa: ARG001
    new: GithubConnectorConfig,
    data: _RuleData,
) -> ConnectorChangeOverride:
    return ConnectorChangeOverride(
        rule_steps=RuleSteps(
            field_names=frozenset({"repo_owner"}),
            backfill_config=new.model_dump(mode="json")
            | {"repositories": data.backfill_repositories},
            prune=True,
        )
    )


@pytest.fixture
def github_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        PLANNING_RULES,
        DocumentSource.GITHUB,
        planning_rule_with_data(
            GithubConnectorConfig,
            _RuleData,
            lambda *_: _RuleData(backfill_repositories=""),
            _github_rule,
        ),
    )


def test_rule_steps_replace_the_default_steps_of_their_fields(
    github_rule: None,  # noqa: ARG001
) -> None:
    current = _current(
        DocumentSource.GITHUB, {"repo_owner": "onyx", "repositories": "a"}
    )
    plan = _plan(
        current,
        _inputs(
            supports_windowed_runs=False,
            rule_data=_RuleData(backfill_repositories="a"),
        ),
        connector_specific_config={"repo_owner": "acme", "repositories": "a"},
    )

    # The IDENTITY change gives no full re-index; the rule's backfill runs
    # even though the source cannot fetch a window.
    assert _kinds(plan) == [EditStepKind.SCOPED_BACKFILL, EditStepKind.PRUNE]
    backfill_step = _step(plan, EditStepKind.SCOPED_BACKFILL)
    assert backfill_step.reasons == [EditStepReason.ITEMS_ADDED_OR_CHANGED]
    assert backfill_step.field_names == ["repo_owner"]
    assert backfill_step.backfill is not None
    assert backfill_step.backfill.connector_config_override is not None
    assert backfill_step.backfill.connector_config_override["repositories"] == "a"
    assert _step(plan, EditStepKind.PRUNE).reasons == [EditStepReason.ITEMS_REMOVED]


def test_fields_outside_the_rule_steps_keep_the_default_steps(
    github_rule: None,  # noqa: ARG001
) -> None:
    current = _current(
        DocumentSource.GITHUB, {"repo_owner": "onyx", "repositories": "a"}
    )
    plan = _plan(
        current,
        _inputs(rule_data=_RuleData(backfill_repositories="a")),
        connector_specific_config={"repo_owner": "acme", "repositories": "a,b"},
    )

    # The default widening has no delta config while repo_owner changes, so
    # it is a full re-index, which also covers the rule's backfill.
    assert _kinds(plan) == [EditStepKind.FULL_REINDEX_THEN_PRUNE]


def test_rule_without_its_data_uses_the_default_rules(
    github_rule: None,  # noqa: ARG001
) -> None:
    current = _current(
        DocumentSource.GITHUB, {"repo_owner": "onyx", "repositories": "a"}
    )
    plan = _plan(
        current, connector_specific_config={"repo_owner": "acme", "repositories": "a"}
    )

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX_THEN_PRUNE]
    assert plan.steps[0].reasons == [EditStepReason.IDENTITY_CHANGED]


def _file_data(**metadata: dict[str, Any]) -> FilePlanningData:
    return FilePlanningData(
        files={
            file_id: StoredFileFacts(
                display_name=f"{file_id}.txt",
                file_type="text/plain",
                content_sha256=f"sha-{file_id}",
            )
            for file_id in ("f1", "f2", "f3")
        },
        old_metadata=metadata.get("old", {}),
        new_metadata=metadata.get("new", {}),
    )


def test_file_edit_indexes_added_files_and_prunes_removed_ones() -> None:
    current = _current(
        DocumentSource.FILE,
        {"file_locations": ["f1", "f2"], "zip_metadata_file_id": "m1"},
        indexing_start=_START,
    )
    plan = _plan(
        current,
        _inputs(
            supports_windowed_runs=False,
            rule_data=_file_data(
                old={"f1.txt": {"title": "one"}},
                new={"f1.txt": {"title": "one"}, "f3.txt": {"title": "three"}},
            ),
        ),
        connector_specific_config={
            "file_locations": ["f1", "f3"],
            "zip_metadata_file_id": "m2",
        },
    )

    assert _kinds(plan) == [EditStepKind.SCOPED_BACKFILL, EditStepKind.PRUNE]
    backfill_step = _step(plan, EditStepKind.SCOPED_BACKFILL)
    assert backfill_step.field_names == ["file_locations", "zip_metadata_file_id"]
    assert backfill_step.backfill is not None
    assert backfill_step.backfill.window_start == _START
    override = backfill_step.backfill.connector_config_override
    assert override is not None
    assert override["file_locations"] == ["f3"]
    assert override["zip_metadata_file_id"] == "m2"


def test_file_edit_without_file_data_reindexes() -> None:
    current = _current(
        DocumentSource.FILE,
        {"file_locations": ["f1"], "zip_metadata_file_id": "m1"},
    )
    plan = _plan(
        current,
        _inputs(supports_windowed_runs=False),
        connector_specific_config={
            "file_locations": ["f1", "f2"],
            "zip_metadata_file_id": "m2",
        },
    )

    assert _kinds(plan) == [EditStepKind.FULL_REINDEX]


def test_file_edit_with_a_future_indexing_start_keeps_the_scoped_backfill() -> None:
    current = _current(
        DocumentSource.FILE,
        {"file_locations": ["f1"]},
        indexing_start=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    plan = _plan(
        current,
        _inputs(supports_windowed_runs=False, rule_data=_file_data()),
        connector_specific_config={"file_locations": ["f1", "f2"]},
    )

    assert _kinds(plan) == [EditStepKind.SCOPED_BACKFILL]
    backfill = _step(plan, EditStepKind.SCOPED_BACKFILL).backfill
    assert backfill is not None
    assert (backfill.window_start, backfill.window_end) == (_EPOCH, _NOW)
    assert backfill.connector_config_override is not None
    assert backfill.connector_config_override["file_locations"] == ["f2"]


def test_planning_rule_runs_once_per_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[None] = []

    def rule(
        old: GithubConnectorConfig,  # noqa: ARG001
        new: GithubConnectorConfig,  # noqa: ARG001
        data: _RuleData,  # noqa: ARG001
    ) -> ConnectorChangeOverride | None:
        calls.append(None)
        return None

    monkeypatch.setitem(
        PLANNING_RULES,
        DocumentSource.GITHUB,
        planning_rule_with_data(
            GithubConnectorConfig,
            _RuleData,
            lambda *_: _RuleData(backfill_repositories=""),
            rule,
        ),
    )
    _plan(
        _current(DocumentSource.GITHUB, {"repo_owner": "onyx", "repositories": "a"}),
        _inputs(rule_data=_RuleData(backfill_repositories="")),
        connector_specific_config={"repo_owner": "onyx", "repositories": "a,b"},
    )

    assert len(calls) == 1
