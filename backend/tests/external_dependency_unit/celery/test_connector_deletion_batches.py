"""Guards connector deletion batching: the first pass is capped, each pass is
sent as one cleanup task per document batch, the monitor queues the next pass
only after the taskset drains with fewer documents linked, the last drained
pass hands over to the Postgres finalize, and a pass that does not lower the
linked count fails the deletion and clears the fence."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.connector_deletion import tasks as deletion_tasks
from onyx.db.enums import ConnectorCredentialPairStatus, SyncStatus, SyncType
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    DocumentByConnectorCredentialPair,
    SyncRecord,
)
from onyx.db.models import Document as DbDocument
from onyx.redis import redis_connector_delete
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.indexing_helpers import (
    make_cc_pair,
    seed_cc_pair_documents,
)

TENANT_ID = POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
PASS_SIZE = 2
DOC_COUNT = 5


class SeededPair(BaseModel):
    """Ids only: the finalize deletes the ORM rows, so teardown cannot hold them."""

    cc_pair_id: int
    connector_id: int
    credential_id: int
    doc_ids: list[str]


@pytest.fixture
def deleting_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[SeededPair, None, None]:
    cc_pair = make_cc_pair(db_session)
    doc_ids = seed_cc_pair_documents(db_session, cc_pair, DOC_COUNT, unique=True)
    cc_pair.status = ConnectorCredentialPairStatus.DELETING
    db_session.commit()
    seeded = SeededPair(
        cc_pair_id=cc_pair.id,
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        doc_ids=doc_ids,
    )
    try:
        yield seeded
    finally:
        RedisConnector(TENANT_ID, seeded.cc_pair_id).delete.reset()
        db_session.rollback()
        _teardown(db_session, seeded)


def _teardown(db_session: Session, seeded: SeededPair) -> None:
    db_session.query(DocumentByConnectorCredentialPair).filter(
        DocumentByConnectorCredentialPair.connector_id == seeded.connector_id,
        DocumentByConnectorCredentialPair.credential_id == seeded.credential_id,
    ).delete(synchronize_session=False)
    db_session.query(DbDocument).filter(DbDocument.id.in_(seeded.doc_ids)).delete(
        synchronize_session=False
    )
    db_session.query(SyncRecord).filter(
        SyncRecord.entity_id == seeded.cc_pair_id,
        SyncRecord.sync_type == SyncType.CONNECTOR_DELETION,
    ).delete(synchronize_session=False)
    db_session.query(ConnectorCredentialPair).filter(
        ConnectorCredentialPair.id == seeded.cc_pair_id
    ).delete(synchronize_session=False)
    db_session.query(Connector).filter(Connector.id == seeded.connector_id).delete(
        synchronize_session=False
    )
    db_session.query(Credential).filter(Credential.id == seeded.credential_id).delete(
        synchronize_session=False
    )
    db_session.commit()


def _drain_batch(db_session: Session, seeded: SeededPair, unlinked: int) -> None:
    """What a finished batch leaves behind: an empty taskset and fewer linked docs."""
    RedisConnector(TENANT_ID, seeded.cc_pair_id).delete.taskset_clear()
    rows = (
        db_session.query(DocumentByConnectorCredentialPair)
        .filter(
            DocumentByConnectorCredentialPair.connector_id == seeded.connector_id,
            DocumentByConnectorCredentialPair.credential_id == seeded.credential_id,
        )
        .limit(unlinked)
        .all()
    )
    for row in rows:
        db_session.delete(row)
    db_session.commit()


def _run_monitor(seeded: SeededPair, celery_app: MagicMock) -> None:
    redis_connector = RedisConnector(TENANT_ID, seeded.cc_pair_id)
    deletion_tasks.monitor_connector_deletion_taskset(
        TENANT_ID,
        redis_connector.delete.fence_key.encode(),
        get_redis_client(tenant_id=TENANT_ID),
        celery_app,
        MagicMock(),
    )


def _queued_doc_ids(celery_app: MagicMock) -> list[str]:
    return [
        doc_id
        for call in celery_app.send_task.call_args_list
        for doc_id in call.kwargs["kwargs"]["document_ids"]
    ]


def _assert_fence(
    seeded: SeededPair, num_docs_queued: int, docs_remaining: int
) -> None:
    fence = RedisConnector(TENANT_ID, seeded.cc_pair_id).delete.payload
    assert fence is not None
    assert fence.num_docs_queued == num_docs_queued
    assert fence.docs_remaining == docs_remaining


def test_deletion_runs_in_bounded_batches_then_finalizes(
    db_session: Session, deleting_pair: SeededPair
) -> None:
    seeded = deleting_pair
    redis_connector = RedisConnector(TENANT_ID, seeded.cc_pair_id)
    celery_app = MagicMock()

    with patch.object(deletion_tasks, "DOCUMENT_INDEX_SYNC_MAX_TASKS", PASS_SIZE):
        generated = deletion_tasks.try_generate_document_cc_pair_cleanup_tasks(
            celery_app, seeded.cc_pair_id, db_session, MagicMock(), TENANT_ID
        )
        assert generated == PASS_SIZE
        # The whole pass fits in one cleanup task.
        assert celery_app.send_task.call_count == 1
        assert len(_queued_doc_ids(celery_app)) == PASS_SIZE
        assert redis_connector.delete.get_remaining() == 1
        _assert_fence(seeded, num_docs_queued=PASS_SIZE, docs_remaining=DOC_COUNT)

        # The taskset still holds the pass, so the monitor waits.
        _run_monitor(seeded, celery_app)
        assert celery_app.send_task.call_count == 1

        # Passes 2 and 3: each drained pass queues the next, up to the cap.
        _drain_batch(db_session, seeded, PASS_SIZE)
        _run_monitor(seeded, celery_app)
        assert len(_queued_doc_ids(celery_app)) == 2 * PASS_SIZE
        _assert_fence(seeded, num_docs_queued=2 * PASS_SIZE, docs_remaining=3)

        _drain_batch(db_session, seeded, PASS_SIZE)
        _run_monitor(seeded, celery_app)
        assert len(_queued_doc_ids(celery_app)) == DOC_COUNT
        _assert_fence(seeded, num_docs_queued=DOC_COUNT, docs_remaining=1)

        # The last pass drains with nothing linked: the deletion finalizes.
        _drain_batch(db_session, seeded, 1)
        _run_monitor(seeded, celery_app)

    assert len(_queued_doc_ids(celery_app)) == DOC_COUNT
    assert not redis_connector.delete.fenced
    db_session.expire_all()
    assert (
        db_session.query(ConnectorCredentialPair)
        .filter(ConnectorCredentialPair.id == seeded.cc_pair_id)
        .one_or_none()
        is None
    )
    sync_record = (
        db_session.query(SyncRecord)
        .filter(
            SyncRecord.entity_id == seeded.cc_pair_id,
            SyncRecord.sync_type == SyncType.CONNECTOR_DELETION,
        )
        .order_by(SyncRecord.id.desc())
        .first()
    )
    assert sync_record is not None
    assert sync_record.sync_status == SyncStatus.SUCCESS
    assert sync_record.num_docs_synced == DOC_COUNT


def test_a_pass_is_split_into_cleanup_tasks_of_the_batch_size(
    db_session: Session, deleting_pair: SeededPair
) -> None:
    seeded = deleting_pair
    celery_app = MagicMock()

    with patch.object(redis_connector_delete, "DOCUMENT_CLEANUP_BATCH_SIZE", 2):
        generated = deletion_tasks.try_generate_document_cc_pair_cleanup_tasks(
            celery_app, seeded.cc_pair_id, db_session, MagicMock(), TENANT_ID
        )

    assert generated == DOC_COUNT
    batch_sizes = [
        len(call.kwargs["kwargs"]["document_ids"])
        for call in celery_app.send_task.call_args_list
    ]
    assert batch_sizes == [2, 2, 1]
    assert sorted(_queued_doc_ids(celery_app)) == sorted(seeded.doc_ids)
    assert RedisConnector(TENANT_ID, seeded.cc_pair_id).delete.get_remaining() == 3
    assert all(
        call.kwargs["expires"] is not None
        for call in celery_app.send_task.call_args_list
    )


def test_a_batch_that_does_not_lower_the_linked_count_fails_the_deletion(
    db_session: Session, deleting_pair: SeededPair
) -> None:
    seeded = deleting_pair
    celery_app = MagicMock()

    with patch.object(deletion_tasks, "DOCUMENT_INDEX_SYNC_MAX_TASKS", PASS_SIZE):
        deletion_tasks.try_generate_document_cc_pair_cleanup_tasks(
            celery_app, seeded.cc_pair_id, db_session, MagicMock(), TENANT_ID
        )
        # The pass drains without unlinking anything.
        _drain_batch(db_session, seeded, 0)
        with pytest.raises(RuntimeError, match="did not lower"):
            _run_monitor(seeded, celery_app)

    assert len(_queued_doc_ids(celery_app)) == PASS_SIZE
    assert not RedisConnector(TENANT_ID, seeded.cc_pair_id).delete.fenced
