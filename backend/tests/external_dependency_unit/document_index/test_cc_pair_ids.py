"""cc_pair_ids on OpenSearch chunks: mapping, index-time write, metadata sync,
relationship cleanup, and the backfill.

Uses real Postgres, Redis, and OpenSearch. The Celery tasks run in-process
against the module's test index.
"""

from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.cc_pair_ids_backfill import (
    tasks as backfill_tasks,
)
from onyx.background.celery.tasks.shared.tasks import document_by_cc_pair_cleanup_task
from onyx.background.celery.tasks.vespa.tasks import document_index_metadata_sync_task
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.connector_credential_pair import get_non_deleting_cc_pair_ids
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    VectorQuantization,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch import cc_pair_ids_backfill
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import (
    CC_PAIR_IDS_FIELD_NAME,
    DocumentSchema,
    get_opensearch_doc_chunk_id,
)
from onyx.indexing.adapters.document_indexing_adapter import (
    DocumentIndexingBatchAdapter,
)
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from onyx.indexing.models import IndexChunk
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_TENANT_STATE = TenantState(
    tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
)


@pytest.fixture(scope="module", autouse=True)
def _opensearch_ready() -> None:
    # Some tests here build their own index instead of using the
    # ``opensearch_index`` fixture, so they must wait for OpenSearch themselves.
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")


class _Pairs(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    first: ConnectorCredentialPair
    second: ConnectorCredentialPair
    deleting: ConnectorCredentialPair


@pytest.fixture
def pairs(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[_Pairs, None, None]:
    first = make_cc_pair(db_session)
    second = make_cc_pair(db_session)
    deleting = make_cc_pair(db_session)
    deleting.status = ConnectorCredentialPairStatus.DELETING
    db_session.commit()
    try:
        yield _Pairs(first=first, second=second, deleting=deleting)
    finally:
        db_session.rollback()
        for pair in (first, second, deleting):
            cleanup_cc_pair(db_session, pair)


def _add_document(
    db_session: Session, pairs: list[ConnectorCredentialPair], doc_id: str
) -> None:
    db_session.add(DbDocument(id=doc_id, semantic_id=doc_id, chunk_count=1))
    db_session.commit()
    for pair in pairs:
        upsert_document_by_connector_credential_pair(
            db_session, pair.connector_id, pair.credential_id, [doc_id]
        )


def _index_without_cc_pair_ids(index: OpenSearchDocumentIndex, doc_id: str) -> None:
    index.index(
        chunks=[make_chunk(doc_id)],
        indexing_metadata=make_indexing_metadata([doc_id], [0], [1]),
    )


def _read_cc_pair_ids(index_name: str, doc_id: str) -> list[int] | None:
    chunk_id = get_opensearch_doc_chunk_id(
        tenant_state=_TENANT_STATE, document_id=doc_id, chunk_index=0
    )
    chunk = OpenSearchIndexClient(index_name=index_name).get_document(chunk_id)
    return chunk.cc_pair_ids


def test_put_mapping_adds_field_to_existing_index(
    tenant_context: None,  # noqa: ARG001
) -> None:
    index_name = f"test_cc_pair_mapping_{uuid4().hex[:8]}"
    old_schema = DocumentSchema.get_document_schema(EMBEDDING_DIM, multitenant=False)
    del old_schema["properties"][CC_PAIR_IDS_FIELD_NAME]
    client = OpenSearchIndexClient(index_name=index_name)
    client.create_index(
        mappings=old_schema,
        settings=DocumentSchema.get_index_settings_based_on_environment(),
    )
    try:
        index = OpenSearchDocumentIndex(
            tenant_state=_TENANT_STATE,
            index_name=index_name,
            embedding_dim=EMBEDDING_DIM,
            vector_quantization=VectorQuantization.NONE,
        )
        index.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
        doc_id = f"mapping-{uuid4().hex[:8]}"
        chunk = make_chunk(doc_id).model_copy(update={"cc_pair_ids": [7, 3]})
        index.index(
            chunks=[chunk],
            indexing_metadata=make_indexing_metadata([doc_id], [0], [1]),
        )
        assert _read_cc_pair_ids(index_name, doc_id) == [7, 3]
    finally:
        client.delete_index()


def test_indexing_writes_cc_pair_ids(
    db_session: Session,
    pairs: _Pairs,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> None:
    doc_id = f"cc-pair-index-{uuid4().hex[:8]}"
    _add_document(db_session, [pairs.first, pairs.second, pairs.deleting], doc_id)
    metadata_aware_chunk = make_chunk(doc_id)
    chunk = IndexChunk.model_validate(
        metadata_aware_chunk.model_dump(include=set(IndexChunk.model_fields))
    )

    adapter = DocumentIndexingBatchAdapter(
        connector_id=pairs.first.connector_id,
        credential_id=pairs.first.credential_id,
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        index_attempt_metadata=IndexAttemptMetadata(
            connector_id=pairs.first.connector_id,
            credential_id=pairs.first.credential_id,
        ),
    )
    enricher = adapter.prepare_enrichment(
        context=DocumentBatchPrepareContext(
            updatable_docs=[chunk.source_document], id_to_boost_map={}
        ),
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        chunks=[chunk],
        db_session=db_session,
    )
    opensearch_index.index(
        chunks=[enricher.enrich_chunk(chunk, score=1.0)],
        indexing_metadata=make_indexing_metadata([doc_id], [0], [1]),
    )

    # The DELETING pair is left out, as it is from document access.
    assert _read_cc_pair_ids(test_index_name, doc_id) == sorted(
        [pairs.first.id, pairs.second.id]
    )


def test_metadata_sync_and_cleanup_update_cc_pair_ids(
    db_session: Session,
    pairs: _Pairs,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> None:
    doc_id = f"cc-pair-sync-{uuid4().hex[:8]}"
    _add_document(db_session, [pairs.first], doc_id)
    _index_without_cc_pair_ids(opensearch_index, doc_id)

    with patch(
        "onyx.background.celery.tasks.vespa.tasks.get_default_document_index",
        return_value=opensearch_index,
    ):
        # Add a cc-pair, then sync.
        upsert_document_by_connector_credential_pair(
            db_session, pairs.second.connector_id, pairs.second.credential_id, [doc_id]
        )
        result = document_index_metadata_sync_task.apply(
            args=(doc_id,),
            kwargs={"tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE},
        )
        assert result.successful(), result.traceback
    assert _read_cc_pair_ids(test_index_name, doc_id) == sorted(
        [pairs.first.id, pairs.second.id]
    )

    # Remove a cc-pair through the prune / deletion cleanup task.
    with patch(
        "onyx.background.celery.tasks.shared.tasks.get_default_document_index",
        return_value=opensearch_index,
    ):
        result = document_by_cc_pair_cleanup_task.apply(
            args=(
                doc_id,
                pairs.second.connector_id,
                pairs.second.credential_id,
                POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            ),
        )
        assert result.successful(), result.traceback
    assert _read_cc_pair_ids(test_index_name, doc_id) == [pairs.first.id]


def test_metadata_sync_rewrites_a_document_with_an_unknown_chunk_count(
    db_session: Session,
    pairs: _Pairs,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> None:
    # Indexed before chunk counts were stored: public chunks, NULL chunk_count.
    doc_id = f"cc-pair-legacy-{uuid4().hex[:8]}"
    _add_document(db_session, [pairs.first], doc_id)
    legacy_doc = db_session.get(DbDocument, doc_id)
    assert legacy_doc is not None
    legacy_doc.chunk_count = None
    db_session.commit()
    _index_without_cc_pair_ids(opensearch_index, doc_id)
    OpenSearchIndexClient(index_name=test_index_name).refresh_index()

    pairs.first.access_type = AccessType.SYNC
    db_session.commit()
    with patch(
        "onyx.background.celery.tasks.vespa.tasks.get_default_document_index",
        return_value=opensearch_index,
    ):
        result = document_index_metadata_sync_task.apply(
            args=(doc_id,),
            kwargs={"tenant_id": POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE},
        )
        assert result.successful(), result.traceback

    chunk = OpenSearchIndexClient(index_name=test_index_name).get_document(
        get_opensearch_doc_chunk_id(
            tenant_state=_TENANT_STATE, document_id=doc_id, chunk_index=0
        )
    )
    assert not chunk.public
    assert chunk.cc_pair_ids == [pairs.first.id]


@pytest.mark.usefixtures("kv_progress_restored")
def test_backfill_fills_missing_field_resumes_and_reports_completion(
    db_session: Session,
    pairs: _Pairs,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> None:
    prefix = f"cc-pair-backfill-{uuid4().hex[:8]}"
    shared_doc = f"{prefix}-a"
    first_only_doc = f"{prefix}-b"
    deleting_only_doc = f"{prefix}-c"
    _add_document(db_session, [pairs.first, pairs.second], shared_doc)
    _add_document(db_session, [pairs.first], first_only_doc)
    _add_document(db_session, [pairs.deleting], deleting_only_doc)
    for doc_id in (shared_doc, first_only_doc, deleting_only_doc):
        _index_without_cc_pair_ids(opensearch_index, doc_id)
        assert _read_cc_pair_ids(test_index_name, doc_id) is None
    # update-by-query only sees refreshed chunks.
    OpenSearchIndexClient(index_name=test_index_name).refresh_index()

    snapshot_ids = get_non_deleting_cc_pair_ids(db_session)
    assert pairs.first.id in snapshot_ids and pairs.second.id in snapshot_ids
    assert pairs.deleting.id not in snapshot_ids
    # Scope the snapshot to this test's pairs. It also holds a cc-pair that
    # started deleting after the snapshot and one that no longer exists.
    missing_id = max(snapshot_ids) + 10_000
    test_snapshot = [pairs.first.id, pairs.deleting.id, missing_id, pairs.second.id]

    search_settings = SimpleNamespace(
        id=1, index_name=test_index_name, port_backfill_source_id=None
    )
    lock = get_redis_client().lock(f"test_cc_pair_backfill_{uuid4().hex}", timeout=60)
    assert lock.acquire(blocking=False)
    try:
        with (
            patch.object(backfill_tasks, "_BACKFILL_BATCH_SIZE", 1),
            patch.object(
                backfill_tasks,
                "get_non_deleting_cc_pair_ids",
                return_value=test_snapshot,
            ),
            patch.object(
                backfill_tasks,
                "get_current_search_settings",
                return_value=search_settings,
            ),
            patch.object(
                cc_pair_ids_backfill,
                "get_current_search_settings",
                return_value=search_settings,
            ),
            patch.object(
                backfill_tasks,
                "build_opensearch_document_index",
                return_value=opensearch_index,
            ),
        ):
            # A run with no time left only takes the snapshot.
            with patch.object(backfill_tasks, "_BACKFILL_TIME_BUDGET_S", 0):
                assert not backfill_tasks.run_cc_pair_ids_backfill(lock)
            assert (
                cc_pair_ids_backfill.load_cc_pair_ids_backfill_progress(
                    search_settings  # ty: ignore[invalid-argument-type]
                ).pending_cc_pair_ids
                == test_snapshot
            )
            assert not cc_pair_ids_backfill.is_cc_pair_ids_backfill_complete(db_session)

            assert backfill_tasks.run_cc_pair_ids_backfill(lock)
            assert cc_pair_ids_backfill.is_cc_pair_ids_backfill_complete(db_session)

            assert _read_cc_pair_ids(test_index_name, shared_doc) == sorted(
                [pairs.first.id, pairs.second.id]
            )
            assert _read_cc_pair_ids(test_index_name, first_only_doc) == [
                pairs.first.id
            ]
            # The deleting cc-pair left the list without a write.
            assert _read_cc_pair_ids(test_index_name, deleting_only_doc) is None

            # A new primary index restarts the backfill, also when the new
            # generation reuses an old index name.
            for other_generation in (
                SimpleNamespace(id=2, index_name=f"{test_index_name}_other"),
                SimpleNamespace(id=2, index_name=test_index_name),
            ):
                with patch.object(
                    cc_pair_ids_backfill,
                    "get_current_search_settings",
                    return_value=other_generation,
                ):
                    assert not cc_pair_ids_backfill.is_cc_pair_ids_backfill_complete(
                        db_session
                    )

            # Re-running from scratch is safe and gives the same result.
            cc_pair_ids_backfill.store_cc_pair_ids_backfill_progress(
                cc_pair_ids_backfill.CCPairIdsBackfillProgress(
                    search_settings_id=1, index_name=test_index_name
                )
            )
            OpenSearchIndexClient(index_name=test_index_name).refresh_index()
            assert backfill_tasks.run_cc_pair_ids_backfill(lock)
            assert _read_cc_pair_ids(test_index_name, shared_doc) == sorted(
                [pairs.first.id, pairs.second.id]
            )
    finally:
        lock.release()


@pytest.mark.usefixtures("kv_progress_restored", "tenant_context")
def test_backfill_waits_for_instant_swap_port(test_index_name: str) -> None:
    search_settings = SimpleNamespace(
        id=1, index_name=test_index_name, port_backfill_source_id=2
    )
    lock = get_redis_client().lock(f"test_cc_pair_backfill_{uuid4().hex}", timeout=60)
    assert lock.acquire(blocking=False)
    try:
        with (
            patch.object(
                backfill_tasks,
                "get_current_search_settings",
                return_value=search_settings,
            ),
            patch.object(
                backfill_tasks, "port_backfill_has_pending_work", return_value=True
            ),
            patch.object(backfill_tasks, "get_non_deleting_cc_pair_ids") as snapshot,
        ):
            assert not backfill_tasks.run_cc_pair_ids_backfill(lock)
        snapshot.assert_not_called()
        assert (
            cc_pair_ids_backfill.load_cc_pair_ids_backfill_progress(
                search_settings  # ty: ignore[invalid-argument-type]
            ).pending_cc_pair_ids
            is None
        )
    finally:
        lock.release()


def test_backfill_marks_concurrently_modified_document_stale(
    db_session: Session,
    pairs: _Pairs,
    opensearch_index: OpenSearchDocumentIndex,
    test_index_name: str,
) -> None:
    """A document modified while its batch runs is marked modified again, so
    metadata sync rewrites it after the backfill's possibly stale write."""
    doc_id = f"cc-pair-race-{uuid4().hex[:8]}"
    _add_document(db_session, [pairs.first], doc_id)
    _index_without_cc_pair_ids(opensearch_index, doc_id)
    OpenSearchIndexClient(index_name=test_index_name).refresh_index()
    concurrent_modified_at = datetime(2021, 1, 1, tzinfo=timezone.utc)

    original_set = OpenSearchDocumentIndex.set_cc_pair_ids

    def _set_and_modify_concurrently(
        index: OpenSearchDocumentIndex, doc_id_to_cc_pair_ids: dict[str, list[int]]
    ) -> int:
        updated = original_set(index, doc_id_to_cc_pair_ids)
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).update(
            {DbDocument.last_modified: concurrent_modified_at}
        )
        db_session.commit()
        return updated

    with patch.object(
        OpenSearchDocumentIndex, "set_cc_pair_ids", _set_and_modify_concurrently
    ):
        backfill_tasks._backfill_batch(opensearch_index, [doc_id])

    db_session.expire_all()
    row = db_session.get(DbDocument, doc_id)
    assert row is not None and row.last_modified is not None
    assert row.last_modified > concurrent_modified_at
    assert _read_cc_pair_ids(test_index_name, doc_id) == [pairs.first.id]


def test_backfill_batches_are_bounded_by_chunk_count(
    db_session: Session,
    pairs: _Pairs,
) -> None:
    prefix = f"cc-pair-chunk-bound-{uuid4().hex[:8]}"
    doc_ids = [f"{prefix}-{i}" for i in range(3)]
    for doc_id in doc_ids:
        _add_document(db_session, [pairs.first], doc_id)
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).update(
            {DbDocument.chunk_count: 3}
        )
    db_session.commit()

    with patch.object(backfill_tasks, "_BACKFILL_MAX_CHUNKS_PER_BATCH", 7):
        assert (
            backfill_tasks._bound_by_chunk_count(db_session, doc_ids) == (doc_ids[:2])
        )
    # A document larger than the bound still makes a batch of one.
    with patch.object(backfill_tasks, "_BACKFILL_MAX_CHUNKS_PER_BATCH", 1):
        assert (
            backfill_tasks._bound_by_chunk_count(db_session, doc_ids) == (doc_ids[:1])
        )

    # A document with an unknown chunk count makes a batch of its own.
    db_session.query(DbDocument).filter(DbDocument.id == doc_ids[1]).update(
        {DbDocument.chunk_count: None}
    )
    db_session.commit()
    with patch.object(backfill_tasks, "_BACKFILL_MAX_CHUNKS_PER_BATCH", 7):
        assert (
            backfill_tasks._bound_by_chunk_count(db_session, doc_ids) == (doc_ids[:1])
        )
        assert (
            backfill_tasks._bound_by_chunk_count(db_session, doc_ids[1:])
            == (doc_ids[1:2])
        )
