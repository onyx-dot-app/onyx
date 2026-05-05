"""External dependency tests for the new DocumentIndex interface.

These tests assume Vespa and OpenSearch are running.
"""

import time
import uuid
from collections.abc import Generator
from collections.abc import Iterator
from unittest.mock import patch

import httpx
import pytest

from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.interfaces_new import DocumentIndex as DocumentIndexNew
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchOldDocumentIndex,
)
from onyx.document_index.vespa.index import VespaIndex
from onyx.document_index.vespa.vespa_document_index import VespaDocumentIndex
from onyx.indexing.models import DocMetadataAwareIndexChunk
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.document_index.conftest import EMBEDDING_DIM
from tests.external_dependency_unit.document_index.conftest import make_chunk
from tests.external_dependency_unit.document_index.conftest import (
    make_indexing_metadata,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vespa_document_index(
    vespa_index: VespaIndex,  # noqa: ARG001 — ensures schema exists
    httpx_client: httpx.Client,
    test_index_name: str,
) -> Generator[VespaDocumentIndex, None, None]:
    yield VespaDocumentIndex(
        index_name=test_index_name,
        tenant_state=TenantState(tenant_id=TEST_TENANT_ID, multitenant=False),
        large_chunks_enabled=False,
        httpx_client=httpx_client,
    )


@pytest.fixture(scope="module")
def opensearch_document_index(
    opensearch_old_index: OpenSearchOldDocumentIndex,  # noqa: ARG001 — ensures index exists
    test_index_name: str,
) -> Generator[OpenSearchDocumentIndex, None, None]:
    yield OpenSearchDocumentIndex(
        tenant_state=TenantState(tenant_id=TEST_TENANT_ID, multitenant=False),
        index_name=test_index_name,
        embedding_dim=EMBEDDING_DIM,
        embedding_precision=EmbeddingPrecision.FLOAT,
    )


@pytest.fixture(scope="module")
def document_indices(
    vespa_document_index: VespaDocumentIndex,
    opensearch_document_index: OpenSearchDocumentIndex,
) -> Generator[list[DocumentIndexNew], None, None]:
    yield [opensearch_document_index, vespa_document_index]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDocumentIndexNew:
    """Tests the new DocumentIndex interface against real Vespa and OpenSearch."""

    def test_index_single_new_doc(
        self,
        document_indices: list[DocumentIndexNew],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Indexing a single new document returns one record with already_existed=False."""
        for document_index in document_indices:
            doc_id = f"test_single_new_{uuid.uuid4().hex[:8]}"
            chunk = make_chunk(doc_id)
            metadata = make_indexing_metadata([doc_id], old_counts=[0], new_counts=[1])

            results = document_index.index(chunks=[chunk], indexing_metadata=metadata)

            assert len(results) == 1
            assert results[0].document_id == doc_id
            assert results[0].already_existed is False

    def test_index_existing_doc_already_existed_true(
        self,
        document_indices: list[DocumentIndexNew],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Re-indexing a doc with previous chunks returns already_existed=True."""
        for document_index in document_indices:
            doc_id = f"test_existing_{uuid.uuid4().hex[:8]}"
            chunk = make_chunk(doc_id)

            # First index — brand new document.
            metadata_first = make_indexing_metadata(
                [doc_id], old_counts=[0], new_counts=[1]
            )
            document_index.index(chunks=[chunk], indexing_metadata=metadata_first)

            # Allow near-real-time indexing to settle (needed for Vespa).
            time.sleep(1)

            # Re-index — old_chunk_cnt=1 signals the document already existed.
            metadata_second = make_indexing_metadata(
                [doc_id], old_counts=[1], new_counts=[1]
            )
            results = document_index.index(
                chunks=[chunk], indexing_metadata=metadata_second
            )

            assert len(results) == 1
            assert results[0].already_existed is True

    def test_index_multiple_docs(
        self,
        document_indices: list[DocumentIndexNew],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Indexing multiple documents returns one record per unique document."""
        for document_index in document_indices:
            doc1 = f"test_multi_1_{uuid.uuid4().hex[:8]}"
            doc2 = f"test_multi_2_{uuid.uuid4().hex[:8]}"
            chunks = [
                make_chunk(doc1, chunk_id=0),
                make_chunk(doc1, chunk_id=1),
                make_chunk(doc2, chunk_id=0),
            ]
            metadata = make_indexing_metadata(
                [doc1, doc2], old_counts=[0, 0], new_counts=[2, 1]
            )

            results = document_index.index(chunks=chunks, indexing_metadata=metadata)

            result_map = {r.document_id: r.already_existed for r in results}
            assert len(result_map) == 2
            assert result_map[doc1] is False
            assert result_map[doc2] is False

    def test_index_deduplicates_doc_ids_in_results(
        self,
        document_indices: list[DocumentIndexNew],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Multiple chunks from the same document produce only one
        DocumentInsertionRecord."""
        for document_index in document_indices:
            doc_id = f"test_dedup_{uuid.uuid4().hex[:8]}"
            chunks = [make_chunk(doc_id, chunk_id=i) for i in range(5)]
            metadata = make_indexing_metadata([doc_id], old_counts=[0], new_counts=[5])

            results = document_index.index(chunks=chunks, indexing_metadata=metadata)

            assert len(results) == 1
            assert results[0].document_id == doc_id

    def test_index_mixed_new_and_existing_docs(
        self,
        document_indices: list[DocumentIndexNew],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A batch with both new and existing documents returns the correct
        already_existed flag for each."""
        for document_index in document_indices:
            existing_doc = f"test_mixed_exist_{uuid.uuid4().hex[:8]}"
            new_doc = f"test_mixed_new_{uuid.uuid4().hex[:8]}"

            # Pre-index the existing document.
            pre_chunk = make_chunk(existing_doc)
            pre_metadata = make_indexing_metadata(
                [existing_doc], old_counts=[0], new_counts=[1]
            )
            document_index.index(chunks=[pre_chunk], indexing_metadata=pre_metadata)

            time.sleep(2)

            # Now index a batch with the existing doc and a new doc.
            chunks = [
                make_chunk(existing_doc, chunk_id=0),
                make_chunk(new_doc, chunk_id=0),
            ]
            metadata = make_indexing_metadata(
                [existing_doc, new_doc], old_counts=[1, 0], new_counts=[1, 1]
            )

            results = document_index.index(chunks=chunks, indexing_metadata=metadata)

            result_map = {r.document_id: r.already_existed for r in results}
            assert len(result_map) == 2
            assert result_map[existing_doc] is True
            assert result_map[new_doc] is False

    def test_index_accepts_generator(
        self,
        document_indices: list[DocumentIndexNew],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """index() accepts a generator (any iterable), not just a list."""
        for document_index in document_indices:
            doc_id = f"test_gen_{uuid.uuid4().hex[:8]}"
            metadata = make_indexing_metadata([doc_id], old_counts=[0], new_counts=[3])

            def chunk_gen() -> Iterator[DocMetadataAwareIndexChunk]:
                for i in range(3):
                    yield make_chunk(doc_id, chunk_id=i)

            results = document_index.index(
                chunks=chunk_gen(), indexing_metadata=metadata
            )

            assert len(results) == 1
            assert results[0].document_id == doc_id
            assert results[0].already_existed is False

    def test_mt_cloud_opensearch_index_verification_only_happens_once(
        self,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """
        Tests that for multiple instantiations of OpenSearchDocumentIndex,
        verify_and_create_index_if_necessary is only called once given the same
        index name on multi-tenant cloud.
        """
        # Precondition.
        with patch.object(
            OpenSearchDocumentIndex, "verify_and_create_index_if_necessary"
        ) as mock_verify_and_create_index_if_necessary:
            assert mock_verify_and_create_index_if_necessary.call_count == 0

            test_index_name = "test_index_name_for_mt_cloud_index_verification"
            tenant_state = TenantState(tenant_id=TEST_TENANT_ID, multitenant=True)
            _ = OpenSearchDocumentIndex(
                tenant_state=tenant_state,
                index_name=test_index_name,
                embedding_dim=EMBEDDING_DIM,
                embedding_precision=EmbeddingPrecision.FLOAT,
            )
            assert mock_verify_and_create_index_if_necessary.call_count == 1

            # Under test.
            _ = OpenSearchDocumentIndex(
                tenant_state=tenant_state,
                index_name=test_index_name,
                embedding_dim=EMBEDDING_DIM,
                embedding_precision=EmbeddingPrecision.FLOAT,
            )

            # Postcondition.
            assert mock_verify_and_create_index_if_necessary.call_count == 1
