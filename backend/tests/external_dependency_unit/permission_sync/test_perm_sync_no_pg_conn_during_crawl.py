"""
Regression coverage for connector_permission_sync_generator_task: no DB
connection may stay checked out across the connector crawl.

On multi-tenant, get_session_with_tenant binds a session to an explicitly
checked-out Connection for schema translation. A session held across a crawl
therefore pins one client connection through gaps long enough to exceed
PgBouncer's client_idle_timeout, and the next query on it fails with "server
closed the connection unexpectedly". pool_pre_ping and pool_recycle act only at
checkout, of which there is exactly one.
"""

from collections.abc import Generator
from datetime import datetime, timezone
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from ee.onyx.background.celery.tasks.doc_permission_syncing import tasks as perm_tasks
from ee.onyx.external_permissions.perm_sync_types import (
    DocSyncFuncType,
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
)
from ee.onyx.external_permissions.sync_params import DocSyncConfig, SyncConfig
from onyx.access.models import (
    DocExternalAccess,
    ElementExternalAccess,
    ExternalAccess,
)
from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import (
    AccessType,
    PermissionSyncStatus,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.db.permission_sync_attempt import (
    get_latest_doc_permission_sync_attempt_for_cc_pair,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_doc_perm_sync import (
    PermissionSyncResult,
    RedisConnectorPermissionSync,
    RedisConnectorPermissionSyncPayload,
)
from shared_configs.configs import (
    POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE as TEST_TENANT_ID,
)
from tests.external_dependency_unit.permission_sync.conftest import (
    create_test_connector_credential_pair,
)


@pytest.fixture
def synced_cc_pair(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> Generator[ConnectorCredentialPair, None, None]:
    """A permission-synced cc_pair with a fence ready for the generator task."""
    cc_pair = create_test_connector_credential_pair(
        db_session, source=DocumentSource.JIRA, access_type=AccessType.SYNC
    )

    suffix = uuid4().hex[:8]
    redis_connector = RedisConnector(TEST_TENANT_ID, cc_pair.id)
    redis_connector.permissions.set_fence(
        RedisConnectorPermissionSyncPayload(
            id=f"payload-{suffix}",
            submitted=datetime.now(timezone.utc),
            started=None,
            celery_task_id=f"task-{suffix}",
        )
    )

    try:
        yield cc_pair
    finally:
        redis_connector.permissions.set_fence(None)


def _run_perm_sync(cc_pair_id: int, doc_sync_func: DocSyncFuncType) -> None:
    """Drive the generator task with a stand-in connector crawl.

    MULTI_TENANT is patched on so the session factory takes its
    checked-out-Connection branch, the one a held session would pin.
    """
    sync_config = SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=1,
            doc_sync_func=doc_sync_func,
            initial_index_should_sync=False,
        )
    )
    with (
        patch("onyx.db.engine.sql_engine.MULTI_TENANT", True),
        patch.object(perm_tasks, "validate_ccpair_for_user", return_value=True),
        patch.object(
            perm_tasks, "get_source_perm_sync_config", return_value=sync_config
        ),
    ):
        perm_tasks.connector_permission_sync_generator_task.apply(
            args=(cc_pair_id,), kwargs={"tenant_id": TEST_TENANT_ID}
        ).get()


def test_no_db_connection_held_during_crawl(
    synced_cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    """The connector crawl must run with no connection checked out by the task,
    and the doc-id query connectors make mid-crawl must still succeed."""
    pool = cast(QueuePool, SqlEngine.get_engine().pool)
    checked_out_during_crawl: list[int] = []
    fetched_existing_ids: list[list[str]] = []
    baseline = pool.checkedout()

    def _fake_doc_sync(
        cc_pair: ConnectorCredentialPair,  # noqa: ARG001
        fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
        fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,
        callback: IndexingHeartbeatInterface | None,  # noqa: ARG001
    ) -> Generator[ElementExternalAccess, None, None]:
        # stands in for the source crawl: the long stretch between the task's
        # own DB queries
        checked_out_during_crawl.append(pool.checkedout() - baseline)
        # connectors query the DB mid-crawl, so this must work on a fresh session
        fetched_existing_ids.append(fetch_all_existing_docs_ids_fn())
        yield from ()

    _run_perm_sync(synced_cc_pair.id, _fake_doc_sync)

    # the crawl ran...
    assert len(checked_out_during_crawl) == 1
    # ...with no connection checked out by the task at that moment
    assert checked_out_during_crawl[0] == 0
    assert fetched_existing_ids == [[]]

    db_session.expire_all()
    attempt = get_latest_doc_permission_sync_attempt_for_cc_pair(
        db_session, synced_cc_pair.id
    )
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.SUCCESS


def test_failed_crawl_records_docs_synced_before_the_error(
    synced_cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    """A sync that dies partway through keeps the documents it already committed,
    so the failed attempt must report them rather than a default of zero."""

    def _fake_doc_sync(
        cc_pair: ConnectorCredentialPair,  # noqa: ARG001
        fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG001
        fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,  # noqa: ARG001
        callback: IndexingHeartbeatInterface | None,  # noqa: ARG001
    ) -> Generator[ElementExternalAccess, None, None]:
        for i in range(2):
            yield DocExternalAccess(
                doc_id=f"doc-{i}", external_access=ExternalAccess.empty()
            )
        raise RuntimeError("connector died mid-crawl")

    with (
        patch.object(
            RedisConnectorPermissionSync,
            "update_db",
            return_value=PermissionSyncResult(num_updated=1, num_errors=0),
        ),
        pytest.raises(RuntimeError, match="connector died mid-crawl"),
    ):
        _run_perm_sync(synced_cc_pair.id, _fake_doc_sync)

    db_session.expire_all()
    attempt = get_latest_doc_permission_sync_attempt_for_cc_pair(
        db_session, synced_cc_pair.id
    )
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.FAILED
    assert attempt.total_docs_synced == 2
    assert attempt.docs_with_permission_errors == 0
