"""
The open DocPermissionSyncAttempt row is the per-cc_pair doc permission sync
lock: dispatch creates it, the task claims it, and nothing in Redis is needed.
"""

from collections.abc import Generator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.doc_permission_syncing import tasks as perm_tasks
from ee.onyx.external_permissions.perm_sync_types import (
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
)
from ee.onyx.external_permissions.sync_params import DocSyncConfig, SyncConfig
from onyx.access.models import (
    DocExternalAccess,
    ElementExternalAccess,
    ExternalAccess,
)
from onyx.configs.constants import PERMISSION_SYNC_TASK_EXPIRES, DocumentSource
from onyx.db.enums import AccessType, PermissionSyncStatus
from onyx.db.models import ConnectorCredentialPair, Document
from onyx.db.permission_sync_attempt import (
    PermissionSyncAttemptLostError,
    cancel_open_doc_permission_sync_attempt,
    get_cc_pair_ids_with_open_doc_permission_sync_attempt,
    get_doc_permission_sync_attempt,
    get_open_doc_permission_sync_attempt,
    mark_doc_permission_sync_attempt_failed,
    mark_doc_permission_sync_attempt_in_progress,
    try_create_doc_permission_sync_attempt,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
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
        db_session, source=DocumentSource.JIRA, access_type=AccessType.SYNC
    )


def _task_id() -> str:
    return f"task-{uuid4().hex[:8]}"


def test_one_open_attempt_per_cc_pair(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    first = try_create_doc_permission_sync_attempt(cc_pair.id, _task_id(), db_session)
    assert first is not None
    assert (
        try_create_doc_permission_sync_attempt(cc_pair.id, _task_id(), db_session)
        is None
    )
    assert cc_pair.id in get_cc_pair_ids_with_open_doc_permission_sync_attempt(
        db_session
    )

    mark_doc_permission_sync_attempt_failed(first, db_session, error_message="boom")
    assert get_open_doc_permission_sync_attempt(cc_pair.id, db_session) is None
    assert (
        try_create_doc_permission_sync_attempt(cc_pair.id, _task_id(), db_session)
        is not None
    )


def test_cancel_releases_the_lock(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    attempt_id = try_create_doc_permission_sync_attempt(
        cc_pair.id, _task_id(), db_session
    )
    assert attempt_id is not None

    assert (
        cancel_open_doc_permission_sync_attempt(
            cc_pair.id, db_session, reason="Canceled: test"
        )
        == attempt_id
    )
    db_session.expire_all()
    attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.CANCELED
    assert get_open_doc_permission_sync_attempt(cc_pair.id, db_session) is None


def test_dispatch_creates_the_attempt_and_sends_an_expiring_task(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    app = MagicMock()

    attempt_id = perm_tasks.try_creating_permissions_sync_task(
        app, cc_pair.id, TEST_TENANT_ID
    )
    assert attempt_id is not None
    sent = app.send_task.call_args.kwargs
    assert sent["kwargs"]["attempt_id"] == attempt_id
    assert sent["expires"] == PERMISSION_SYNC_TASK_EXPIRES

    attempt = get_open_doc_permission_sync_attempt(cc_pair.id, db_session)
    assert attempt is not None
    assert attempt.id == attempt_id
    assert attempt.celery_task_id == sent["task_id"]

    # A second dispatch while the first is open sends nothing
    app.send_task.reset_mock()
    assert (
        perm_tasks.try_creating_permissions_sync_task(app, cc_pair.id, TEST_TENANT_ID)
        is None
    )
    app.send_task.assert_not_called()


def test_failed_dispatch_releases_the_lock(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    app = MagicMock()
    app.send_task.side_effect = ConnectionError("broker down")

    assert (
        perm_tasks.try_creating_permissions_sync_task(app, cc_pair.id, TEST_TENANT_ID)
        is None
    )
    assert get_open_doc_permission_sync_attempt(cc_pair.id, db_session) is None


def test_task_skips_an_attempt_closed_while_queued(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    attempt_id = try_create_doc_permission_sync_attempt(
        cc_pair.id, _task_id(), db_session
    )
    assert attempt_id is not None
    mark_doc_permission_sync_attempt_failed(
        attempt_id, db_session, error_message="reaped while queued"
    )

    crawled: list[bool] = []

    def _fake_doc_sync(
        cc_pair: ConnectorCredentialPair,  # noqa: ARG001
        fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
        fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,  # noqa: ARG001
        callback: IndexingHeartbeatInterface | None,  # noqa: ARG001
    ) -> Generator[ElementExternalAccess, None, None]:
        crawled.append(True)
        yield from ()

    sync_config = SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=1,
            doc_sync_func=_fake_doc_sync,
            initial_index_should_sync=False,
        )
    )
    with patch.object(
        perm_tasks, "get_source_perm_sync_config", return_value=sync_config
    ):
        perm_tasks.connector_permission_sync_generator_task.apply(
            args=(cc_pair.id,),
            kwargs={"tenant_id": TEST_TENANT_ID, "attempt_id": attempt_id},
        ).get()

    assert crawled == []
    db_session.expire_all()
    attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
    assert attempt is not None
    assert attempt.error_message == "reaped while queued"


def test_writes_are_refused_after_the_attempt_is_lost(
    cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    """A worker whose attempt was failed (and maybe replaced) must not write an
    older permission snapshot over the replacement's."""
    attempt_id = try_create_doc_permission_sync_attempt(
        cc_pair.id, _task_id(), db_session
    )
    assert attempt_id is not None
    mark_doc_permission_sync_attempt_in_progress(attempt_id, db_session)
    doc_id = f"lease-doc-{uuid4().hex[:8]}"

    def write(element_id: str) -> perm_tasks.PermissionSyncResult:
        return perm_tasks.update_element_permissions_batch(
            tenant_id=TEST_TENANT_ID,
            attempt_id=attempt_id,
            new_permissions=[
                DocExternalAccess(
                    doc_id=element_id, external_access=ExternalAccess.empty()
                )
            ],
            source_string=DocumentSource.JIRA.value,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
        )

    assert write(doc_id).num_updated == 1

    mark_doc_permission_sync_attempt_failed(
        attempt_id, db_session, error_message="reaped"
    )
    with pytest.raises(PermissionSyncAttemptLostError):
        write(f"{doc_id}-late")
    assert db_session.get(Document, f"{doc_id}-late") is None
