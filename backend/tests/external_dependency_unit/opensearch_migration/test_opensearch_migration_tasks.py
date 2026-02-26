"""External dependency tests for OpenSearch migration celery tasks.

These tests require Postgres, Redis, Vespa, and OpenSearch to be running.

WARNING: As with all external dependency tests, do not run them against a
database with data you care about. Your data will be destroyed.
"""

import json
from collections.abc import Generator
from copy import deepcopy
from datetime import datetime
from typing import Any
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.opensearch_migration.tasks import (
    is_continuation_token_done_for_all_slices,
)
from onyx.background.celery.tasks.opensearch_migration.tasks import (
    migrate_chunks_from_vespa_to_opensearch_task,
)
from onyx.background.celery.tasks.opensearch_migration.transformer import (
    transform_vespa_chunks_to_opensearch_chunks,
)
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.configs.constants import SOURCE_TYPE
from onyx.context.search.models import IndexFilters
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Document
from onyx.db.models import OpenSearchDocumentMigrationRecord
from onyx.db.models import OpenSearchTenantMigrationRecord
from onyx.db.opensearch_migration import build_sanitized_to_original_doc_id_mapping
from onyx.db.search_settings import get_active_search_settings
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.client import OpenSearchIndexClient
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
    opensearch_client: OpenSearchIndexClient, document_id: str, current_tenant_id: str
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
    opensearch_client: OpenSearchIndexClient, document_id: str, current_tenant_id: str
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
) -> Generator[OpenSearchIndexClient, None, None]:
    """Creates an OpenSearch client for the test tenant."""
    active = get_active_search_settings(db_session)
    yield OpenSearchIndexClient(index_name=active.primary.index_name)  # Test runs here.


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
def patch_get_vespa_chunks_page_size() -> Generator[int, None, None]:
    test_page_size = 5
    with patch(
        "onyx.background.celery.tasks.opensearch_migration.tasks.GET_VESPA_CHUNKS_PAGE_SIZE",
        test_page_size,
    ):
        yield test_page_size  # Test runs here.


@pytest.fixture(scope="function")
def test_documents(
    db_session: Session,
    vespa_document_index: VespaDocumentIndex,
    opensearch_client: OpenSearchIndexClient,
    patch_get_vespa_chunks_page_size: int,
) -> Generator[list[Document], None, None]:
    """
    Creates and cleans test Document records in Postgres and the document
    indices.
    """
    # We use a large number of documents >
    # get_all_raw_document_chunks_paginated's page_size argument in the task.
    documents_to_create = patch_get_vespa_chunks_page_size * 2
    doc_ids = [f"test_doc_{i}" for i in range(documents_to_create)]
    documents = _insert_test_documents_with_commit(db_session, doc_ids)

    # NOTE: chunk_count must be passed because index_raw_chunks uses the "new"
    # chunk ID system (get_uuid_from_chunk_info). Without chunk_count, delete()
    # falls back to the "old" system (get_uuid_from_chunk_info_old) and won't
    # find/delete the chunks.
    for document in documents:
        vespa_document_index.delete(document.id, chunk_count=CHUNK_COUNT)

    for document in documents:
        _delete_document_chunks_from_opensearch(
            opensearch_client, document.id, get_current_tenant_id()
        )

    yield documents  # Test runs here.

    # Cleanup.
    for document in documents:
        _delete_document_chunks_from_opensearch(
            opensearch_client, document.id, get_current_tenant_id()
        )

    for document in documents:
        vespa_document_index.delete(document.id, chunk_count=CHUNK_COUNT)

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


class TestMigrateChunksFromVespaToOpenSearchTask:
    """Tests migrate_chunks_from_vespa_to_opensearch_task."""

    def test_chunk_migration_completes_successfully(
        self,
        db_session: Session,
        test_documents: list[Document],
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchIndexClient,
        test_embedding_dimension: int,
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """
        Tests that all chunks are migrated from Vespa to OpenSearch.
        """
        # Precondition.
        # Index chunks into Vespa.
        document_chunks: dict[str, list[dict[str, Any]]] = {
            document.id: [
                _create_raw_document_chunk(
                    document_id=document.id,
                    chunk_index=i,
                    content=f"Test content {i} for {document.id}",
                    embedding=_generate_test_vector(test_embedding_dimension),
                    now=datetime.now(),
                    title=f"Test title {document.id}",
                    title_embedding=_generate_test_vector(test_embedding_dimension),
                )
                for i in range(CHUNK_COUNT)
            ]
            for document in test_documents
        }
        all_chunks: list[dict[str, Any]] = []
        for chunks in document_chunks.values():
            all_chunks.extend(chunks)
        vespa_document_index.index_raw_chunks(all_chunks)

        # Under test.
        result = migrate_chunks_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        # Verify tenant migration record was updated.
        tenant_record = db_session.query(OpenSearchTenantMigrationRecord).first()
        assert tenant_record is not None
        assert tenant_record.total_chunks_migrated == len(all_chunks)
        # Visit is complete so continuation token should be None.
        assert tenant_record.vespa_visit_continuation_token is not None
        assert is_continuation_token_done_for_all_slices(
            json.loads(tenant_record.vespa_visit_continuation_token)
        )
        assert tenant_record.migration_completed_at is not None
        assert tenant_record.approx_chunk_count_in_vespa == len(all_chunks)

        # Verify chunks were indexed in OpenSearch.
        for document in test_documents:
            opensearch_chunks = _get_document_chunks_from_opensearch(
                opensearch_client, document.id, get_current_tenant_id()
            )
            assert len(opensearch_chunks) == CHUNK_COUNT
            opensearch_chunks.sort(key=lambda x: x.chunk_index)
            for opensearch_chunk in opensearch_chunks:
                _assert_chunk_matches_vespa_chunk(
                    opensearch_chunk,
                    document_chunks[document.id][opensearch_chunk.chunk_index],
                )

    def test_chunk_migration_resumes_from_continuation_token(
        self,
        db_session: Session,
        test_documents: list[Document],
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchIndexClient,
        test_embedding_dimension: int,
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """Tests that chunk migration resumes from a saved continuation token.

        Simulates task time running out my mocking the locking behavior.
        """
        # Precondition.
        # Index chunks into Vespa.
        document_chunks: dict[str, list[dict[str, Any]]] = {
            document.id: [
                _create_raw_document_chunk(
                    document_id=document.id,
                    chunk_index=i,
                    content=f"Test content {i} for {document.id}",
                    embedding=_generate_test_vector(test_embedding_dimension),
                    now=datetime.now(),
                    title=f"Test title {document.id}",
                    title_embedding=_generate_test_vector(test_embedding_dimension),
                )
                for i in range(CHUNK_COUNT)
            ]
            for document in test_documents
        }
        all_chunks: list[dict[str, Any]] = []
        for chunks in document_chunks.values():
            all_chunks.extend(chunks)
        vespa_document_index.index_raw_chunks(all_chunks)

        # Run the initial batch. To simulate partial progress we will mock the
        # redis lock to return True for the first invocation of .owned() and
        # False subsequently.
        mock_redis_client = Mock()
        mock_lock = Mock()
        mock_lock.owned.side_effect = [True, False, False]
        mock_lock.acquire.return_value = True
        mock_redis_client.lock.return_value = mock_lock
        with patch(
            "onyx.background.celery.tasks.opensearch_migration.tasks.get_redis_client",
            return_value=mock_redis_client,
        ):
            result_1 = migrate_chunks_from_vespa_to_opensearch_task(
                tenant_id=get_current_tenant_id()
            )

        assert result_1 is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()

        # Verify partial progress was saved.
        tenant_record = db_session.query(OpenSearchTenantMigrationRecord).first()
        assert tenant_record is not None
        partial_chunks_migrated = tenant_record.total_chunks_migrated
        assert partial_chunks_migrated > 0
        assert tenant_record.vespa_visit_continuation_token is not None
        # Slices are not necessarily evenly distributed across all document
        # chunks so we can't test that every token is non-None, but certainly at
        # least one must be.
        assert any(json.loads(tenant_record.vespa_visit_continuation_token).values())
        assert tenant_record.migration_completed_at is None
        assert tenant_record.approx_chunk_count_in_vespa is not None

        # Under test.
        # Run the remainder of the migration.
        result_2 = migrate_chunks_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result_2 is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()

        # Verify completion.
        tenant_record = db_session.query(OpenSearchTenantMigrationRecord).first()
        assert tenant_record is not None
        assert tenant_record.total_chunks_migrated > partial_chunks_migrated
        assert tenant_record.total_chunks_migrated == len(all_chunks)
        # Visit is complete so continuation token should be None.
        assert tenant_record.vespa_visit_continuation_token is not None
        assert is_continuation_token_done_for_all_slices(
            json.loads(tenant_record.vespa_visit_continuation_token)
        )
        assert tenant_record.migration_completed_at is not None
        assert tenant_record.approx_chunk_count_in_vespa == len(all_chunks)

        # Verify chunks were indexed in OpenSearch.
        for document in test_documents:
            opensearch_chunks = _get_document_chunks_from_opensearch(
                opensearch_client, document.id, get_current_tenant_id()
            )
            assert len(opensearch_chunks) == CHUNK_COUNT
            opensearch_chunks.sort(key=lambda x: x.chunk_index)
            for opensearch_chunk in opensearch_chunks:
                _assert_chunk_matches_vespa_chunk(
                    opensearch_chunk,
                    document_chunks[document.id][opensearch_chunk.chunk_index],
                )

    def test_chunk_migration_empty_vespa(
        self,
        db_session: Session,
        # Get this just to ensure Vespa is clean from previous test runs.
        test_documents: list[Document],  # noqa: ARG002
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """
        Tests that chunk migration completes without error when Vespa is empty.
        """
        # Under test.
        # No chunks in Vespa.
        result = migrate_chunks_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        db_session.expire_all()
        tenant_record = db_session.query(OpenSearchTenantMigrationRecord).first()
        assert tenant_record is not None
        assert tenant_record.total_chunks_migrated == 0
        # Visit is complete so continuation token should be marked as done for all slices.
        assert tenant_record.vespa_visit_continuation_token is not None
        assert is_continuation_token_done_for_all_slices(
            json.loads(tenant_record.vespa_visit_continuation_token)
        )
        # Mark migration as completed even for empty Vespa.
        assert tenant_record.migration_completed_at is not None
        assert tenant_record.approx_chunk_count_in_vespa == 0

    def test_chunk_migration_updates_existing_chunks(
        self,
        db_session: Session,
        test_documents: list[Document],
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchIndexClient,
        test_embedding_dimension: int,
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """
        Tests that the migration task updates existing chunks in OpenSearch if
        they already exist.

        Chunks existing in the index is not a failure mode as the document may
        have been dual indexed. Since dual indexing indexes into Vespa first, we
        can assume that the state of the chunk we want to migrate is the most
        up-to-date.
        """
        # Precondition.
        # Index chunks into Vespa.
        document_chunks: dict[str, list[dict[str, Any]]] = {
            document.id: [
                _create_raw_document_chunk(
                    document_id=document.id,
                    chunk_index=i,
                    content=f"Test content {i} for {document.id}",
                    embedding=_generate_test_vector(test_embedding_dimension),
                    now=datetime.now(),
                    title=f"Test title {document.id}",
                    title_embedding=_generate_test_vector(test_embedding_dimension),
                )
                for i in range(CHUNK_COUNT)
            ]
            for document in test_documents
        }
        all_chunks: list[dict[str, Any]] = []
        for chunks in document_chunks.values():
            all_chunks.extend(chunks)
        vespa_document_index.index_raw_chunks(all_chunks)
        # Index the first document into OpenSearch with some different content.
        document_in_opensearch = deepcopy(document_chunks[test_documents[0].id])
        for chunk in document_in_opensearch:
            chunk["content"] = (
                f"Different content {chunk[CHUNK_ID]} for {test_documents[0].id}"
            )
        chunks_for_document_in_opensearch, _ = (
            transform_vespa_chunks_to_opensearch_chunks(
                document_in_opensearch,
                TenantState(tenant_id=get_current_tenant_id(), multitenant=False),
                {},
            )
        )
        opensearch_client.bulk_index_documents(
            documents=chunks_for_document_in_opensearch,
            tenant_state=TenantState(
                tenant_id=get_current_tenant_id(), multitenant=False
            ),
            update_if_exists=True,
        )

        # Under test.
        result = migrate_chunks_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        tenant_record = db_session.query(OpenSearchTenantMigrationRecord).first()
        assert tenant_record is not None
        assert tenant_record.total_chunks_migrated == len(all_chunks)
        # Visit is complete so continuation token should be None.
        assert tenant_record.vespa_visit_continuation_token is not None
        assert is_continuation_token_done_for_all_slices(
            json.loads(tenant_record.vespa_visit_continuation_token)
        )
        assert tenant_record.migration_completed_at is not None
        assert tenant_record.approx_chunk_count_in_vespa == len(all_chunks)

        # Verify chunks were indexed in OpenSearch.
        for document in test_documents:
            opensearch_chunks = _get_document_chunks_from_opensearch(
                opensearch_client, document.id, get_current_tenant_id()
            )
            assert len(opensearch_chunks) == CHUNK_COUNT
            opensearch_chunks.sort(key=lambda x: x.chunk_index)
            for opensearch_chunk in opensearch_chunks:
                _assert_chunk_matches_vespa_chunk(
                    opensearch_chunk,
                    document_chunks[document.id][opensearch_chunk.chunk_index],
                )

    def test_chunk_migration_noops_when_migration_is_complete(
        self,
        db_session: Session,
        test_documents: list[Document],
        vespa_document_index: VespaDocumentIndex,
        opensearch_client: OpenSearchIndexClient,
        test_embedding_dimension: int,
        clean_migration_tables: None,  # noqa: ARG002
        enable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """
        Tests that the migration task no-ops when the migration is complete.
        """
        # Precondition.
        # Index chunks into Vespa.
        document_chunks: dict[str, list[dict[str, Any]]] = {
            document.id: [
                _create_raw_document_chunk(
                    document_id=document.id,
                    chunk_index=i,
                    content=f"Test content {i} for {document.id}",
                    embedding=_generate_test_vector(test_embedding_dimension),
                    now=datetime.now(),
                    title=f"Test title {document.id}",
                    title_embedding=_generate_test_vector(test_embedding_dimension),
                )
                for i in range(CHUNK_COUNT)
            ]
            for document in test_documents
        }
        all_chunks: list[dict[str, Any]] = []
        for chunks in document_chunks.values():
            all_chunks.extend(chunks)
        vespa_document_index.index_raw_chunks(all_chunks)

        # Under test.
        # First run.
        result_1 = migrate_chunks_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result_1 is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        tenant_record = db_session.query(OpenSearchTenantMigrationRecord).first()
        assert tenant_record is not None
        assert tenant_record.total_chunks_migrated == len(all_chunks)
        # Visit is complete so continuation token should be None.
        assert tenant_record.vespa_visit_continuation_token is not None
        assert is_continuation_token_done_for_all_slices(
            json.loads(tenant_record.vespa_visit_continuation_token)
        )
        assert tenant_record.migration_completed_at is not None
        assert tenant_record.approx_chunk_count_in_vespa == len(all_chunks)

        # Verify chunks were indexed in OpenSearch.
        for document in test_documents:
            opensearch_chunks = _get_document_chunks_from_opensearch(
                opensearch_client, document.id, get_current_tenant_id()
            )
            assert len(opensearch_chunks) == CHUNK_COUNT
            opensearch_chunks.sort(key=lambda x: x.chunk_index)
            for opensearch_chunk in opensearch_chunks:
                _assert_chunk_matches_vespa_chunk(
                    opensearch_chunk,
                    document_chunks[document.id][opensearch_chunk.chunk_index],
                )

        # Under test.
        # Second run.
        result_2 = migrate_chunks_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result_2 is True
        # Expire the session cache to see the committed changes from the task.
        db_session.expire_all()
        # This all should be unchanged.
        tenant_record = db_session.query(OpenSearchTenantMigrationRecord).first()
        assert tenant_record is not None
        assert tenant_record.total_chunks_migrated == len(all_chunks)
        # Visit is complete so continuation token should be None.
        assert tenant_record.vespa_visit_continuation_token is not None
        assert is_continuation_token_done_for_all_slices(
            json.loads(tenant_record.vespa_visit_continuation_token)
        )
        assert tenant_record.migration_completed_at is not None
        assert tenant_record.approx_chunk_count_in_vespa == len(all_chunks)

        # Verify chunks were indexed in OpenSearch.
        for document in test_documents:
            opensearch_chunks = _get_document_chunks_from_opensearch(
                opensearch_client, document.id, get_current_tenant_id()
            )
            assert len(opensearch_chunks) == CHUNK_COUNT
            opensearch_chunks.sort(key=lambda x: x.chunk_index)
            for opensearch_chunk in opensearch_chunks:
                _assert_chunk_matches_vespa_chunk(
                    opensearch_chunk,
                    document_chunks[document.id][opensearch_chunk.chunk_index],
                )

    def test_returns_none_when_feature_disabled(
        self,
        disable_opensearch_indexing_for_onyx: None,  # noqa: ARG002
    ) -> None:
        """Tests that task returns None when feature is disabled."""
        # Under test.
        result = migrate_chunks_from_vespa_to_opensearch_task(
            tenant_id=get_current_tenant_id()
        )

        # Postcondition.
        assert result is None

    def test_vespa_get_chunk_count(
        self,
        vespa_document_index: VespaDocumentIndex,
        test_embedding_dimension: int,
    ) -> None:
        """
        Tests that the VespaDocumentIndex.get_chunk_count() method returns the
        correct number of chunks.
        """
        # Precondition.
        # Index chunks into Vespa.
        all_chunks = [
            _create_raw_document_chunk(
                document_id="test_doc_1",
                chunk_index=i,
                content=f"Test content {i} for test_doc_1",
                embedding=_generate_test_vector(test_embedding_dimension),
                now=datetime.now(),
                title=f"Test title {i}",
                title_embedding=_generate_test_vector(test_embedding_dimension),
            )
            for i in range(500)
        ]
        vespa_document_index.index_raw_chunks(all_chunks)

        # Under test.
        chunk_count = vespa_document_index.get_chunk_count()

        # Postcondition.
        assert chunk_count == len(all_chunks)


class TestSanitizedDocIdResolution:
    """Tests document ID resolution functions."""

    def test_resolve_sanitized_document_ids_batch_normal(
        self,
        db_session: Session,
        test_documents: list[Document],  # noqa: ARG002
    ) -> None:
        """
        Tests batch resolution for normal document IDs (no sanitization needed).
        """
        # Under test.
        result = build_sanitized_to_original_doc_id_mapping(db_session)

        # Postcondition.
        # Since we expect no IDs in test_documents to need sanitization, the
        # result should be empty.
        assert not result

    def test_resolve_sanitized_document_ids_batch_with_quotes(
        self,
        db_session: Session,
    ) -> None:
        """Tests batch resolution for a document ID containing single quotes."""
        # Precondition.
        # Create a document with a single quote in its ID.
        original_id = "test_doc_with'quote"
        sanitized_id = "test_doc_with_quote"
        document = Document(
            id=original_id,
            semantic_id=original_id,
            chunk_count=1,
        )
        try:
            db_session.add(document)
            db_session.commit()

            # Under test.
            result = build_sanitized_to_original_doc_id_mapping(db_session)

            # Postcondition.
            assert len(result) == 1
            # The sanitized version should map to the original.
            assert sanitized_id in result
            assert result[sanitized_id] == original_id

        finally:
            _delete_test_documents_with_commit(db_session, [document])

    def test_raises_when_sanitized_id_matches_another_document(
        self,
        db_session: Session,
    ) -> None:
        """
        Tests that the function raises when a sanitized ID matches another
        document's original ID.
        """
        # Precondition.
        # Create a document with a single quote in its ID, and another document
        # with that string as its ID.
        original_id = "test_doc_with'quote"
        sanitized_id = "test_doc_with_quote"
        document_bad = Document(
            id=original_id,
            semantic_id=original_id,
            chunk_count=1,
        )
        document_fine = Document(
            id=sanitized_id,
            semantic_id=sanitized_id,
            chunk_count=1,
        )
        try:
            db_session.add(document_bad)
            db_session.add(document_fine)
            db_session.commit()

            # Under test.
            with pytest.raises(RuntimeError):
                build_sanitized_to_original_doc_id_mapping(db_session)

        finally:
            _delete_test_documents_with_commit(
                db_session, [document_bad, document_fine]
            )
