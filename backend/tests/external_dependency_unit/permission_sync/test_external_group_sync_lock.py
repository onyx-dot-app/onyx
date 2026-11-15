"""
The open ExternalGroupPermissionSyncAttempt row is the per-cc_pair group sync
lock: dispatch creates it, the task claims it, and nothing in Redis is needed.
"""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.external_group_syncing import (
    tasks as group_tasks,
)
from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.configs.constants import PERMISSION_SYNC_TASK_EXPIRES, DocumentSource
from onyx.db.enums import AccessType, PermissionSyncStatus
from onyx.db.models import ConnectorCredentialPair, ExternalGroupPermissionSyncAttempt
from onyx.db.permission_sync_attempt import (
    cancel_open_external_group_sync_attempt,
    get_cc_pair_ids_with_open_external_group_sync_attempt,
    get_external_group_sync_attempt,
    get_open_external_group_sync_attempt,
    mark_external_group_sync_attempt_failed,
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


def test_one_open_attempt_per_cc_pair(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    first = try_create_external_group_sync_attempt(cc_pair.id, "task-1", db_session)
    assert first is not None
    assert (
        try_create_external_group_sync_attempt(cc_pair.id, "task-2", db_session) is None
    )
    assert cc_pair.id in get_cc_pair_ids_with_open_external_group_sync_attempt(
        db_session
    )

    assert (
        cancel_open_external_group_sync_attempt(
            cc_pair.id, db_session, reason="Canceled: test"
        )
        == first
    )
    assert get_open_external_group_sync_attempt(cc_pair.id, db_session) is None
    assert (
        try_create_external_group_sync_attempt(cc_pair.id, "task-3", db_session)
        is not None
    )


def test_dispatch_creates_the_attempt_and_sends_an_expiring_task(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    app = MagicMock()

    attempt_id = group_tasks.try_creating_external_group_sync_task(
        app, cc_pair.id, TEST_TENANT_ID
    )
    assert attempt_id is not None
    sent = app.send_task.call_args.kwargs
    assert sent["kwargs"]["attempt_id"] == attempt_id
    assert sent["expires"] == PERMISSION_SYNC_TASK_EXPIRES

    attempt = get_open_external_group_sync_attempt(cc_pair.id, db_session)
    assert attempt is not None
    assert attempt.celery_task_id == sent["task_id"]

    app.send_task.reset_mock()
    assert (
        group_tasks.try_creating_external_group_sync_task(
            app, cc_pair.id, TEST_TENANT_ID
        )
        is None
    )
    app.send_task.assert_not_called()


def test_task_skips_an_attempt_closed_while_queued(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    attempt_id = try_create_external_group_sync_attempt(
        cc_pair.id, "task-closed", db_session
    )
    assert attempt_id is not None
    mark_external_group_sync_attempt_failed(
        attempt_id, db_session, error_message="reaped while queued"
    )

    crawled: list[bool] = []

    def _fake_group_sync(
        tenant_id: str,  # noqa: ARG001
        cc_pair: ConnectorCredentialPair,  # noqa: ARG001
    ) -> Generator[ExternalUserGroup, None, None]:
        crawled.append(True)
        yield from ()

    sync_config = Mock()
    sync_config.group_sync_config.group_sync_func = _fake_group_sync
    with patch.object(
        group_tasks, "get_source_perm_sync_config", return_value=sync_config
    ):
        group_tasks.connector_external_group_sync_generator_task.apply(
            args=(cc_pair.id,),
            kwargs={"tenant_id": TEST_TENANT_ID, "attempt_id": attempt_id},
        ).get()

    assert crawled == []
    db_session.expire_all()
    attempt = get_external_group_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.FAILED
    assert attempt.error_message == "reaped while queued"


def test_failure_before_the_crawl_fails_the_attempt(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    """An error before the group fetch starts (e.g. a missing config) still
    closes the attempt, so the cc_pair can sync again."""
    attempt_id = try_create_external_group_sync_attempt(
        cc_pair.id, "task-no-config", db_session
    )
    assert attempt_id is not None

    with (
        patch.object(group_tasks, "get_source_perm_sync_config", return_value=None),
        pytest.raises(ValueError, match="No sync config"),
    ):
        group_tasks.connector_external_group_sync_generator_task.apply(
            args=(cc_pair.id,),
            kwargs={"tenant_id": TEST_TENANT_ID, "attempt_id": attempt_id},
        ).get()

    assert get_open_external_group_sync_attempt(cc_pair.id, db_session) is None


def test_attempt_whose_queued_task_was_lost_is_failed(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    other_cc_pair = create_test_connector_credential_pair(
        db_session, source=DocumentSource.GOOGLE_DRIVE, access_type=AccessType.SYNC
    )
    lost_id = try_create_external_group_sync_attempt(
        cc_pair.id, "task-lost", db_session
    )
    queued_id = try_create_external_group_sync_attempt(
        other_cc_pair.id, "task-queued", db_session
    )
    assert lost_id is not None and queued_id is not None
    db_session.execute(
        update(ExternalGroupPermissionSyncAttempt)
        .where(ExternalGroupPermissionSyncAttempt.id.in_([lost_id, queued_id]))
        .values(time_created=datetime.now(timezone.utc) - timedelta(hours=1))
    )
    db_session.commit()

    with (
        patch.object(group_tasks, "celery_get_broker_client"),
        patch.object(
            group_tasks, "celery_get_queued_task_ids", return_value={"task-queued"}
        ),
        patch.object(group_tasks, "celery_get_unacked_task_ids", return_value=set()),
    ):
        group_tasks.fail_lost_queued_external_group_sync_attempts(MagicMock())

    assert get_open_external_group_sync_attempt(cc_pair.id, db_session) is None
    queued = get_open_external_group_sync_attempt(other_cc_pair.id, db_session)
    assert queued is not None and queued.id == queued_id
