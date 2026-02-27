"""External dependency tests for the old DocumentIndex interface.

These tests assume Vespa and OpenSearch are running.

TODO(ENG-3764)(andrei): Consolidate some of these test fixtures.
"""

import uuid
from collections.abc import Generator

import httpx
import pytest

from onyx.access.models import DocumentAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.context.search.models import IndexFilters
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import IndexBatchParams
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.document_index.opensearch.client import wait_for_opensearch_with_timeout
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchOldDocumentIndex,
)
from onyx.document_index.vespa.index import VespaIndex
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa.shared_utils.utils import wait_for_vespa_with_timeout
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocMetadataAwareIndexChunk
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture(scope="module")
def vespa_available() -> Generator[None, None, None]:
    """Verifies Vespa is running, fails the test if not."""
    # Try 90 seconds for testing in CI.
    if not wait_for_vespa_with_timeout(wait_limit=90):
        pytest.fail("Vespa is not available.")
    yield  # Test runs here.


@pytest.fixture(scope="module")
def opensearch_available() -> Generator[None, None, None]:
    """Verifies OpenSearch is running, fails the test if not."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    yield  # Test runs here.


@pytest.fixture(scope="module")
def test_index_name() -> Generator[str, None, None]:
    yield f"test_index_{uuid.uuid4().hex[:8]}"  # Test runs here.


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    """Sets up tenant context for testing."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield  # Test runs here.
    finally:
        # Reset the tenant context after the test
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="module")
def httpx_client() -> Generator[httpx.Client, None, None]:
    yield get_vespa_http_client()


@pytest.fixture(scope="module")
def vespa_document_index(
    vespa_available: None,  # noqa: ARG001
    httpx_client: httpx.Client,
    tenant_context: None,  # noqa: ARG001
    test_index_name: str,
) -> Generator[VespaIndex, None, None]:
    vespa_index = VespaIndex(
        index_name=test_index_name,
        secondary_index_name=None,
        large_chunks_enabled=False,
        secondary_large_chunks_enabled=None,
        multitenant=MULTI_TENANT,
        httpx_client=httpx_client,
    )
    vespa_index.ensure_indices_exist(
        primary_embedding_dim=128,
        primary_embedding_precision=EmbeddingPrecision.FLOAT,
        secondary_index_embedding_dim=None,
        secondary_index_embedding_precision=None,
    )

    yield vespa_index  # Test runs here.

    # TODO(ENG-3765)(andrei): Explicitly cleanup index. Not immediately
    # pressing; in CI we should be using fresh instances of dependencies each
    # time anyway.


@pytest.fixture(scope="module")
def opensearch_document_index(
    opensearch_available: None,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
    test_index_name: str,
) -> Generator[OpenSearchOldDocumentIndex, None, None]:
    opensearch_index = OpenSearchOldDocumentIndex(
        index_name=test_index_name,
        embedding_dim=128,
        embedding_precision=EmbeddingPrecision.FLOAT,
        secondary_index_name=None,
        large_chunks_enabled=False,
        secondary_large_chunks_enabled=None,
        multitenant=MULTI_TENANT,
    )
    opensearch_index.ensure_indices_exist(
        primary_embedding_dim=128,
        primary_embedding_precision=EmbeddingPrecision.FLOAT,
        secondary_index_embedding_dim=None,
        secondary_index_embedding_precision=None,
    )

    yield opensearch_index  # Test runs here.

    # TODO(ENG-3765)(andrei): Explicitly cleanup index. Not immediately
    # pressing; in CI we should be using fresh instances of dependencies each
    # time anyway.


@pytest.fixture(scope="module")
def document_indices(
    vespa_document_index: VespaIndex,
    opensearch_document_index: OpenSearchOldDocumentIndex,
) -> Generator[list[DocumentIndex], None, None]:
    # Ideally these are parametrized; doing so with pytest fixtures is tricky.
    yield [vespa_document_index, opensearch_document_index]  # Test runs here.


@pytest.fixture(scope="function")
def chunks() -> Generator[list[DocMetadataAwareIndexChunk], None, None]:
    result = []
    chunk_count = 5
    doc_id = "test_doc"
    tenant_id = get_current_tenant_id()
    access = DocumentAccess.build(
        user_emails=[],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=True,
    )
    document_sets: set[str] = set()
    user_project: list[int] = list()
    personas: list[int] = list()
    boost = 0
    blurb = ""
    content = ""
    title_prefix = ""
    doc_summary = ""
    chunk_context = ""
    title_embedding = None
    embeddings = ChunkEmbedding(full_embedding=[0] * 128, mini_chunk_embeddings=[])
    source_document = Document(
        id=doc_id, semantic_identifier="", source=DocumentSource.FILE
    )
    metadata_suffix_keyword = ""
    image_file_id = None
    source_links = None
    ancestor_hierarchy_node_ids: list[int] = []
    for i in range(chunk_count):
        result.append(
            DocMetadataAwareIndexChunk(
                tenant_id=tenant_id,
                access=access,
                document_sets=document_sets,
                user_project=user_project,
                personas=personas,
                boost=boost,
                aggregated_chunk_boost_factor=0,
                ancestor_hierarchy_node_ids=ancestor_hierarchy_node_ids,
                embeddings=embeddings,
                title_embedding=title_embedding,
                source_document=source_document,
                title_prefix=title_prefix,
                metadata_suffix_keyword=metadata_suffix_keyword,
                metadata_suffix_semantic="",
                contextual_rag_reserved_tokens=0,
                doc_summary=doc_summary,
                chunk_context=chunk_context,
                mini_chunk_texts=None,
                large_chunk_id=None,
                chunk_id=i,
                blurb=blurb,
                content=content,
                source_links=source_links,
                image_file_id=image_file_id,
                section_continuation=False,
            )
        )
    yield result  # Test runs here.


@pytest.fixture(scope="function")
def index_batch_params() -> Generator[IndexBatchParams, None, None]:
    yield IndexBatchParams(
        doc_id_to_previous_chunk_cnt={"test_doc": 0},
        doc_id_to_new_chunk_cnt={"test_doc": 5},
        tenant_id=get_current_tenant_id(),
        large_chunks_enabled=False,
    )


class TestDocumentIndexOld:
    """Tests the old DocumentIndex interface."""

    def test_update_single_can_clear_user_projects_and_personas(
        self,
        document_indices: list[DocumentIndex],
        # This test case assumes all these chunks correspond to one document.
        chunks: list[DocMetadataAwareIndexChunk],
        index_batch_params: IndexBatchParams,
    ) -> None:
        """
        Tests that update_single can clear user_projects and personas.
        """
        for document_index in document_indices:
            # Precondition.
            # Ensure there is some non-empty value for user project and
            # personas.
            for chunk in chunks:
                chunk.user_project = [1]
                chunk.personas = [2]
            document_index.index(chunks, index_batch_params)

            # Ensure that we can get chunks as expected.
            doc_id = chunks[0].source_document.id
            chunk_count = len(chunks)
            tenant_id = get_current_tenant_id()
            chunk_request = VespaChunkRequest(document_id=doc_id)
            project_persona_filters = IndexFilters(
                access_control_list=None,
                tenant_id=tenant_id,
                project_id=1,
                persona_id=2,
            )
            inference_chunks = document_index.id_based_retrieval(
                chunk_requests=[chunk_request], filters=project_persona_filters
            )
            assert len(inference_chunks) == chunk_count
            # Sort by chunk id to easily test if we have all chunks.
            for i, inference_chunk in enumerate(
                sorted(inference_chunks, key=lambda x: x.chunk_id)
            ):
                assert inference_chunk.chunk_id == i
                assert inference_chunk.document_id == doc_id

            # Under test.
            # Explicitly set empty fields here.
            user_fields = VespaDocumentUserFields(user_projects=[], personas=[])
            document_index.update_single(
                doc_id=doc_id,
                chunk_count=chunk_count,
                tenant_id=tenant_id,
                fields=None,
                user_fields=user_fields,
            )

            # Postcondition.
            filters = IndexFilters(access_control_list=None, tenant_id=tenant_id)
            # We should expect to get back all expected chunks with no filters.
            inference_chunks = document_index.id_based_retrieval(
                chunk_requests=[chunk_request], filters=filters
            )
            assert len(inference_chunks) == chunk_count
            # Sort by chunk id to easily test if we have all chunks.
            for i, inference_chunk in enumerate(
                sorted(inference_chunks, key=lambda x: x.chunk_id)
            ):
                assert inference_chunk.chunk_id == i
                assert inference_chunk.document_id == doc_id
            # Now, we should expect to not get any chunks if we specify the user
            # project and personas filters.
            inference_chunks = document_index.id_based_retrieval(
                chunk_requests=[chunk_request], filters=project_persona_filters
            )
            assert len(inference_chunks) == 0
