"""External dependency tests for OpenSearch migration celery tasks.

These tests require Postgres, Redis, Vespa, and OpenSearch to be running.

WARNING: As with all external dependency tests, do not run them against a
database with data you care about. Your data will be destroyed.
"""

from collections.abc import Generator
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.opensearch_migration.constants import (
    TOTAL_ALLOWABLE_DOC_MIGRATION_ATTEMPTS_BEFORE_PERMANENT_FAILURE,
)
from onyx.background.celery.tasks.opensearch_migration.tasks import (
    check_for_documents_for_opensearch_migration_task,
)
from onyx.background.celery.tasks.opensearch_migration.tasks import (
    migrate_documents_from_vespa_to_opensearch_task,
)
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.configs.constants import SOURCE_TYPE
from onyx.context.search.models import IndexFilters
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import OpenSearchDocumentMigrationStatus
from onyx.db.enums import OpenSearchTenantMigrationStatus
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
from onyx.document_index.vespa_constants import ACCESS_CONTROL_LIST
from onyx.document_index.vespa_constants import BLURB
from onyx.document_index.vespa_constants import BOOST
from onyx.document_index.vespa_constants import CHUNK_CONTEXT
from onyx.document_index.vespa_constants import CHUNK_ID
from onyx.document_index.vespa_constants import CONTENT
from onyx.document_index.vespa_constants import DOC_SUMMARY
from onyx.document_index.vespa_constants import DOC_UPDATED_AT
from onyx.document_index.vespa_constants import DOCUMENT_ID
from onyx.document_index.vespa_constants import DOCUMENT_SETS
from onyx.document_index.vespa_constants import EMBEDDINGS
from onyx.document_index.vespa_constants import FULL_CHUNK_EMBEDDING_KEY
from onyx.document_index.vespa_constants import HIDDEN
from onyx.document_index.vespa_constants import IMAGE_FILE_NAME
from onyx.document_index.vespa_constants import METADATA_LIST
from onyx.document_index.vespa_constants import METADATA_SUFFIX
from onyx.document_index.vespa_constants import PRIMARY_OWNERS
from onyx.document_index.vespa_constants import SECONDARY_OWNERS
from onyx.document_index.vespa_constants import SEMANTIC_IDENTIFIER
from onyx.document_index.vespa_constants import SOURCE_LINKS
from onyx.document_index.vespa_constants import TITLE
from onyx.document_index.vespa_constants import TITLE_EMBEDDING
from onyx.document_index.vespa_constants import USER_PROJECT
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.full_setup import ensure_full_deployment_setup


CHUNK_COUNT = 5


def _get_document_chunks_from_opensearch(
    opensearch_client: OpenSearchClient, document_id: str, current_tenant_id: str
) -> list[DocumentChunk]:
    opensearch_client.refresh_index()
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


def _delete_document_chunks_from_opensearch(
    opensearch_client: OpenSearchClient, document_id: str, current_tenant_id: str
) -> None:
    opensearch_client.refresh_index()
    query_body = DocumentQuery.delete_from_document_id_query(
        document_id=document_id,
        tenant_state=TenantState(tenant_id=current_tenant_id, multitenant=False),
    )
    opensearch_client.delete_by_query(query_body)


def _generate_test_vector(dim: int) -> list[float]:
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
            chunk_count=CHUNK_COUNT,
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
    now: datetime,
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
        SOURCE_TYPE: "test source type",
        METADATA_LIST: ["stuff=things"],
        DOC_UPDATED_AT: int(now.timestamp()),
        HIDDEN: False,
        BOOST: 1,
        SEMANTIC_IDENTIFIER: "test semantic identifier",
        IMAGE_FILE_NAME: "test.png",
        SOURCE_LINKS: "https://test.com",
        BLURB: "test blurb",
        DOC_SUMMARY: "test doc summary",
        CHUNK_CONTEXT: "test chunk context",
        METADATA_SUFFIX: "test metadata suffix",
        DOCUMENT_SETS: {"test document set": 1},
        USER_PROJECT: [1],
        PRIMARY_OWNERS: ["test primary owner"],
        SECONDARY_OWNERS: ["test secondary owner"],
        ACCESS_CONTROL_LIST: {PUBLIC_DOC_PAT: 1, "test user": 1},
    }


def _assert_chunk_matches_vespa_chunk(
    opensearch_chunk: DocumentChunk,
    vespa_chunk: dict[str, Any],
) -> None:
    assert opensearch_chunk.document_id == vespa_chunk[DOCUMENT_ID]
    assert opensearch_chunk.chunk_index == vespa_chunk[CHUNK_ID]
    assert opensearch_chunk.content == vespa_chunk[CONTENT]
    assert opensearch_chunk.content_vector == pytest.approx(
        vespa_chunk[EMBEDDINGS][FULL_CHUNK_EMBEDDING_KEY]
    )
    assert opensearch_chunk.title == vespa_chunk[TITLE]
    assert opensearch_chunk.title_vector == pytest.approx(vespa_chunk[TITLE_EMBEDDING])
    assert opensearch_chunk.source_type == vespa_chunk[SOURCE_TYPE]
    assert opensearch_chunk.metadata_list == vespa_chunk[METADATA_LIST]
    assert (
        opensearch_chunk.last_updated is not None
        and int(opensearch_chunk.last_updated.timestamp())
        == vespa_chunk[DOC_UPDATED_AT]
    )
    assert opensearch_chunk.public == vespa_chunk[ACCESS_CONTROL_LIST][PUBLIC_DOC_PAT]
    assert opensearch_chunk.access_control_list == [
        access_control
        for access_control in vespa_chunk[ACCESS_CONTROL_LIST]
        if access_control != PUBLIC_DOC_PAT
    ]
    assert opensearch_chunk.hidden == vespa_chunk[HIDDEN]
    assert opensearch_chunk.global_boost == vespa_chunk[BOOST]
    assert opensearch_chunk.semantic_identifier == vespa_chunk[SEMANTIC_IDENTIFIER]
    assert opensearch_chunk.image_file_id == vespa_chunk[IMAGE_FILE_NAME]
    assert opensearch_chunk.source_links == vespa_chunk[SOURCE_LINKS]
    assert opensearch_chunk.blurb == vespa_chunk[BLURB]
    assert opensearch_chunk.doc_summary == vespa_chunk[DOC_SUMMARY]
    assert opensearch_chunk.chunk_context == vespa_chunk[CHUNK_CONTEXT]
    assert opensearch_chunk.metadata_suffix == vespa_chunk[METADATA_SUFFIX]
    assert opensearch_chunk.document_sets == [
        doc_set for doc_set in vespa_chunk[DOCUMENT_SETS]
    ]
    assert opensearch_chunk.user_projects == vespa_chunk[USER_PROJECT]
    assert opensearch_chunk.primary_owners == vespa_chunk[PRIMARY_OWNERS]
    assert opensearch_chunk.secondary_owners == vespa_chunk[SECONDARY_OWNERS]


@pytest.fixture(scope="module")
def full_deployment_setup() -> Generator[None, None, None]:
    """Optional fixture to perform full deployment-like setup on demand.

    Imports and calls
    tests.external_dependency_unit.startup.full_setup.ensure_full_deployment_setup
    to initialize Postgres defaults, Vespa indices, and seed initial docs.

    NOTE: We deliberately duplicate this logic from
    backend/tests/external_dependency_unit/conftest.py because we need to set
    opensearch_available just for this module, not the entire test session.
    """
    # Patch ENABLE_OPENSEARCH_INDEXING_FOR_ONYX just for this test because we
    # don't yet want that enabled for all tests.
    # TODO(andrei): Remove this once CI enables OpenSearch for all tests.
    with (
        patch(
            "onyx.configs.app_configs.ENABLE_OPENSEARCH_INDEXING_FOR_ONYX",
            True,
        ),
        patch("onyx.document_index.factory.ENABLE_OPENSEARCH_INDEXING_FOR_ONYX", True),
    ):
        ensure_full_deployment_setup(opensearch_available=True)
        yield  # Test runs here.


@pytest.fixture(scope="module")
def db_session(
    full_deployment_setup: None,  # noqa: ARG001
) -> Generator[Session, None, None]:
    """
    NOTE: We deliberately duplicate this logic from
    backend/tests/external_dependency_unit/conftest.py because we need a
    module-level fixture whereas the fixture in that file is function-level. I
    don't want to change it in this change to not risk inadvertently breaking
    things.
    """
    with get_session_with_current_tenant() as session:
        yield session  # Test runs here.


@pytest.fixture(scope="module")
def vespa_document_index(
    db_session: Session,
    full_deployment_setup: None,  # noqa: ARG001
) -> Generator[VespaDocumentIndex, None, None]:
    """Creates a Vespa document index for the test tenant."""
    active = get_active_search_settings(db_session)
    yield VespaDocumentIndex(
        index_name=active.primary.index_name,
        tenant_state=TenantState(tenant_id=get_current_tenant_id(), multitenant=False),
        large_chunks_enabled=False,
    )  # Test runs here.


@pytest.fixture(scope="module")
def opensearch_client(
    db_session: Session,
    full_deployment_setup: None,  # noqa: ARG001
) -> Generator[OpenSearchClient, None, None]:
    """Creates an OpenSearch client for the test tenant."""
    active = get_active_search_settings(db_session)
    yield OpenSearchClient(index_name=active.primary.index_name)  # Test runs here.


@pytest.fixture(scope="module")
def opensearch_available(
    opensearch_client: OpenSearchClient,
) -> Generator[None, None, None]:
    """Verifies OpenSearch is running, fails the test if not."""
    if not wait_for_opensearch_with_timeout(client=opensearch_client):
        pytest.fail("OpenSearch is not available.")
    yield  # Test runs here.


@pytest.fixture(scope="module")
def vespa_available(
    full_deployment_setup: None,  # noqa: ARG001
) -> Generator[None, None, None]:
    """Verifies Vespa is running, fails the test if not."""
    # Try 90 seconds for testing in CI.
    if not wait_for_vespa_with_timeout(wait_limit=90):
        pytest.fail("Vespa is not available.")
    yield  # Test runs here.


@pytest.fixture(scope="module")
def test_embedding_dimension(db_session: Session) -> Generator[int, None, None]:
    active = get_active_search_settings(db_session)
    yield active.primary.model_dim  # Test runs here.


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


@pytest.fixture(scope="function")
def clean_vespa(
    vespa_document_index: VespaDocumentIndex, test_documents: list[Document]
) -> Generator[None, None, None]:
    # NOTE: chunk_count must be passed because index_raw_chunks uses the "new"
    # chunk ID system (get_uuid_from_chunk_info). Without chunk_count, delete()
    # falls back to the "old" system (get_uuid_from_chunk_info_old) and won't
    # find/delete the chunks.
    for document in test_documents:
        vespa_document_index.delete(document.id, chunk_count=CHUNK_COUNT)
    yield  # Test runs here.
    for document in test_documents:
        vespa_document_index.delete(document.id, chunk_count=CHUNK_COUNT)


@pytest.fixture(scope="function")
def clean_opensearch(
    opensearch_client: OpenSearchClient, test_documents: list[Document]
) -> Generator[None, None, None]:
    for document in test_documents:
        _delete_document_chunks_from_opensearch(
            opensearch_client, document.id, get_current_tenant_id()
        )
    yield  # Test runs here.
    for document in test_documents:
        _delete_document_chunks_from_opensearch(
            opensearch_client, document.id, get_current_tenant_id()
        )


class TestCheckForDocumentsForOpenSearchMigrationTask:
    """Tests check_for_documents_for_opensearch_migration_task."""

    def test_creates_migration_records_for_documents(
        self,
        db_session: Session,
        test_documents: list[Document],
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """Tests that migration records are created for documents in the DB."""
        # Under test.
        result = check_for_documents_for_opensearch_migration_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
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
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """Tests that pagination picks up from the last migrated document ID."""
        # Precondition.
        # Pre-create migration records for first n - 1 docs.
        n = len(test_documents)
        create_opensearch_migration_records_with_commit(
            db_session, [doc.id for doc in test_documents[: n - 1]]
        )
        # Verify last document ID - should be the last one with a migration record.
        last_id = get_last_opensearch_migration_document_id(db_session)
        assert last_id == test_documents[n - 2].id

        # Under test.
        result = check_for_documents_for_opensearch_migration_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
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
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
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
        disable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
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
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """Tests that counter increments when no records to populate."""
        # Precondition.
        # Create migration records for all documents so there are none left.
        create_opensearch_migration_records_with_commit(
            db_session, [doc.id for doc in test_documents]
        )

        # Under test.
        result = check_for_documents_for_opensearch_migration_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        # Verify counter was incremented.
        tenant_record = db_session.query(OpenSearchTenantMigrationRecord).first()
        assert tenant_record is not None
        assert (
            tenant_record.num_times_observed_no_additional_docs_to_populate_migration_table
            >= 1
        )

    def test_creates_singleton_migration_record(
        self,
        db_session: Session,
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """Tests that singleton migration record is created."""
        # Under test.
        result = check_for_documents_for_opensearch_migration_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        # Verify the singleton migration record was created.
        tenant_record = db_session.query(OpenSearchTenantMigrationRecord).first()
        assert tenant_record is not None
        assert (
            tenant_record.document_migration_record_table_population_status
            == OpenSearchTenantMigrationStatus.PENDING
        )
        assert (
            tenant_record.num_times_observed_no_additional_docs_to_populate_migration_table
            == 1
        )
        assert (
            tenant_record.overall_document_migration_status
            == OpenSearchTenantMigrationStatus.PENDING
        )
        assert tenant_record.num_times_observed_no_additional_docs_to_migrate == 0
        assert tenant_record.last_updated_at is not None


class TestMigrateDocumentsFromVespaToOpenSearchTask:
    """Tests migrate_documents_from_vespa_to_opensearch_task."""

    def test_migrates_document_successfully(
        self,
        db_session: Session,
        test_documents: list[Document],
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchClient,
        test_embedding_dimension: int,
        clean_migration_tables: None,  # noqa: ARG002
        clean_vespa: None,  # noqa: ARG002
        clean_opensearch: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """Tests successful migration of a document from Vespa to OpenSearch."""
        # Precondition.
        create_opensearch_migration_records_with_commit(
            db_session, [doc.id for doc in test_documents]
        )
        document_chunks = {
            document.id: [
                _create_raw_document_chunk(
                    document_id=document.id,
                    chunk_index=i,
                    content=f"Test content {i}",
                    embedding=_generate_test_vector(test_embedding_dimension),
                    now=datetime.now(),
                    title=f"Test title {document.id}",
                    title_embedding=_generate_test_vector(test_embedding_dimension),
                )
                for i in range(CHUNK_COUNT)
            ]
            for document in test_documents
        }
        document_chunks_list = []
        for document in test_documents:
            document_chunks_list.extend(document_chunks[document.id])
        vespa_document_index.index_raw_chunks(document_chunks_list)

        # Under test.
        result = migrate_documents_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        # Verify migration records were updated.
        for document in test_documents:
            record = (
                db_session.query(OpenSearchDocumentMigrationRecord)
                .filter(OpenSearchDocumentMigrationRecord.document_id == document.id)
                .first()
            )
            assert record is not None
            assert record.status == OpenSearchDocumentMigrationStatus.COMPLETED
            assert record.attempts_count == 1
        # Verify chunks were indexed in OpenSearch.
        for document in test_documents:
            chunks = _get_document_chunks_from_opensearch(
                opensearch_client, document.id, get_current_tenant_id()
            )
            assert len(chunks) == CHUNK_COUNT
            # Chunks are not guaranteed to be in order.
            chunks.sort(key=lambda x: x.chunk_index)
            for i, chunk in enumerate(chunks):
                _assert_chunk_matches_vespa_chunk(
                    chunk, document_chunks[document.id][i]
                )

    def test_marks_document_as_failed_on_error(
        self,
        db_session: Session,
        test_documents: list[Document],
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchClient,
        test_embedding_dimension: int,
        clean_migration_tables: None,  # noqa: ARG002
        clean_vespa: None,  # noqa: ARG002
        clean_opensearch: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """Tests that documents are marked as FAILED when migration fails."""
        # Precondition.
        create_opensearch_migration_records_with_commit(
            db_session, [doc.id for doc in test_documents]
        )
        # Don't create chunks in Vespa so migration fails for the target doc.
        doc_ids_that_have_chunks = [doc.id for doc in test_documents[:-1]]
        document_chunks = {
            document_id: [
                _create_raw_document_chunk(
                    document_id=document_id,
                    chunk_index=i,
                    content=f"Test content {i}",
                    embedding=_generate_test_vector(test_embedding_dimension),
                    now=datetime.now(),
                    title=f"Test title {document_id}",
                    title_embedding=_generate_test_vector(test_embedding_dimension),
                )
                for i in range(CHUNK_COUNT)
            ]
            for document_id in doc_ids_that_have_chunks
        }
        document_chunks_list = []
        for document_id in doc_ids_that_have_chunks:
            document_chunks_list.extend(document_chunks[document_id])
        vespa_document_index.index_raw_chunks(document_chunks_list)

        # Under test.
        result = migrate_documents_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        # Verify migration records were updated.
        for document_id in doc_ids_that_have_chunks:
            record = (
                db_session.query(OpenSearchDocumentMigrationRecord)
                .filter(OpenSearchDocumentMigrationRecord.document_id == document_id)
                .first()
            )
            assert record is not None
            assert record.status == OpenSearchDocumentMigrationStatus.COMPLETED
            assert record.attempts_count == 1
        # Verify the target doc was marked as FAILED.
        record = (
            db_session.query(OpenSearchDocumentMigrationRecord)
            .filter(
                OpenSearchDocumentMigrationRecord.document_id == test_documents[-1].id
            )
            .first()
        )
        assert record is not None
        # In practice the task keeps trying docs until it either runs out of
        # time or the lock is lost, which will not happen during this test.
        # Because of this the migration record will just shift to permanently
        # failed. Let's just test for that here.
        assert record.status == OpenSearchDocumentMigrationStatus.PERMANENTLY_FAILED
        # Verify chunks were indexed in OpenSearch.
        for document_id in doc_ids_that_have_chunks:
            chunks = _get_document_chunks_from_opensearch(
                opensearch_client, document_id, get_current_tenant_id()
            )
            assert len(chunks) == CHUNK_COUNT
            # Chunks are not guaranteed to be in order.
            chunks.sort(key=lambda x: x.chunk_index)
            for j, chunk in enumerate(chunks):
                _assert_chunk_matches_vespa_chunk(
                    chunk, document_chunks[document_id][j]
                )
        # Verify the target doc was not indexed in OpenSearch.
        chunks = _get_document_chunks_from_opensearch(
            opensearch_client, test_documents[-1].id, get_current_tenant_id()
        )
        assert len(chunks) == 0

    def test_marks_document_as_permanently_failed_after_max_attempts(
        self,
        db_session: Session,
        test_documents: list[Document],
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """
        Tests that documents are marked as PERMANENTLY_FAILED after max
        attempts.
        """
        # Precondition.
        # Let's only just make one record.
        migration_record = OpenSearchDocumentMigrationRecord(
            document_id=test_documents[0].id,
            status=OpenSearchDocumentMigrationStatus.FAILED,
            attempts_count=TOTAL_ALLOWABLE_DOC_MIGRATION_ATTEMPTS_BEFORE_PERMANENT_FAILURE
            - 1,
        )
        _insert_test_migration_records_with_commit(db_session, [migration_record])
        # Don't create chunks in Vespa so migration fails.

        # Under test.
        result = migrate_documents_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        record = (
            db_session.query(OpenSearchDocumentMigrationRecord)
            .filter(
                OpenSearchDocumentMigrationRecord.document_id
                == migration_record.document_id
            )
            .first()
        )
        assert record is not None
        assert record.status == OpenSearchDocumentMigrationStatus.PERMANENTLY_FAILED
        assert (
            record.attempts_count
            == TOTAL_ALLOWABLE_DOC_MIGRATION_ATTEMPTS_BEFORE_PERMANENT_FAILURE
        )

    def test_fails_if_chunk_count_is_none(
        self,
        db_session: Session,
        test_documents: list[Document],
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """Tests that migration fails if document has no chunk_count."""
        # Precondition.
        # Let's just use one doc only.
        test_documents[0].chunk_count = None
        db_session.commit()
        migration_record = OpenSearchDocumentMigrationRecord(
            document_id=test_documents[0].id
        )
        _insert_test_migration_records_with_commit(db_session, [migration_record])

        # Under test.
        result = migrate_documents_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        record = (
            db_session.query(OpenSearchDocumentMigrationRecord)
            .filter(
                OpenSearchDocumentMigrationRecord.document_id == test_documents[0].id
            )
            .first()
        )
        assert record is not None
        # In practice the task keeps trying docs until it either runs out of
        # time or the lock is lost, which will not happen during this test.
        # Because of this the migration record will just shift to permanently
        # failed. Let's just test for that here.
        assert record.status == OpenSearchDocumentMigrationStatus.PERMANENTLY_FAILED
        assert record.error_message is not None
        assert "no chunk count" in record.error_message.lower()

    def test_returns_none_when_feature_disabled(
        self,
        disable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
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
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """Tests that counter increments when no documents need migration."""
        # Precondition.
        # No migration records exist so there are no documents to migrate.

        # Under test.
        result = migrate_documents_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        tenant_record = db_session.query(OpenSearchTenantMigrationRecord).first()
        assert tenant_record is not None
        assert tenant_record.num_times_observed_no_additional_docs_to_migrate >= 1
