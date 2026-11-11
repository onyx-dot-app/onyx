"""A group sync records each user or group its source skipped as a
sync_attempt_error row on the attempt, and still completes."""

from collections.abc import Generator
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.external_group_syncing import (
    tasks as group_tasks,
)
from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.db.sync_attempt_error import create_sync_attempt_error
from ee.onyx.external_permissions.models import SyncEntityFailure
from ee.onyx.external_permissions.perm_sync_types import GroupSyncFuncType
from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType, PermissionSyncStatus, SyncEntityKind
from onyx.db.index_attempt import MAX_INDEX_ATTEMPT_ERROR_MESSAGE_CHARS
from onyx.db.models import ConnectorCredentialPair, SyncAttemptError
from onyx.db.permission_sync_attempt import (
    PermissionSyncAttemptLostError,
    get_external_group_sync_attempt,
    mark_external_group_sync_attempt_in_progress,
    try_create_external_group_sync_attempt,
)
from shared_configs.configs import (
    POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE as TEST_TENANT_ID,
)
from tests.external_dependency_unit.permission_sync.conftest import (
    create_test_connector_credential_pair,
)


@pytest.fixture
def cc_pair(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> ConnectorCredentialPair:
    return create_test_connector_credential_pair(
        db_session, source=DocumentSource.GOOGLE_DRIVE, access_type=AccessType.SYNC
    )


def _create_attempt(cc_pair: ConnectorCredentialPair, db_session: Session) -> int:
    attempt_id = try_create_external_group_sync_attempt(
        cc_pair.id, f"task-{uuid4().hex}", db_session
    )
    assert attempt_id is not None
    return attempt_id


def _run_group_sync(
    cc_pair: ConnectorCredentialPair, attempt_id: int, group_sync: GroupSyncFuncType
) -> None:
    sync_config = Mock()
    sync_config.group_sync_config.group_sync_func = group_sync
    with patch.object(
        group_tasks, "get_source_perm_sync_config", return_value=sync_config
    ):
        group_tasks.connector_external_group_sync_generator_task.apply(
            args=(cc_pair.id,),
            kwargs={"tenant_id": TEST_TENANT_ID, "attempt_id": attempt_id},
        ).get()


def _errors_for(db_session: Session, attempt_id: int) -> list[SyncAttemptError]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(SyncAttemptError).where(
                SyncAttemptError.external_group_sync_attempt_id == attempt_id
            )
        ).all()
    )


def test_entity_failure_writes_a_row_and_the_sync_completes(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    suffix = uuid4().hex[:8]

    def _group_sync(
        tenant_id: str,  # noqa: ARG001
        cc_pair: ConnectorCredentialPair,  # noqa: ARG001
    ) -> Generator[ExternalUserGroup | SyncEntityFailure, None, None]:
        yield ExternalUserGroup(id="a", user_emails=[f"a_{suffix}@example.com"])
        yield SyncEntityFailure(
            kind=SyncEntityKind.USER,
            id=f"broken_{suffix}@example.com",
            name="Broken User",
            message="403 Forbidden",
        )
        yield ExternalUserGroup(id="b", user_emails=[f"b_{suffix}@example.com"])

    attempt_id = _create_attempt(cc_pair, db_session)
    _run_group_sync(cc_pair, attempt_id, _group_sync)

    errors = _errors_for(db_session, attempt_id)
    assert len(errors) == 1
    error = errors[0]
    assert error.connector_credential_pair_id == cc_pair.id
    assert error.entity_kind == SyncEntityKind.USER
    assert error.entity_id == f"broken_{suffix}@example.com"
    assert error.entity_name == "Broken User"
    assert error.failure_message == "403 Forbidden"
    assert error.is_resolved is False
    assert error.resolved_reason is None

    attempt = get_external_group_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.COMPLETED_WITH_ERRORS
    assert attempt.total_groups_processed == 2


def test_raising_source_writes_no_row_and_fails_the_sync(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    def _group_sync(
        tenant_id: str,  # noqa: ARG001
        cc_pair: ConnectorCredentialPair,  # noqa: ARG001
    ) -> Generator[ExternalUserGroup | SyncEntityFailure, None, None]:
        yield ExternalUserGroup(id="a", user_emails=[])
        raise RuntimeError("source is down")

    attempt_id = _create_attempt(cc_pair, db_session)
    with pytest.raises(RuntimeError, match="source is down"):
        _run_group_sync(cc_pair, attempt_id, _group_sync)

    assert _errors_for(db_session, attempt_id) == []
    attempt = get_external_group_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.FAILED
    assert attempt.error_message == "source is down"


def test_row_message_is_capped(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    attempt_id = _create_attempt(cc_pair, db_session)
    mark_external_group_sync_attempt_in_progress(attempt_id, db_session)

    create_sync_attempt_error(
        db_session,
        attempt_id,
        cc_pair.id,
        SyncEntityFailure(
            kind=SyncEntityKind.USER,
            id="long@example.com",
            message="x" * (MAX_INDEX_ATTEMPT_ERROR_MESSAGE_CHARS * 2),
        ),
    )

    [error] = _errors_for(db_session, attempt_id)
    assert len(error.failure_message) <= MAX_INDEX_ATTEMPT_ERROR_MESSAGE_CHARS
    assert error.failure_message.endswith("chars truncated]")


def test_lost_attempt_files_no_row(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    # Not IN_PROGRESS, like an attempt the reaper has failed.
    attempt_id = _create_attempt(cc_pair, db_session)

    with pytest.raises(PermissionSyncAttemptLostError):
        create_sync_attempt_error(
            db_session,
            attempt_id,
            cc_pair.id,
            SyncEntityFailure(
                kind=SyncEntityKind.USER, id="late@example.com", message="403"
            ),
        )
    db_session.rollback()

    assert _errors_for(db_session, attempt_id) == []
