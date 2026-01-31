"""External dependency unit tests for OpenSearch migration celery tasks.

These tests require Postgres, Redis, Vespa, and OpenSearch to be running.

WARNING: As will all external dependency tests, do not run them against a
database with data you care about. Your data will be destroyed.
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.opensearch_migration.tasks import (
    _migrate_single_document as _original_migrate_single_document,
)
from onyx.background.celery.tasks.opensearch_migration.tasks import (
    check_for_documents_for_opensearch_migration_task,
)
from onyx.background.celery.tasks.opensearch_migration.tasks import (
    migrate_documents_from_vespa_to_opensearch_task,
)
from onyx.context.search.models import IndexFilters
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import OpenSearchDocumentMigrationStatus
from onyx.db.models import Document
from onyx.db.models import OpenSearchDocumentMigrationRecord
from onyx.db.models import OpenSearchTenantMigrationRecord
from onyx.db.opensearch_migration import create_opensearch_migration_records_with_commit
from onyx.db.opensearch_migration import get_last_opensearch_migration_document_id
from onyx.db.search_settings import get_active_search_settings
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.client import wait_for_opensearch_with_timeout
from onyx.document_index.opensearch.constants import DEFAULT_MAX_CHUNK_SIZE
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.search import DocumentQuery
from onyx.document_index.vespa.shared_utils.utils import wait_for_vespa_with_timeout
from onyx.document_index.vespa.vespa_document_index import VespaDocumentIndex
from onyx.document_index.vespa_constants import CHUNK_ID
from onyx.document_index.vespa_constants import CONTENT
from onyx.document_index.vespa_constants import DOCUMENT_ID
from onyx.document_index.vespa_constants import EMBEDDINGS
from onyx.document_index.vespa_constants import FULL_CHUNK_EMBEDDING_KEY
from onyx.document_index.vespa_constants import TITLE
from onyx.document_index.vespa_constants import TITLE_EMBEDDING
from shared_configs.contextvars import get_current_tenant_id


# Test vector dimension - must match the actual search settings dimension (384
# for default model).
TEST_VECTOR_DIM = 384


def _get_document_chunks_from_opensearch(
    opensearch_client: OpenSearchClient, document_id: str, current_tenant_id: str
) -> list[DocumentChunk]:
    filters = IndexFilters(access_control_list=None, tenant_id=current_tenant_id)
    query_body = DocumentQuery.get_from_document_id_query(
        document_id=document_id,
        tenant_state=TenantState(tenant_id=current_tenant_id, multitenant=False),
        index_filters=filters,
        include_hidden=False,
        max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
        min_chunk_index=None,
        max_chunk_index=None,
    )
    search_hits = opensearch_client.search(
        body=query_body,
        search_pipeline_id=None,
    )
    return [search_hit.document_chunk for search_hit in search_hits]


def _generate_test_vector(dim: int = TEST_VECTOR_DIM) -> list[float]:
    """Generate a deterministic test embedding vector."""
    return [0.1 + (i * 0.001) for i in range(dim)]


def _insert_test_documents_with_commit(
    db_session: Session,
    document_ids: list[str],
) -> list[Document]:
    """Creates test Document records in Postgres."""
    documents = [
        Document(
            id=document_id,
            semantic_id=document_id,
        )
        for document_id in document_ids
    ]
    db_session.add_all(documents)
    db_session.commit()
    return documents


def _delete_test_documents_with_commit(
    db_session: Session,
    documents: list[Document],
) -> None:
    """Deletes test Document records from Postgres."""
    for document in documents:
        db_session.delete(document)
    db_session.commit()


def _insert_test_migration_records_with_commit(
    db_session: Session,
    migration_records: list[OpenSearchDocumentMigrationRecord],
) -> None:
    db_session.add_all(migration_records)
    db_session.commit()


def _create_raw_document_chunk(
    document_id: str,
    chunk_index: int,
    content: str,
    embedding: list[float],
    title: str | None = None,
    title_embedding: list[float] | None = None,
) -> dict[str, Any]:
    return {
        DOCUMENT_ID: document_id,
        CHUNK_ID: chunk_index,
        CONTENT: content,
        EMBEDDINGS: {FULL_CHUNK_EMBEDDING_KEY: embedding},
        TITLE: title,
        TITLE_EMBEDDING: title_embedding,
    }


@pytest.fixture(scope="module")
def opensearch_available(full_deployment_setup: None) -> None:
    """Verifies OpenSearch is running, fails the test if not."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")


@pytest.fixture(scope="module")
def vespa_available(full_deployment_setup: None) -> None:
    """Verifies Vespa is running, fails the test if not."""
    if not wait_for_vespa_with_timeout():
        pytest.fail("Vespa is not available.")


@pytest.fixture(scope="module")
def vespa_document_index(
    db_session: Session,
    vespa_available: None,
) -> VespaDocumentIndex:
    """Creates a Vespa document index for the test tenant."""
    with get_session_with_current_tenant() as db_session:
        active = get_active_search_settings(db_session)
    return VespaDocumentIndex(
        index_name=active.primary.index_name,
        tenant_state=TenantState(tenant_id=get_current_tenant_id(), multitenant=False),
        large_chunks_enabled=False,
    )


@pytest.fixture(scope="module")
def opensearch_client(
    db_session: Session,
    opensearch_available: None,
) -> OpenSearchClient:
    """Creates an OpenSearch client for the test tenant."""
    with get_session_with_current_tenant() as db_session:
        active = get_active_search_settings(db_session)
    return OpenSearchClient(index_name=active.primary.index_name)


@pytest.fixture(scope="function")
def test_documents(db_session: Session) -> Generator[list[Document], None, None]:
    """Creates and cleans test Document records in Postgres."""
    doc_ids = [f"test_doc_{i}" for i in range(3)]
    documents = _insert_test_documents_with_commit(db_session, doc_ids)

    yield documents  # Test runs here.

    # Cleanup.
    _delete_test_documents_with_commit(db_session, documents)


@pytest.fixture(scope="function")
def clean_migration_tables(db_session: Session) -> Generator[None, None, None]:
    """Cleans up migration-related tables before and after each test."""
    # Clean before test.
    db_session.query(OpenSearchDocumentMigrationRecord).delete()
    db_session.query(OpenSearchTenantMigrationRecord).delete()
    db_session.commit()

    yield  # Test runs here.

    # Clean after test.
    db_session.query(OpenSearchDocumentMigrationRecord).delete()
    db_session.query(OpenSearchTenantMigrationRecord).delete()
    db_session.commit()


@pytest.fixture(scope="function")
def enable_opensearch_indexing_for_onyx() -> Generator[None, None, None]:
    with patch(
        "onyx.background.celery.tasks.opensearch_migration.tasks.ENABLE_OPENSEARCH_INDEXING_FOR_ONYX",
        True,
    ):
        yield  # Test runs here.


@pytest.fixture(scope="function")
def disable_opensearch_indexing_for_onyx() -> Generator[None, None, None]:
    with patch(
        "onyx.background.celery.tasks.opensearch_migration.tasks.ENABLE_OPENSEARCH_INDEXING_FOR_ONYX",
        False,
    ):
        yield  # Test runs here.


class TestCheckForDocumentsForOpenSearchMigrationTask:
    """Tests check_for_documents_for_opensearch_migration_task."""

    def test_creates_migration_records_for_documents(
        self,
        db_session: Session,
        test_documents: list[Document],
        clean_migration_tables: None,
        enable_opensearch_indexing_for_onyx: None,
    ) -> None:
        """Tests that migration records are created for documents in the DB."""
        # Under test.
        result = check_for_documents_for_opensearch_migration_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Verify migration records were created.
        for document in test_documents:
            record = (
                db_session.query(OpenSearchDocumentMigrationRecord)
                .filter(OpenSearchDocumentMigrationRecord.document_id == document.id)
                .first()
            )
            assert record is not None
            assert record.status == OpenSearchDocumentMigrationStatus.PENDING

    def test_pagination_continues_from_last_document(
        self,
        db_session: Session,
        test_documents: list[Document],
        clean_migration_tables: None,
        enable_opensearch_indexing_for_onyx: None,
    ) -> None:
        """Tests that pagination picks up from the last migrated document ID."""
        # Precondition.
        # Pre-create migration records for first n - 1 docs.
        n = len(test_documents)
        create_opensearch_migration_records_with_commit(
            db_session, [doc.id for doc in test_documents[: n - 1]]
        )
        # Verify last document ID - should be the second one alphabetically.
        last_id = get_last_opensearch_migration_document_id(db_session)
        assert last_id == test_documents[n - 1].id

        # Under test.
        result = check_for_documents_for_opensearch_migration_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Verify all documents now have migration records.
        for document in test_documents:
            record = (
                db_session.query(OpenSearchDocumentMigrationRecord)
                .filter(OpenSearchDocumentMigrationRecord.document_id == document.id)
                .first()
            )
            assert record is not None

    def test_runs_successfully_when_documents_already_have_migration_records(
        self,
        db_session: Session,
        test_documents: list[Document],
        clean_migration_tables: None,
        enable_opensearch_indexing_for_onyx: None,
    ) -> None:
        """
        Tests that task runs successfully when all documents already have
        migration records.
        """
        # Precondition.
        create_opensearch_migration_records_with_commit(
            db_session, [doc.id for doc in test_documents]
        )

        # Under test.
        result = check_for_documents_for_opensearch_migration_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True

    def test_returns_none_when_feature_disabled(
        self,
        disable_opensearch_migration: None,
    ) -> None:
        """Tests that task returns None when feature is disabled."""
        # Under test.
        result = check_for_documents_for_opensearch_migration_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is None

    def test_increments_counter_when_no_records_to_populate(
        self,
        db_session: Session,
        test_documents: list[Document],
        clean_migration_tables: None,
        enable_opensearch_indexing_for_onyx: None,
    ) -> None:
        """Tests that counter increments when no records to populate."""


class TestMigrateDocumentsFromVespaToOpenSearchTask:
    """Tests migrate_documents_from_vespa_to_opensearch_task."""

    def test_migrates_document_successfully(
        self,
        db_session: Session,
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchClient,
        clean_migration_tables: None,
        enable_opensearch_migration: None,
    ) -> None:
        """Tests successful migration of a document from Vespa to OpenSearch."""
        # Precondition.
        document_ids = [f"test_doc_{i}" for i in range(3)]
        migration_records = [
            OpenSearchDocumentMigrationRecord(document_id=document_id)
            for document_id in document_ids
        ]
        _insert_test_migration_records_with_commit(db_session, migration_records)
        document_chunks = {
            document_id: [
                _create_raw_document_chunk(
                    document_id,
                    i,
                    f"Test content {i}",
                    _generate_test_vector(),
                    f"Test title {document_id}",
                    _generate_test_vector(),
                )
                for i in range(5)
            ]
            for document_id in document_ids
        }
        document_chunks_list = []
        for document_id in document_ids:
            document_chunks_list.extend(document_chunks[document_id])
        vespa_document_index.index_raw_chunks(document_chunks_list)

        # Under test.
        result = migrate_documents_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Verify migration records were updated.
        for document_id in document_ids:
            record = (
                db_session.query(OpenSearchDocumentMigrationRecord)
                .filter(OpenSearchDocumentMigrationRecord.document_id == document_id)
                .first()
            )
            assert record is not None
            assert record.status == OpenSearchDocumentMigrationStatus.COMPLETED
            assert record.attempts_count == 1
        # Verify chunks were indexed in OpenSearch.
        for document_id in document_ids:
            chunks = _get_document_chunks_from_opensearch(
                opensearch_client, document_id, get_current_tenant_id()
            )
            assert len(chunks) == 5
            for i, chunk in enumerate(chunks):
                assert chunk.document_id == document_id
                assert chunk.chunk_index == i
                assert chunk.content == document_chunks[document_id][i][CONTENT]
                assert (
                    chunk.content_vector
                    == document_chunks[document_id][i][EMBEDDINGS][
                        FULL_CHUNK_EMBEDDING_KEY
                    ]
                )
                assert chunk.title == document_chunks[document_id][i][TITLE]
                assert (
                    chunk.title_vector
                    == document_chunks[document_id][i][TITLE_EMBEDDING]
                )

    def test_marks_document_as_failed_on_error(
        self,
        db_session: Session,
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchClient,
        clean_migration_tables: None,
        enable_opensearch_migration: None,
    ) -> None:
        """Tests that documents are marked as FAILED when migration fails."""
        # Precondition.
        call_count = 0
        call_count_to_fail_on = 2

        def _mock_migrate_single_document_impl(*args, **kwargs) -> int:
            nonlocal call_count
            if call_count >= call_count_to_fail_on:
                call_count += 1
                raise RuntimeError("Test error.")
            call_count += 1
            return _original_migrate_single_document(
                *args,
                **kwargs,
            )

        document_ids = [f"test_doc_{i}" for i in range(3)]
        migration_records = [
            OpenSearchDocumentMigrationRecord(document_id=document_id)
            for document_id in document_ids
        ]
        _insert_test_migration_records_with_commit(db_session, migration_records)
        document_chunks = {
            document_id: [
                _create_raw_document_chunk(
                    document_id,
                    i,
                    f"Test content {i}",
                    _generate_test_vector(),
                    f"Test title {document_id}",
                    _generate_test_vector(),
                )
                for i in range(5)
            ]
            for document_id in document_ids
        }
        document_chunks_list = []
        for document_id in document_ids:
            document_chunks_list.extend(document_chunks[document_id])
        vespa_document_index.index_raw_chunks(document_chunks_list)

        # Patch _migrate_single_document to have normal behavior on all docs but
        # the last one.
        with patch(
            "onyx.background.celery.tasks.opensearch_migration.tasks._migrate_single_document",
            _mock_migrate_single_document_impl,
        ):
            # Under test.
            result = migrate_documents_from_vespa_to_opensearch_task(
                tenant_id=get_current_tenant_id()
            )

        # Postcondition.
        assert result is True
        # Verify migration records were updated.
        for i, document_id in enumerate(document_ids):
            record = (
                db_session.query(OpenSearchDocumentMigrationRecord)
                .filter(OpenSearchDocumentMigrationRecord.document_id == document_id)
                .first()
            )
            assert record is not None
            assert (
                record.status == OpenSearchDocumentMigrationStatus.COMPLETED
                if i < call_count_to_fail_on
                else OpenSearchDocumentMigrationStatus.FAILED
            )
            assert record.attempts_count == 1
        # Verify chunks were indexed in OpenSearch.
        for i, document_id in enumerate(document_ids):
            if i < call_count_to_fail_on:
                chunks = _get_document_chunks_from_opensearch(
                    opensearch_client, document_id, get_current_tenant_id()
                )
                assert len(chunks) == 3
                for j, chunk in enumerate(chunks):
                    assert chunk.document_id == document_id
                    assert chunk.chunk_index == j
                    assert chunk.content == document_chunks[document_id][j][CONTENT]
                    assert (
                        chunk.content_vector
                        == document_chunks[document_id][j][EMBEDDINGS][
                            FULL_CHUNK_EMBEDDING_KEY
                        ]
                    )
                    assert chunk.title == document_chunks[document_id][j][TITLE]
                    assert (
                        chunk.title_vector
                        == document_chunks[document_id][j][TITLE_EMBEDDING]
                    )
            else:
                # Since the doc should be missing we expect a raise.
                with pytest.raises(Exception):
                    _get_document_chunks_from_opensearch(
                        opensearch_client, document_id, get_current_tenant_id()
                    )

    def test_marks_document_as_permanently_failed_after_max_attempts(
        self,
        db_session: Session,
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchClient,
        clean_migration_tables: None,
        enable_opensearch_migration: None,
    ) -> None:
        """
        Tests that documents are marked as PERMANENTLY_FAILED after max
        attempts.
        """

    def test_fails_if_chunk_count_is_none(
        self,
        db_session: Session,
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchClient,
        clean_migration_tables: None,
        enable_opensearch_migration: None,
    ) -> None:
        """Tests that migration fails if document has no chunk_count."""

    def test_returns_none_when_feature_disabled(
        self,
        disable_opensearch_migration: None,
    ) -> None:
        """Tests that task returns None when feature is disabled."""
        # Under test.
        result = migrate_documents_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is None

    def test_increments_counter_when_no_documents_to_migrate(
        self,
        db_session: Session,
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchClient,
        clean_migration_tables: None,
        enable_opensearch_migration: None,
    ) -> None:
        """Tests that counter increments when no documents need migration."""
