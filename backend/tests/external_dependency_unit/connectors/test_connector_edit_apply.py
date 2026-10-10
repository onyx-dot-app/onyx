"""Applying a connector edit plan against a real pair: one transaction writes
the proposed state and a request per confirmed step, backfill windows end at
apply time, an invalid pair whose new state validates becomes active, and a
stale plan, a failed validation or a rejected authorization writes nothing.
The plan is single use and private to the user who computed it."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, NotificationType
from onyx.connectors.capability_checks.models import ProposedPairingValidation
from onyx.connectors.edit_plan import apply as apply_module
from onyx.connectors.edit_plan import orchestration
from onyx.connectors.edit_plan.apply import apply_connector_edit, load_plan_for_user
from onyx.connectors.edit_plan.models import (
    AppliedConnectorEdit,
    CredentialPath,
    EditPlanChoices,
    EditStepKind,
    EditStepReason,
    ProposedPairState,
    StoredEditPlan,
)
from onyx.connectors.edit_plan.orchestration import plan_connector_edit
from onyx.connectors.edit_plan.state import fetch_current_pair_state
from onyx.connectors.edit_plan.store import (
    claim_edit_plan_for_apply,
    load_edit_plan,
    release_edit_plan_claim,
    save_edit_plan,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import InputType
from onyx.db.backfill_models import BackfillSpec, PendingBackfill
from onyx.db.connector_alerts import notify_admins_of_connector_alert
from onyx.db.enums import (
    AccessType,
    CapabilityCheckTrigger,
    ConnectorCredentialPairStatus,
    IndexingMode,
    IndexingStatus,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    Credential,
    DocumentByConnectorCredentialPair,
    IndexAttempt,
    Notification,
    User,
    UserGroup,
    UserGroup__CCPairDataAccess,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.connector_edit import (
    _authorize_pair_edit,
    _authorize_proposed_state,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_user_group,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    seed_cc_pair_documents,
)

_STORED_CONFIG: dict[str, Any] = {"channels": ["general", "random"]}
_WIDENED_CONFIG: dict[str, Any] = {"channels": ["general", "random", "new"]}
_NARROWED_CONFIG: dict[str, Any] = {"channels": ["general"]}
_INDEXING_START = datetime(2025, 1, 1)
_INDEXING_START_UTC = _INDEXING_START.replace(tzinfo=timezone.utc)
_PLAN_TIME_END = datetime(2025, 6, 1, tzinfo=timezone.utc)


class _Validation:
    """Planning's validation and dry-run reads, and apply's recorded
    validation, without a Slack workspace."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            orchestration,
            "validate_proposed_pairing",
            MagicMock(return_value=ProposedPairingValidation()),
        )
        monkeypatch.setattr(
            orchestration, "get_cc_pair_dry_run_results", MagicMock(return_value=[])
        )
        self.record = MagicMock(return_value=True)
        monkeypatch.setattr(apply_module, "validate_and_record_pairing", self.record)


@pytest.fixture
def validation(monkeypatch: pytest.MonkeyPatch) -> _Validation:
    return _Validation(monkeypatch)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "edit_apply_admin", is_admin=True)
    yield user
    db_session.rollback()
    delete_test_user(db_session, user)
    db_session.commit()


@pytest.fixture
def other_admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "edit_apply_other", is_admin=True)
    yield user
    db_session.rollback()
    delete_test_user(db_session, user)
    db_session.commit()


@pytest.fixture
def slack_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session, source=DocumentSource.SLACK)
    pair.connector.input_type = InputType.POLL
    pair.connector.connector_specific_config = _STORED_CONFIG
    pair.connector.indexing_start = _INDEXING_START
    db_session.commit()
    original_credential_id = pair.credential_id
    yield pair
    db_session.rollback()
    db_session.execute(
        delete(IndexAttempt).where(IndexAttempt.connector_credential_pair_id == pair.id)
    )
    db_session.execute(
        delete(UserGroup__CCPairDataAccess).where(
            UserGroup__CCPairDataAccess.cc_pair_id == pair.id
        )
    )
    db_session.commit()
    cleanup_cc_pair(db_session, pair)
    # A swapped pair takes only its new credential with it.
    db_session.execute(
        delete(Credential).where(Credential.id == original_credential_id)
    )
    db_session.commit()


@pytest.fixture
def other_credential(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[Credential, None, None]:
    credential = Credential(source=DocumentSource.SLACK, credential_json={})
    db_session.add(credential)
    db_session.commit()
    credential_id = credential.id
    yield credential
    db_session.rollback()
    db_session.execute(delete(Credential).where(Credential.id == credential_id))
    db_session.commit()


@pytest.fixture
def group(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[UserGroup, None, None]:
    created = create_test_user_group(db_session, members=[])
    yield created
    db_session.rollback()
    db_session.execute(
        delete(UserGroup__CCPairDataAccess).where(
            UserGroup__CCPairDataAccess.user_group_id == created.id
        )
    )
    db_session.execute(delete(UserGroup).where(UserGroup.id == created.id))
    db_session.commit()


def _proposed(
    db_session: Session, pair: ConnectorCredentialPair, **changes: Any
) -> ProposedPairState:
    current = fetch_current_pair_state(db_session, pair.id)
    return ProposedPairState.model_validate(
        current.model_dump(exclude={"cc_pair_id", "connector_id", "status"}) | changes
    )


def _plan(
    db_session: Session, pair: ConnectorCredentialPair, user: User, **changes: Any
) -> StoredEditPlan:
    return plan_connector_edit(
        db_session,
        cc_pair_id=pair.id,
        proposed=_proposed(db_session, pair, **changes),
        user=user,
    )


def _apply(
    db_session: Session,
    stored: StoredEditPlan,
    user: User,
    choices: EditPlanChoices | None = None,
) -> AppliedConnectorEdit:
    return apply_connector_edit(
        db_session,
        stored=load_plan_for_user(stored.plan_id, stored.cc_pair_id, user),
        choices=choices or EditPlanChoices(),
        user=user,
    )


def _reload(db_session: Session, pair: ConnectorCredentialPair) -> None:
    db_session.expire_all()
    db_session.refresh(pair)


def test_scope_widening_writes_the_config_and_queues_a_backfill_ending_at_apply(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,
) -> None:
    stored = _plan(
        db_session, slack_pair, admin, connector_specific_config=_WIDENED_CONFIG
    )
    # A normal run between planning and apply moves the cursor past the
    # plan-time end, so apply must not reuse it.
    step = stored.plan.steps[0]
    assert step.kind == EditStepKind.SCOPED_BACKFILL
    assert step.backfill is not None
    step.backfill = step.backfill.model_copy(update={"window_end": _PLAN_TIME_END})
    save_edit_plan(stored)

    before_apply = datetime.now(timezone.utc) - timedelta(seconds=5)
    applied = _apply(db_session, stored, admin)

    assert [step.kind for step in applied.steps] == [EditStepKind.SCOPED_BACKFILL]
    _reload(db_session, slack_pair)
    assert slack_pair.connector.connector_specific_config == _WIDENED_CONFIG
    [pending] = slack_pair.pending_backfills
    assert pending.backfill.window_start == _INDEXING_START_UTC
    assert pending.backfill.window_end > before_apply
    assert pending.backfill.connector_config_override == {"channels": ["new"]}
    assert pending.requested_at == pending.backfill.window_end
    # Nothing else is requested.
    assert slack_pair.indexing_trigger is None
    assert slack_pair.prune_requested_at is None

    record_kwargs = validation.record.call_args.kwargs
    assert record_kwargs["trigger"] == CapabilityCheckTrigger.CONNECTOR_CONFIG_UPDATE
    assert record_kwargs["cc_pair_id"] == slack_pair.id
    assert record_kwargs["connector_specific_config"] == _WIDENED_CONFIG

    # Single use.
    assert load_edit_plan(stored.plan_id, slack_pair.id) is None
    with pytest.raises(OnyxError) as exc:
        load_plan_for_user(stored.plan_id, slack_pair.id, admin)
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND

    assert applied.audit.field_changes[0].field_name == "channels"
    assert applied.audit.field_changes[0].added_item_count == 1
    assert applied.audit.old_credential_id == applied.audit.new_credential_id


def test_scope_narrowing_requests_a_prune(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    stored = _plan(
        db_session, slack_pair, admin, connector_specific_config=_NARROWED_CONFIG
    )
    _apply(db_session, stored, admin)

    _reload(db_session, slack_pair)
    assert slack_pair.connector.connector_specific_config == _NARROWED_CONFIG
    assert slack_pair.prune_requested_at is not None
    assert slack_pair.pending_backfills == []
    assert slack_pair.indexing_trigger is None


def test_added_full_reindex_steps_set_the_reindex_requests(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    stored = _plan(db_session, slack_pair, admin, name="renamed", refresh_freq=3600)
    applied = _apply(
        db_session,
        stored,
        admin,
        EditPlanChoices(added_steps=[EditStepKind.FULL_REINDEX_THEN_PRUNE]),
    )

    assert [step.kind for step in applied.steps] == [
        EditStepKind.FULL_REINDEX_THEN_PRUNE
    ]
    _reload(db_session, slack_pair)
    assert slack_pair.name == "renamed"
    assert slack_pair.connector.refresh_freq == 3600
    assert slack_pair.indexing_trigger == IndexingMode.REINDEX
    assert slack_pair.prune_after_reindex_requested_at is not None

    stored = _plan(db_session, slack_pair, admin, name="renamed again")
    _apply(
        db_session,
        stored,
        admin,
        EditPlanChoices(added_steps=[EditStepKind.FULL_REINDEX]),
    )
    _reload(db_session, slack_pair)
    assert slack_pair.indexing_trigger == IndexingMode.REINDEX


def test_running_attempt_is_restarted(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    attempt = IndexAttempt(
        connector_credential_pair_id=slack_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"edit_apply_{uuid4().hex[:8]}",
    )
    db_session.add(attempt)
    db_session.commit()
    stored = _plan(
        db_session, slack_pair, admin, connector_specific_config=_WIDENED_CONFIG
    )
    assert EditStepKind.RESTART_ATTEMPT in [step.kind for step in stored.plan.steps]

    applied = _apply(db_session, stored, admin)

    assert applied.restarted_task_ids == [attempt.celery_task_id]
    db_session.expire_all()
    assert attempt.cancellation_requested
    _reload(db_session, slack_pair)
    assert slack_pair.indexing_trigger == IndexingMode.UPDATE
    assert len(slack_pair.pending_backfills) == 1


def test_attempt_started_after_planning_is_restarted(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    stored = _plan(
        db_session, slack_pair, admin, connector_specific_config=_NARROWED_CONFIG
    )
    attempt = IndexAttempt(
        connector_credential_pair_id=slack_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"edit_apply_{uuid4().hex[:8]}",
    )
    db_session.add(attempt)
    db_session.commit()

    applied = _apply(db_session, stored, admin)

    assert applied.restarted_task_ids == [attempt.celery_task_id]


def test_cosmetic_edit_does_not_restart_an_attempt_started_after_planning(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    stored = _plan(
        db_session,
        slack_pair,
        admin,
        connector_specific_config=_STORED_CONFIG | {"batch_size": 7},
    )
    attempt = IndexAttempt(
        connector_credential_pair_id=slack_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"edit_apply_{uuid4().hex[:8]}",
    )
    db_session.add(attempt)
    db_session.commit()

    applied = _apply(db_session, stored, admin)

    assert applied.restarted_task_ids == []
    db_session.expire_all()
    assert not attempt.cancellation_requested


def test_stale_plan_writes_nothing(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,
) -> None:
    stored = _plan(
        db_session,
        slack_pair,
        admin,
        connector_specific_config=_WIDENED_CONFIG,
        name="renamed",
    )
    slack_pair.connector.connector_specific_config = {"channels": ["other"]}
    db_session.commit()

    with pytest.raises(OnyxError) as exc:
        _apply(db_session, stored, admin)

    assert exc.value.error_code == OnyxErrorCode.EDIT_PLAN_STALE
    validation.record.assert_not_called()
    _reload(db_session, slack_pair)
    assert slack_pair.name != "renamed"
    assert slack_pair.pending_backfills == []
    assert load_edit_plan(stored.plan_id, slack_pair.id) is not None


def test_failed_validation_writes_nothing(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,
) -> None:
    stored = _plan(
        db_session,
        slack_pair,
        admin,
        connector_specific_config=_NARROWED_CONFIG,
        name="renamed",
    )
    validation.record.side_effect = ConnectorValidationError("bot not in channel")

    with pytest.raises(OnyxError) as exc:
        _apply(db_session, stored, admin)

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "bot not in channel" in exc.value.detail
    _reload(db_session, slack_pair)
    assert slack_pair.connector.connector_specific_config == _STORED_CONFIG
    assert slack_pair.name != "renamed"
    assert slack_pair.prune_requested_at is None
    # The admin can fix the source and apply the same plan.
    assert load_edit_plan(stored.plan_id, slack_pair.id) is not None


def test_invalid_frequency_writes_nothing(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    stored = _plan(
        db_session,
        slack_pair,
        admin,
        connector_specific_config=_NARROWED_CONFIG,
        refresh_freq=1,
    )
    with pytest.raises(OnyxError) as exc:
        _apply(db_session, stored, admin)

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    _reload(db_session, slack_pair)
    assert slack_pair.connector.connector_specific_config == _STORED_CONFIG
    assert slack_pair.prune_requested_at is None


def test_validated_edit_reactivates_an_invalid_pair(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    slack_pair.status = ConnectorCredentialPairStatus.INVALID
    db_session.commit()
    notify_admins_of_connector_alert(
        db_session,
        slack_pair.id,
        NotificationType.CONNECTOR_INVALID,
        "invalid",
        "invalid",
    )

    # A rename runs no validation, so the pair stays invalid.
    stored = _plan(db_session, slack_pair, admin, name="renamed")
    assert not _apply(db_session, stored, admin).reactivated
    _reload(db_session, slack_pair)
    assert slack_pair.status == ConnectorCredentialPairStatus.INVALID

    stored = _plan(
        db_session, slack_pair, admin, connector_specific_config=_NARROWED_CONFIG
    )
    applied = _apply(db_session, stored, admin)

    assert applied.reactivated
    assert applied.audit.reactivated
    _reload(db_session, slack_pair)
    assert slack_pair.status == ConnectorCredentialPairStatus.ACTIVE
    alerts = db_session.scalars(
        select(Notification).where(
            Notification.notif_type == NotificationType.CONNECTOR_INVALID,
            Notification.additional_data["cc_pair_id"].astext == str(slack_pair.id),
        )
    ).all()
    assert alerts == []


def test_credential_swap_moves_the_documents(
    db_session: Session,
    # Before the pair: its teardown runs after the pair lets go of it.
    other_credential: Credential,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    doc_ids = seed_cc_pair_documents(
        db_session, slack_pair, 2, prefix=f"edit-apply-{uuid4().hex[:6]}-"
    )
    db_session.commit()
    old_credential_id = slack_pair.credential_id
    stored = _plan(db_session, slack_pair, admin, credential_id=other_credential.id)

    applied = _apply(
        db_session,
        stored,
        admin,
        EditPlanChoices(credential_path=CredentialPath.FULL_REINDEX_AND_PRUNE),
    )

    _reload(db_session, slack_pair)
    assert slack_pair.credential_id == other_credential.id
    rows = db_session.scalars(
        select(DocumentByConnectorCredentialPair).where(
            DocumentByConnectorCredentialPair.id.in_(doc_ids)
        )
    ).all()
    assert {row.credential_id for row in rows} == {other_credential.id}
    assert slack_pair.prune_after_reindex_requested_at is not None
    assert applied.audit.old_credential_id == old_credential_id
    assert applied.audit.new_credential_id == other_credential.id


def test_access_change_is_applied(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    group: UserGroup,
    admin: User,
    validation: _Validation,  # noqa: ARG001
    enable_ee: None,  # noqa: ARG001
) -> None:
    stored = _plan(
        db_session,
        slack_pair,
        admin,
        access_type=AccessType.PRIVATE,
        data_access_group_ids=[group.id],
    )
    assert [step.kind for step in stored.plan.steps] == [EditStepKind.ACCESS_TYPE]

    applied = _apply(db_session, stored, admin)

    _reload(db_session, slack_pair)
    assert slack_pair.access_type == AccessType.PRIVATE
    state = fetch_current_pair_state(db_session, slack_pair.id)
    assert state.data_access_group_ids == [group.id]
    assert applied.audit.old_access_type == AccessType.PUBLIC
    assert applied.audit.new_access_type == AccessType.PRIVATE
    assert applied.audit.new_data_access_group_ids == [group.id]


def test_plan_is_private_and_single_use(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    other_admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    stored = _plan(db_session, slack_pair, admin, name="renamed")

    with pytest.raises(OnyxError) as exc:
        load_plan_for_user(stored.plan_id, slack_pair.id, other_admin)
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND
    with pytest.raises(OnyxError) as exc:
        load_plan_for_user(stored.plan_id, slack_pair.id + 1, admin)
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND

    loaded = load_plan_for_user(stored.plan_id, slack_pair.id, admin)
    _apply(db_session, stored, admin)
    # A second apply that loaded the plan before the first committed.
    with pytest.raises(OnyxError) as exc:
        apply_connector_edit(
            db_session, stored=loaded, choices=EditPlanChoices(), user=admin
        )
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND


def test_deleting_pair_is_refused(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    stored = _plan(db_session, slack_pair, admin, name="renamed")
    slack_pair.status = ConnectorCredentialPairStatus.DELETING
    db_session.commit()

    with pytest.raises(OnyxError) as exc:
        _apply(db_session, stored, admin)
    assert exc.value.error_code == OnyxErrorCode.CONFLICT


def test_config_edit_supersedes_an_outstanding_scoped_backfill(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    slack_pair.pending_backfills = [
        PendingBackfill(
            request_id=uuid4(),
            requested_at=_PLAN_TIME_END,
            backfill=BackfillSpec(
                window_start=_INDEXING_START_UTC,
                window_end=_PLAN_TIME_END,
                connector_config_override={"channels": ["random"]},
            ),
        )
    ]
    db_session.commit()

    stored = _plan(
        db_session, slack_pair, admin, connector_specific_config=_NARROWED_CONFIG
    )

    # The required re-index does not merge with the optional prune.
    [reindex, prune] = stored.plan.steps
    assert reindex.kind == EditStepKind.FULL_REINDEX
    assert reindex.required
    assert reindex.reasons == [EditStepReason.SCOPED_BACKFILL_SUPERSEDED]
    assert prune.kind == EditStepKind.PRUNE
    assert not prune.required


def test_authorization_rejections(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    other_admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    basic = create_test_user(db_session, "edit_apply_basic")
    hidden = Credential(
        source=DocumentSource.SLACK,
        credential_json={},
        user_id=other_admin.id,
        admin_public=False,
    )
    github = Credential(source=DocumentSource.GITHUB, credential_json={})
    db_session.add_all([hidden, github])
    db_session.commit()
    try:
        # Not an Editor of the pair.
        with pytest.raises(OnyxError) as exc:
            _authorize_pair_edit(db_session, basic, slack_pair.id)
        assert exc.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        _authorize_pair_edit(db_session, admin, slack_pair.id)

        # The groupless creator of a private pair is its Editor, but the
        # connector is shared with a pair they cannot edit.
        slack_pair.creator_id = basic.id
        slack_pair.access_type = AccessType.PRIVATE
        sibling = ConnectorCredentialPair(
            connector_id=slack_pair.connector_id,
            credential_id=github.id,
            name=f"edit-apply-sibling-{uuid4().hex[:6]}",
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.PUBLIC,
        )
        db_session.add(sibling)
        db_session.commit()
        with pytest.raises(OnyxError) as exc:
            _authorize_pair_edit(db_session, basic, slack_pair.id)
        assert exc.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        db_session.delete(sibling)
        db_session.commit()
        _authorize_pair_edit(db_session, basic, slack_pair.id)
        slack_pair.creator_id = None
        slack_pair.access_type = AccessType.PUBLIC
        db_session.commit()

        current = fetch_current_pair_state(db_session, slack_pair.id)
        # A credential the user cannot see, and one of another source.
        with pytest.raises(OnyxError) as exc:
            _authorize_proposed_state(
                db_session,
                admin,
                current,
                _proposed(db_session, slack_pair, credential_id=hidden.id),
            )
        assert exc.value.error_code == OnyxErrorCode.CREDENTIAL_NOT_FOUND
        with pytest.raises(OnyxError) as exc:
            _authorize_proposed_state(
                db_session,
                admin,
                current,
                _proposed(db_session, slack_pair, credential_id=github.id),
            )
        assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT

        # GATE 2: a user without global authority cannot change access, except
        # to a groupless perm-synced type, as at creation.
        with pytest.raises(OnyxError) as exc:
            _authorize_proposed_state(
                db_session,
                basic,
                current,
                _proposed(db_session, slack_pair, access_type=AccessType.PRIVATE),
            )
        assert exc.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        _authorize_proposed_state(
            db_session,
            basic,
            current,
            _proposed(db_session, slack_pair, access_type=AccessType.SYNC),
        )
    finally:
        db_session.rollback()
        db_session.execute(
            delete(Credential).where(Credential.id.in_([hidden.id, github.id]))
        )
        db_session.commit()
        delete_test_user(db_session, basic)
        db_session.commit()


def _pending(
    start: datetime, end: datetime, attempt_id: int | None = None
) -> PendingBackfill:
    return PendingBackfill(
        request_id=uuid4(),
        requested_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        backfill=BackfillSpec(window_start=start, window_end=end),
        attempt_id=attempt_id,
    )


def test_later_indexing_start_clips_pending_backfills(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    def utc(year: int, month: int) -> datetime:
        return datetime(year, month, 1, tzinfo=timezone.utc)

    new_start = utc(2025, 3)
    running = IndexAttempt(
        connector_credential_pair_id=slack_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"edit_apply_{uuid4().hex[:8]}",
        is_backfill=True,
    )
    db_session.add(running)
    db_session.commit()
    straddling = _pending(utc(2025, 1), utc(2025, 5))
    before = _pending(utc(2025, 1), utc(2025, 2))
    after = _pending(utc(2025, 4), utc(2025, 5))
    tracked = _pending(utc(2025, 1), utc(2025, 6), attempt_id=running.id)
    slack_pair.pending_backfills = [straddling, before, after, tracked]
    db_session.commit()

    stored = _plan(db_session, slack_pair, admin, indexing_start=new_start)
    applied = _apply(db_session, stored, admin)

    # The running backfill restarts, so its request is released and clipped.
    assert applied.restarted_task_ids == [running.celery_task_id]
    _reload(db_session, slack_pair)
    by_id = {pending.request_id: pending for pending in slack_pair.pending_backfills}
    assert set(by_id) == {straddling.request_id, after.request_id, tracked.request_id}
    assert by_id[straddling.request_id].backfill.window_start == new_start
    assert by_id[straddling.request_id].backfill.window_end == utc(2025, 5)
    assert by_id[after.request_id] == after
    assert by_id[tracked.request_id].backfill.window_start == new_start
    assert by_id[tracked.request_id].attempt_id is None


def test_earlier_indexing_start_keeps_pending_backfills(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    pending = _pending(
        datetime(2025, 2, 1, tzinfo=timezone.utc),
        datetime(2025, 5, 1, tzinfo=timezone.utc),
    )
    slack_pair.pending_backfills = [pending]
    db_session.commit()

    stored = _plan(
        db_session,
        slack_pair,
        admin,
        indexing_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    _apply(db_session, stored, admin)

    _reload(db_session, slack_pair)
    assert pending in slack_pair.pending_backfills


def test_failed_commit_leaves_the_plan_usable(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _plan(
        db_session, slack_pair, admin, connector_specific_config=_NARROWED_CONFIG
    )
    real_commit = db_session.commit

    def failing_commit() -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db_session, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        _apply(db_session, stored, admin)
    monkeypatch.setattr(db_session, "commit", real_commit)

    _reload(db_session, slack_pair)
    assert slack_pair.connector.connector_specific_config == _STORED_CONFIG
    assert load_edit_plan(stored.plan_id, slack_pair.id) is not None

    _apply(db_session, stored, admin)
    _reload(db_session, slack_pair)
    assert slack_pair.connector.connector_specific_config == _NARROWED_CONFIG
    assert load_edit_plan(stored.plan_id, slack_pair.id) is None


def test_second_apply_of_a_settings_only_plan_is_refused(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    # A rename leaves the base state as it was, so only the plan's claim and
    # its deletion refuse a second apply.
    stored = _plan(db_session, slack_pair, admin, name="renamed")
    loaded = load_plan_for_user(stored.plan_id, slack_pair.id, admin)

    # Another apply of the plan holds the claim.
    assert claim_edit_plan_for_apply(stored.plan_id)
    with pytest.raises(OnyxError) as exc:
        apply_connector_edit(
            db_session, stored=loaded, choices=EditPlanChoices(), user=admin
        )
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    release_edit_plan_claim(stored.plan_id)

    _apply(db_session, stored, admin)
    _reload(db_session, slack_pair)
    assert slack_pair.name == "renamed"
    with pytest.raises(OnyxError) as exc:
        apply_connector_edit(
            db_session, stored=loaded, choices=EditPlanChoices(), user=admin
        )
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND
