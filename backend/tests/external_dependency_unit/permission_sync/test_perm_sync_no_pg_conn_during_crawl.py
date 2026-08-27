"""
Regression coverage for connector_permission_sync_generator_task pinning a
Postgres connection across the connector crawl.

The task used to open one session before the crawl and hold it until the crawl
finished. On multi-tenant deployments get_session_with_tenant binds a session to
an explicitly checked-out Connection (for schema translation), so that one
connection sat idle, issuing no queries, for the whole crawl. PgBouncer drops
idle clients at client_idle_timeout, so the first query after a long crawl hit a
dead connection and failed with "server closed the connection unexpectedly".
pool_pre_ping and pool_recycle cannot help because there is only ever one
checkout. The task now closes the setup session before the crawl and opens a
fresh session for each DB access after it.

MULTI_TENANT is patched on because the single-tenant branch binds to the engine
instead, which returns the connection to the pool at commit and so never
reproduces the pin.
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
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    PermissionSyncStatus,
)
from onyx.db.models import Connector, ConnectorCredentialPair, Credential
from onyx.db.permission_sync_attempt import (
    delete_doc_permission_sync_attempts__no_commit,
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
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def synced_cc_pair(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> Generator[ConnectorCredentialPair, None, None]:
    """A permission-synced cc_pair with a fence ready for the generator task."""
    suffix = uuid4().hex[:8]
    user = create_test_user(db_session, f"perm_sync_crawl_{suffix}")

    connector = Connector(
        name=f"Perm Sync Crawl Connector {suffix}",
        source=DocumentSource.JIRA,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=datetime.now(timezone.utc),
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(credential_json={}, user_id=user.id, admin_public=True)
    db_session.add(credential)
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        name=f"Perm Sync Crawl CC Pair {suffix}",
        connector_id=connector.id,
        credential_id=credential.id,
        access_type=AccessType.SYNC,
        status=ConnectorCredentialPairStatus.ACTIVE,
    )
    db_session.add(cc_pair)
    db_session.commit()

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
        db_session.rollback()
        delete_doc_permission_sync_attempts__no_commit(db_session, cc_pair.id)
        db_session.delete(cc_pair)
        db_session.commit()


def _run_perm_sync(cc_pair_id: int) -> None:
    perm_tasks.connector_permission_sync_generator_task.apply(
        args=(cc_pair_id,), kwargs={"tenant_id": TEST_TENANT_ID}
    ).get()


def _sync_config(doc_sync_func: DocSyncFuncType) -> SyncConfig:
    return SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=1,
            doc_sync_func=doc_sync_func,
            initial_index_should_sync=False,
        )
    )


def test_no_db_connection_held_during_crawl(
    synced_cc_pair: ConnectorCredentialPair, db_session: Session
) -> None:
    """The connector crawl must run with no connection checked out by the task,
    and the post-crawl doc-id query must still succeed on a fresh session."""
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
        # stands in for the source crawl: the long stretch where the task makes
        # no DB queries at all
        checked_out_during_crawl.append(pool.checkedout() - baseline)
        # the query that used to land on a connection PgBouncer had already killed
        fetched_existing_ids.append(fetch_all_existing_docs_ids_fn())
        return
        yield  # noqa: unreachable - makes this a generator

    with (
        patch("onyx.db.engine.sql_engine.MULTI_TENANT", True),
        patch.object(perm_tasks, "validate_ccpair_for_user", return_value=True),
        patch.object(
            perm_tasks,
            "get_source_perm_sync_config",
            return_value=_sync_config(_fake_doc_sync),
        ),
    ):
        _run_perm_sync(synced_cc_pair.id)

    assert checked_out_during_crawl == [0]
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
        patch("onyx.db.engine.sql_engine.MULTI_TENANT", True),
        patch.object(perm_tasks, "validate_ccpair_for_user", return_value=True),
        patch.object(
            RedisConnectorPermissionSync,
            "update_db",
            return_value=PermissionSyncResult(num_updated=1, num_errors=0),
        ),
        patch.object(
            perm_tasks,
            "get_source_perm_sync_config",
            return_value=_sync_config(_fake_doc_sync),
        ),
        pytest.raises(RuntimeError, match="connector died mid-crawl"),
    ):
        _run_perm_sync(synced_cc_pair.id)

    db_session.expire_all()
    attempt = get_latest_doc_permission_sync_attempt_for_cc_pair(
        db_session, synced_cc_pair.id
    )
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.FAILED
    assert attempt.total_docs_synced == 2
    assert attempt.docs_with_permission_errors == 0
