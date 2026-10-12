"""Applies a stored connector edit plan: the proposed state and every step the
admin confirmed are written in one transaction.

Validation of the proposed state runs before the transaction and blocks
apply when a required check fails. Steps that index or prune are requests the
beats carry out later (see ``connector_edit_requests``), so the transaction
holds no slow work. The caller authorizes the user and does the work that
must follow the commit (task revokes, the indexing kick, the audit event).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.scoped_permissions import get_visible_user_group_ids
from onyx.configs.constants import DocumentSource
from onyx.connectors.edit_plan.models import (
    AppliedConnectorEdit,
    ConnectorEditAudit,
    ConnectorEditAuditFieldChange,
    CurrentPairState,
    EditPlanChoices,
    EditStep,
    EditStepKind,
    ProposedPairState,
    StoredEditPlan,
)
from onyx.connectors.edit_plan.overrides import resolve_edit_steps
from onyx.connectors.edit_plan.planner import (
    ensure_edit_is_plannable,
    restart_inputs_changed,
)
from onyx.connectors.edit_plan.state import fetch_current_pair_state
from onyx.connectors.edit_plan.store import (
    claim_edit_plan_for_apply,
    delete_edit_plan,
    ensure_base_state_matches,
    load_edit_plan,
    release_edit_plan_claim,
)
from onyx.connectors.exceptions import ValidationError
from onyx.connectors.factory import validate_and_record_pairing
from onyx.connectors.file.config import LocalFileConnectorConfig
from onyx.connectors.file.edit_staging import claim_staged_files__no_commit
from onyx.connectors.pairing_access import validate_pairing_access
from onyx.db.backfill_models import BackfillSpec
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_edit_requests import (
    apply_access_change__no_commit,
    clip_pending_backfills_to_start__no_commit,
    has_restartable_attempt,
    lock_cc_pair_for_edit__no_commit,
    reactivate_invalid_cc_pair__no_commit,
    request_attempt_restart__no_commit,
    request_backfills__no_commit,
    request_full_reindex__no_commit,
    request_prune__no_commit,
    request_prune_after_reindex__no_commit,
    write_edited_pair_state__no_commit,
)
from onyx.db.credentials import (
    credential_usable_for_source,
    fetch_credential_by_id,
    swap_cc_pair_credential__no_commit,
)
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import CapabilityCheckTrigger, IndexingMode
from onyx.db.models import Credential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PLAN_NOT_FOUND_MESSAGE = "The edit plan does not exist or has expired."


def load_plan_for_user(plan_id: UUID, cc_pair_id: int, user: User) -> StoredEditPlan:
    """The stored plan, only for the user who computed it.

    Raises:
        OnyxError: NOT_FOUND when the plan expired, belongs to another pair, or
            was computed by another user.
    """
    stored = load_edit_plan(plan_id, cc_pair_id)
    if stored is None or stored.user_id != user.id:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, _PLAN_NOT_FOUND_MESSAGE)
    return stored


def _validation_inputs_changed(
    current: CurrentPairState, proposed: ProposedPairState
) -> bool:
    return (
        proposed.connector_specific_config != current.connector_specific_config
        or proposed.credential_id != current.credential_id
        or proposed.access_type != current.access_type
    )


def _access_changed(current: CurrentPairState, proposed: ProposedPairState) -> bool:
    return (
        proposed.access_type != current.access_type
        or proposed.data_access_group_ids != current.data_access_group_ids
    )


def _proposed_credential(
    db_session: Session, current: CurrentPairState, proposed: ProposedPairState
) -> Credential:
    credential = fetch_credential_by_id(proposed.credential_id, db_session)
    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {proposed.credential_id} does not exist.",
        )
    if not credential_usable_for_source(credential, current.source):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Credential {credential.id} cannot be used by a "
            f"{current.source.value} connector.",
        )
    return credential


def _validate_proposed_state(
    db_session: Session,
    current: CurrentPairState,
    proposed: ProposedPairState,
    credential: Credential,
) -> bool:
    """Runs the blocking validation on the proposed state and records it as
    the pairing's report. Returns False when nothing it checks changed.

    Raises:
        OnyxError: INVALID_INPUT when the validation or a required check fails.
    """
    if not _validation_inputs_changed(current, proposed):
        return False
    try:
        validate_and_record_pairing(
            db_session,
            connector_id=current.connector_id,
            cc_pair_id=current.cc_pair_id,
            source=current.source,
            input_type=current.input_type,
            connector_specific_config=proposed.connector_specific_config,
            credential=credential,
            access_type=proposed.access_type,
            enforce_creation=True,
            trigger=CapabilityCheckTrigger.CONNECTOR_CONFIG_UPDATE,
        )
    except ValidationError as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"Connector validation failed: {e}"
        ) from e
    return True


def _backfills_at_apply(
    steps: list[EditStep], current: CurrentPairState, now: datetime
) -> list[BackfillSpec]:
    """The backfill windows, ending now instead of at plan time: a normal run
    between planning and apply moved the cursor with the old config. A window
    backfill still ends at the old indexing_start, which it fills up to."""
    backfills: list[BackfillSpec] = []
    for step in steps:
        if step.backfill is None:
            continue
        window_end = (
            min(current.indexing_start, now)
            if step.kind == EditStepKind.WINDOW_BACKFILL
            and current.indexing_start is not None
            else now
        )
        if step.backfill.window_start >= window_end:
            logger.info(
                "Skipping an empty backfill window: cc_pair=%s kind=%s",
                current.cc_pair_id,
                step.kind.value,
            )
            continue
        backfills.append(
            BackfillSpec(
                window_start=step.backfill.window_start,
                window_end=window_end,
                connector_config_override=step.backfill.connector_config_override,
            )
        )
    return backfills


def _audit(
    stored: StoredEditPlan,
    current: CurrentPairState,
    steps: list[EditStep],
    reactivated: bool,
) -> ConnectorEditAudit:
    proposed = stored.proposed
    return ConnectorEditAudit(
        plan_id=stored.plan_id,
        field_changes=[
            ConnectorEditAuditFieldChange(
                field_name=change.field_name,
                field_class=change.field_class,
                scope_direction=change.scope_direction,
                added_item_count=len(change.added_items),
                removed_item_count=len(change.removed_items),
            )
            for change in stored.plan.field_changes
        ],
        changed_settings=stored.plan.changed_settings,
        indexing_start_changed=proposed.indexing_start != current.indexing_start,
        old_access_type=current.access_type,
        new_access_type=proposed.access_type,
        old_data_access_group_ids=current.data_access_group_ids,
        new_data_access_group_ids=proposed.data_access_group_ids,
        old_credential_id=current.credential_id,
        new_credential_id=proposed.credential_id,
        steps=[step.kind for step in steps],
        reactivated=reactivated,
    )


def _write_edit__no_commit(
    db_session: Session,
    *,
    user: User,
    current: CurrentPairState,
    stored: StoredEditPlan,
    credential: Credential,
    steps: list[EditStep],
) -> list[str]:
    """Writes the proposed state and the step requests. Returns the task ids
    of the restarted attempts."""
    cc_pair_id = current.cc_pair_id
    proposed = stored.proposed
    try:
        write_edited_pair_state__no_commit(
            db_session,
            cc_pair_id,
            connector_specific_config=proposed.connector_specific_config,
            indexing_start=proposed.indexing_start,
            name=proposed.name,
            refresh_freq=proposed.refresh_freq,
            prune_freq=proposed.prune_freq,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e

    if proposed.credential_id != current.credential_id:
        cc_pair = get_connector_credential_pair_from_id(db_session, cc_pair_id)
        if cc_pair is None:
            raise OnyxError(
                OnyxErrorCode.CONNECTOR_NOT_FOUND,
                f"Connector-credential pair {cc_pair_id} does not exist.",
            )
        swap_cc_pair_credential__no_commit(db_session, cc_pair, credential)

    if _access_changed(current, proposed):
        apply_access_change__no_commit(
            db_session,
            cc_pair_id,
            proposed.access_type,
            set(proposed.data_access_group_ids),
            visible_group_ids=get_visible_user_group_ids(user, db_session),
        )

    # The file connector indexes only files staged for this edit; claiming
    # them keeps the staged-file cleanup from deleting them.
    if (
        current.source == DocumentSource.FILE
        and proposed.connector_specific_config != current.connector_specific_config
    ):
        claim_staged_files__no_commit(
            db_session,
            cc_pair_id,
            LocalFileConnectorConfig.model_validate(current.connector_specific_config),
            LocalFileConnectorConfig.model_validate(proposed.connector_specific_config),
        )

    kinds = {step.kind for step in steps}
    task_ids: list[str] = []
    # The plan may predate an attempt that started since; it runs with the
    # old state too.
    if EditStepKind.RESTART_ATTEMPT in kinds or (
        restart_inputs_changed(current, proposed, stored.plan.field_changes)
        and has_restartable_attempt(db_session, cc_pair_id)
    ):
        task_ids = request_attempt_restart__no_commit(
            db_session, cc_pair_id, IndexingMode.UPDATE
        )
    # Older backfills must not fetch documents from before a later start,
    # which this edit's prune removes. The restart above released every
    # backfill whose attempt was active. No start means no floor.
    new_start = proposed.indexing_start
    if new_start is not None and (
        current.indexing_start is None or new_start > current.indexing_start
    ):
        clip_pending_backfills_to_start__no_commit(db_session, cc_pair_id, new_start)
    if EditStepKind.FULL_REINDEX_THEN_PRUNE in kinds:
        request_prune_after_reindex__no_commit(db_session, cc_pair_id)
    if EditStepKind.FULL_REINDEX in kinds:
        request_full_reindex__no_commit(db_session, cc_pair_id)
    if EditStepKind.PRUNE in kinds:
        request_prune__no_commit(db_session, cc_pair_id)

    now = get_db_current_time(db_session)
    if backfills := _backfills_at_apply(steps, current, now):
        request_backfills__no_commit(db_session, cc_pair_id, backfills, now)
    return task_ids


def _safe_retire_applied_plan(plan_id: UUID) -> None:
    """Deletes a plan whose edit committed, then frees its claim. A failure
    here must not fail the committed apply: the claim then stays until it
    expires, and keeps refusing the plan until then."""
    try:
        delete_edit_plan(plan_id)
        release_edit_plan_claim(plan_id)
    except Exception:
        logger.exception("Could not delete an applied edit plan: plan_id=%s", plan_id)


def apply_connector_edit(
    db_session: Session,
    *,
    stored: StoredEditPlan,
    choices: EditPlanChoices,
    user: User,
) -> AppliedConnectorEdit:
    """Applies ``stored`` with the admin's ``choices`` and commits.

    The plan is single use. An apply claims it first and deletes it only
    after the commit, so a failed apply leaves it usable. A second apply of
    the plan gets CONFLICT while the first holds the claim, and NOT_FOUND
    once the first deleted the plan. The base-state check alone would not
    refuse it: a settings-only edit leaves the base state unchanged.

    Raises:
        OnyxError: EDIT_PLAN_STALE when the pair changed after planning;
            INVALID_INPUT for invalid choices, a failed validation or an
            invalid setting; NOT_FOUND when another apply used the plan;
            CONFLICT while another apply of the plan runs, or for a DELETING
            pair. Nothing is written then.
    """
    if not claim_edit_plan_for_apply(stored.plan_id):
        raise OnyxError(OnyxErrorCode.CONFLICT, "This edit plan is being applied.")
    try:
        applied = _apply_claimed_plan(
            db_session, stored=stored, choices=choices, user=user
        )
    except Exception:
        release_edit_plan_claim(stored.plan_id)
        raise
    _safe_retire_applied_plan(stored.plan_id)
    return applied


def _apply_claimed_plan(
    db_session: Session,
    *,
    stored: StoredEditPlan,
    choices: EditPlanChoices,
    user: User,
) -> AppliedConnectorEdit:
    cc_pair_id = stored.cc_pair_id
    proposed = stored.proposed

    current = fetch_current_pair_state(db_session, cc_pair_id)
    ensure_edit_is_plannable(current, proposed)
    ensure_base_state_matches(stored, current)
    steps = resolve_edit_steps(stored.plan, choices)
    if _access_changed(current, proposed):
        validate_pairing_access(
            db_session,
            user=user,
            source=current.source,
            access_type=proposed.access_type,
            data_access_group_ids=proposed.data_access_group_ids,
        )
    credential = _proposed_credential(db_session, current, proposed)
    validated = _validate_proposed_state(db_session, current, proposed, credential)

    try:
        lock_cc_pair_for_edit__no_commit(db_session, cc_pair_id)
        # Under the lock: a concurrent apply of this plan has committed and
        # deleted it, or changed the pair.
        if load_edit_plan(stored.plan_id, cc_pair_id) is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, _PLAN_NOT_FOUND_MESSAGE)
        current = fetch_current_pair_state(db_session, cc_pair_id)
        ensure_base_state_matches(stored, current)

        credential = _proposed_credential(db_session, current, proposed)
        task_ids = _write_edit__no_commit(
            db_session,
            user=user,
            current=current,
            stored=stored,
            credential=credential,
            steps=steps,
        )
        reactivated = validated and reactivate_invalid_cc_pair__no_commit(
            db_session, cc_pair_id
        )
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise

    return AppliedConnectorEdit(
        steps=steps,
        reactivated=reactivated,
        restarted_task_ids=task_ids,
        audit=_audit(stored, current, steps, reactivated),
    )
