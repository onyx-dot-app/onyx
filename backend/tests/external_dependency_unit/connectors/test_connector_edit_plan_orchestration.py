"""Planning a connector edit against a real pair: the current state comes from
the DB, the plan gets the inputs the pair's state implies, validation runs on
the proposed state only when something it checks changed, and the stored plan
is scoped to its pair and tied to the base state it was computed from. Nothing
but the plan store is written (the validation itself is mocked here)."""

from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import DocumentSource
from onyx.connectors import pairing_access
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CredentialCapability,
    ProposedPairingValidation,
)
from onyx.connectors.edit_plan import orchestration
from onyx.connectors.edit_plan.constants import EDIT_PLAN_TTL_SECONDS
from onyx.connectors.edit_plan.models import (
    EditNoteKind,
    EditStepKind,
    ProposedPairState,
)
from onyx.connectors.edit_plan.orchestration import (
    plan_connector_edit,
    with_latest_dry_run_results,
)
from onyx.connectors.edit_plan.state import fetch_current_pair_state
from onyx.connectors.edit_plan.store import (
    ensure_base_state_matches,
    load_edit_plan,
)
from onyx.connectors.models import InputType
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    IndexingStatus,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    Credential,
    IndexAttempt,
    User,
    UserGroup,
    UserGroup__CCPairDataAccess,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_user_group,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    seed_cc_pair_documents,
)

_STORED_CONFIG: dict[str, Any] = {"channels": ["general"]}
_WIDENED_CONFIG: dict[str, Any] = {"channels": ["general", "random"]}
_INDEXING_START = datetime(2025, 1, 1)


class _Validation:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.validate = MagicMock(return_value=ProposedPairingValidation())
        self.dry_run_results = [
            CapabilityCheckResult(
                capability=CredentialCapability.INDEXING,
                check_id="slow",
                display_name="Slow",
                required=True,
                status=CapabilityCheckStatus.PASSED,
            )
        ]
        self.read_dry_runs = MagicMock(return_value=self.dry_run_results)
        monkeypatch.setattr(orchestration, "validate_proposed_pairing", self.validate)
        monkeypatch.setattr(
            orchestration, "get_cc_pair_dry_run_results", self.read_dry_runs
        )


@pytest.fixture
def validation(monkeypatch: pytest.MonkeyPatch) -> _Validation:
    return _Validation(monkeypatch)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "edit_plan_admin", is_admin=True)
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
def groups(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[UserGroup], None, None]:
    created = [create_test_user_group(db_session, members=[]) for _ in range(2)]
    yield created
    db_session.rollback()
    group_ids = [group.id for group in created]
    db_session.execute(
        delete(UserGroup__CCPairDataAccess).where(
            UserGroup__CCPairDataAccess.user_group_id.in_(group_ids)
        )
    )
    db_session.execute(delete(UserGroup).where(UserGroup.id.in_(group_ids)))
    db_session.commit()


def _proposed(
    db_session: Session, pair: ConnectorCredentialPair, **changes: Any
) -> ProposedPairState:
    current = fetch_current_pair_state(db_session, pair.id)
    return ProposedPairState.model_validate(
        current.model_dump(exclude={"cc_pair_id", "connector_id", "status"}) | changes
    )


def test_state_builder_reads_the_pair(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    groups: list[UserGroup],
    enable_ee: None,  # noqa: ARG001
) -> None:
    slack_pair.access_type = AccessType.PRIVATE
    for group in reversed(groups):
        db_session.add(
            UserGroup__CCPairDataAccess(
                cc_pair_id=slack_pair.id, user_group_id=group.id
            )
        )
    db_session.commit()

    state = fetch_current_pair_state(db_session, slack_pair.id)

    assert state.cc_pair_id == slack_pair.id
    assert state.connector_id == slack_pair.connector_id
    assert state.status == ConnectorCredentialPairStatus.ACTIVE
    assert state.source == DocumentSource.SLACK
    assert state.input_type == InputType.POLL
    assert state.connector_specific_config == _STORED_CONFIG
    assert state.access_type == AccessType.PRIVATE
    assert state.data_access_group_ids == sorted(group.id for group in groups)
    assert state.credential_id == slack_pair.credential_id
    assert state.indexing_start == _INDEXING_START.replace(tzinfo=timezone.utc)
    assert state.name == slack_pair.name


def test_state_builder_raises_for_a_missing_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    with pytest.raises(OnyxError) as exc:
        fetch_current_pair_state(db_session, -1)
    assert exc.value.error_code == OnyxErrorCode.CONNECTOR_NOT_FOUND


def test_plan_for_a_widened_scope(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,
) -> None:
    seed_cc_pair_documents(
        db_session, slack_pair, 3, prefix=f"edit-plan-{uuid4().hex[:6]}-"
    )
    proposed = _proposed(
        db_session, slack_pair, connector_specific_config=_WIDENED_CONFIG
    )

    stored = plan_connector_edit(
        db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
    )

    plan = stored.plan
    assert [step.kind for step in plan.steps] == [EditStepKind.SCOPED_BACKFILL]
    backfill = plan.steps[0].backfill
    assert backfill is not None
    assert backfill.window_start == _INDEXING_START.replace(tzinfo=timezone.utc)
    assert backfill.connector_config_override == {"channels": ["random"]}
    assert plan.indexed_document_count == 3
    assert plan.dry_run_results == validation.dry_run_results
    assert plan.validation == ProposedPairingValidation()

    validate_kwargs = validation.validate.call_args.kwargs
    assert validate_kwargs["cc_pair_id"] == slack_pair.id
    assert validate_kwargs["connector_specific_config"] == _WIDENED_CONFIG
    assert validate_kwargs["access_type"] == AccessType.PUBLIC

    # Only the plan store is written.
    db_session.expire_all()
    assert slack_pair.connector.connector_specific_config == _STORED_CONFIG

    loaded = load_edit_plan(stored.plan_id, slack_pair.id)
    assert loaded == stored
    assert loaded.user_id == admin.id
    assert loaded.proposed == proposed
    ttl = get_cache_backend().ttl(f"connector_edit_plan:{stored.plan_id}")
    assert EDIT_PLAN_TTL_SECONDS - 60 < ttl <= EDIT_PLAN_TTL_SECONDS


def test_settings_and_group_edits_skip_validation(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,
) -> None:
    proposed = _proposed(db_session, slack_pair, name="renamed")

    stored = plan_connector_edit(
        db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
    )

    assert stored.plan.validation is None
    assert stored.plan.changed_settings == ["name"]
    validation.validate.assert_not_called()


def test_group_only_edit_skips_validation(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    groups: list[UserGroup],
    admin: User,
    validation: _Validation,
    enable_ee: None,  # noqa: ARG001
) -> None:
    slack_pair.access_type = AccessType.PRIVATE
    db_session.add(
        UserGroup__CCPairDataAccess(
            cc_pair_id=slack_pair.id, user_group_id=groups[0].id
        )
    )
    db_session.commit()
    proposed = _proposed(
        db_session,
        slack_pair,
        data_access_group_ids=[group.id for group in groups],
    )

    stored = plan_connector_edit(
        db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
    )

    assert [step.kind for step in stored.plan.steps] == [EditStepKind.ACCESS_GROUPS]
    assert stored.plan.validation is None
    validation.validate.assert_not_called()


def test_access_change_runs_the_access_gates(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pairing_access,
        "get_security_settings",
        lambda: MagicMock(allow_connector_group_restrictions=True),
    )
    # A restricted pair needs a data-access group.
    proposed = _proposed(db_session, slack_pair, access_type=AccessType.SYNC_RESTRICTED)

    with pytest.raises(OnyxError) as exc:
        plan_connector_edit(
            db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
        )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_rename_of_a_pair_without_a_connector_class(
    db_session: Session,
    admin: User,
    validation: _Validation,
    tenant_context: None,  # noqa: ARG001
) -> None:
    pair = make_cc_pair(db_session, source=DocumentSource.INGESTION_API)
    try:
        proposed = _proposed(db_session, pair, name="renamed")

        stored = plan_connector_edit(
            db_session, cc_pair_id=pair.id, proposed=proposed, user=admin
        )

        assert stored.plan.changed_settings == ["name"]
        assert stored.plan.steps == []
        validation.validate.assert_not_called()
        # No connector class: the stored plan comes back without a dry run.
        assert with_latest_dry_run_results(db_session, stored) == stored
    finally:
        db_session.rollback()
        cleanup_cc_pair(db_session, pair)


def test_credential_change_validates_the_new_credential(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    other_credential: Credential,
    admin: User,
    validation: _Validation,
) -> None:
    proposed = _proposed(db_session, slack_pair, credential_id=other_credential.id)

    stored = plan_connector_edit(
        db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
    )

    assert stored.plan.credential_choice is not None
    assert validation.validate.call_args.kwargs["credential"].id == other_credential.id
    assert validation.read_dry_runs.call_args.kwargs["credential"].id == (
        other_credential.id
    )


def test_plan_refresh_refuses_a_deleted_proposed_credential(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    other_credential: Credential,
    admin: User,
    validation: _Validation,
) -> None:
    proposed = _proposed(db_session, slack_pair, credential_id=other_credential.id)
    stored = plan_connector_edit(
        db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
    )
    refreshed = with_latest_dry_run_results(db_session, stored)
    assert refreshed.plan.dry_run_results == validation.dry_run_results

    db_session.execute(delete(Credential).where(Credential.id == other_credential.id))
    db_session.commit()

    with pytest.raises(OnyxError) as exc:
        with_latest_dry_run_results(db_session, stored)
    assert exc.value.error_code == OnyxErrorCode.CREDENTIAL_NOT_FOUND


def test_credential_of_another_source_is_rejected(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    credential = Credential(source=DocumentSource.GITHUB, credential_json={})
    db_session.add(credential)
    db_session.commit()
    try:
        proposed = _proposed(db_session, slack_pair, credential_id=credential.id)
        with pytest.raises(OnyxError) as exc:
            plan_connector_edit(
                db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
            )
        assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    finally:
        db_session.rollback()
        db_session.execute(delete(Credential).where(Credential.id == credential.id))
        db_session.commit()


def test_invalid_config_is_rejected(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,
) -> None:
    proposed = _proposed(
        db_session, slack_pair, connector_specific_config={"channels": 5}
    )

    with pytest.raises(OnyxError) as exc:
        plan_connector_edit(
            db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
        )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    validation.validate.assert_not_called()


def test_running_attempt_is_restarted(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    db_session.add(
        IndexAttempt(
            connector_credential_pair_id=slack_pair.id,
            search_settings_id=get_current_search_settings(db_session).id,
            from_beginning=False,
            status=IndexingStatus.IN_PROGRESS,
        )
    )
    db_session.commit()
    proposed = _proposed(
        db_session, slack_pair, connector_specific_config=_WIDENED_CONFIG
    )

    stored = plan_connector_edit(
        db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
    )

    assert [step.kind for step in stored.plan.steps] == [
        EditStepKind.RESTART_ATTEMPT,
        EditStepKind.SCOPED_BACKFILL,
    ]
    assert EditNoteKind.ATTEMPT_RESTARTED in [note.kind for note in stored.plan.notes]


def test_deleting_pair_is_refused_before_validation(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,
) -> None:
    proposed = _proposed(
        db_session, slack_pair, connector_specific_config=_WIDENED_CONFIG
    )
    slack_pair.status = ConnectorCredentialPairStatus.DELETING
    db_session.commit()

    with pytest.raises(OnyxError) as exc:
        plan_connector_edit(
            db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
        )
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    validation.validate.assert_not_called()


def test_stored_plan_is_scoped_to_its_pair_and_base_state(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    admin: User,
    validation: _Validation,  # noqa: ARG001
) -> None:
    proposed = _proposed(
        db_session, slack_pair, connector_specific_config=_WIDENED_CONFIG
    )
    stored = plan_connector_edit(
        db_session, cc_pair_id=slack_pair.id, proposed=proposed, user=admin
    )

    assert load_edit_plan(stored.plan_id, slack_pair.id + 1) is None
    assert load_edit_plan(uuid4(), slack_pair.id) is None

    # A rename is not part of the base state.
    slack_pair.name = "renamed"
    db_session.commit()
    ensure_base_state_matches(
        stored, fetch_current_pair_state(db_session, slack_pair.id)
    )

    slack_pair.connector.connector_specific_config = {"channels": ["other"]}
    db_session.commit()
    with pytest.raises(OnyxError) as exc:
        ensure_base_state_matches(
            stored, fetch_current_pair_state(db_session, slack_pair.id)
        )
    assert exc.value.error_code == OnyxErrorCode.EDIT_PLAN_STALE
