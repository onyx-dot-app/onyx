"""External dependency tests for the old DocumentIndex interface.

These tests assume Vespa and OpenSearch are running.

TODO(ENG-3764)(andrei): Consolidate some of these test fixtures.
"""

import os
import time
import uuid
from collections.abc import Generator
from unittest.mock import patch

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
def opensearch_available() -> Generator[None, None, None]:
    """Verifies OpenSearch is running, fails the test if not."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    yield  # Test runs here.


@pytest.fixture(scope="module")
def test_index_name() -> Generator[str, None, None]:
    yield f"test_index_{uuid.uuid4().hex[:8]}"  # Test runs here.


@pytest.fixture(scope="module")
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
    client = get_vespa_http_client()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="module")
def vespa_document_index(
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
    backend_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    with patch("os.getcwd", return_value=backend_dir):
        vespa_index.ensure_indices_exist(
            primary_embedding_dim=128,
            primary_embedding_precision=EmbeddingPrecision.FLOAT,
            secondary_index_embedding_dim=None,
            secondary_index_embedding_precision=None,
        )
    # Verify Vespa is running, fails the test if not. Try 90 seconds for testing
    # in CI. We have to do this here because this endpoint only becomes live
    # once we create an index.
    if not wait_for_vespa_with_timeout(wait_limit=90):
        pytest.fail("Vespa is not available.")

    # Wait until the schema is actually ready for writes on content nodes. We
    # probe by attempting a PUT; 200 means the schema is live, 400 means not
    # yet. This is so scuffed but running the test is really flakey otherwise;
    # this is only temporary until we entirely move off of Vespa.
    probe_doc = {
        "fields": {
            "document_id": "__probe__",
            "chunk_id": 0,
            "blurb": "",
            "title": "",
            "skip_title": True,
            "content": "",
            "content_summary": "",
            "source_type": "file",
            "source_links": "null",
            "semantic_identifier": "",
            "section_continuation": False,
            "large_chunk_reference_ids": [],
            "metadata": "{}",
            "metadata_list": [],
            "metadata_suffix": "",
            "chunk_context": "",
            "doc_summary": "",
            "embeddings": {"full_chunk": [1.0] + [0.0] * 127},
            "access_control_list": {},
            "document_sets": {},
            "image_file_name": None,
            "user_project": [],
            "personas": [],
            "boost": 0.0,
            "aggregated_chunk_boost_factor": 0.0,
            "primary_owners": [],
            "secondary_owners": [],
        }
    }
    schema_ready = False
    probe_url = (
        f"http://localhost:8081/document/v1/default/{test_index_name}/docid/__probe__"
    )
    for _ in range(60):
        resp = httpx_client.post(probe_url, json=probe_doc)
        if resp.status_code == 200:
            schema_ready = True
            # Clean up the probe document.
            httpx_client.delete(probe_url)
            break
        time.sleep(1)
    if not schema_ready:
        pytest.fail(f"Vespa schema '{test_index_name}' did not become ready in time.")

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
        secondary_embedding_dim=None,
        secondary_embedding_precision=None,
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
    yield [opensearch_document_index, vespa_document_index]  # Test runs here.


@pytest.fixture(scope="function")
def chunks(
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[DocMetadataAwareIndexChunk], None, None]:
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
    blurb = "blurb"
    content = "content"
    title_prefix = ""
    doc_summary = ""
    chunk_context = ""
    title_embedding = [1.0] + [0] * 127
    # Full 0 vectors are not supported for cos similarity.
    embeddings = ChunkEmbedding(
        full_embedding=[1.0] + [0] * 127, mini_chunk_embeddings=[]
    )
    source_document = Document(
        id=doc_id,
        semantic_identifier="semantic identifier",
        source=DocumentSource.FILE,
        sections=[],
        metadata={},
        title="title",
    )
    metadata_suffix_keyword = ""
    image_file_id = None
    source_links: dict[int, str] = {0: ""}
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
def index_batch_params(
    tenant_context: None,  # noqa: ARG001
) -> Generator[IndexBatchParams, None, None]:
    # WARNING: doc_id_to_previous_chunk_cnt={"test_doc": 0} is hardcoded to 0,
    # which is only correct on the very first index call. The document_indices
    # fixture is scope="module", meaning the same OpenSearch and Vespa backends
    # persist across all test functions in this module. When a second test
    # function uses this fixture and calls document_index.index(...), the
    # backend already has 5 chunks for "test_doc" from the previous test run,
    # but the batch params still claim 0 prior chunks exist. This can lead to
    # orphaned/duplicate chunks that make subsequent assertions incorrect.
    # TODO: Whenever adding a second test, either change this or cleanup the
    # index between test cases.
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
        tenant_context: None,  # noqa: ARG002
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

            # Ensure that we can get chunks as expected with filters.
            doc_id = chunks[0].source_document.id
            chunk_count = len(chunks)
            tenant_id = get_current_tenant_id()
            # We need to specify the chunk index range and specify
            # batch_retrieval=True below to trigger the codepath for Vespa's
            # search API, which uses the expected additive filtering for
            # project_id and persona_id. Otherwise we would use the codepath for
            # the visit API, which does not have this kind of filtering
            # implemented.
            chunk_request = VespaChunkRequest(
                document_id=doc_id, min_chunk_ind=0, max_chunk_ind=chunk_count - 1
            )
            project_persona_filters = IndexFilters(
                access_control_list=None,
                tenant_id=tenant_id,
                project_id=1,
                persona_id=2,
                # We need this even though none of the chunks belong to a
                # document set because project_id and persona_id are only
                # additive filters in the event the agent has knowledge scope;
                # if the agent does not, it is implied that it can see
                # everything it is allowed to.
                document_set=["1"],
            )
            # Not best practice here but the API for refreshing the index to
            # ensure that the latest data is present is not exposed in this
            # class and is not the same for Vespa and OpenSearch, so we just
            # tolerate a sleep for now. As a consequence the number of tests in
            # this suite should be small. We only need to tolerate this for as
            # long as we continue to use Vespa, we can consider exposing
            # something for OpenSearch later.
            time.sleep(1)
            inference_chunks = document_index.id_based_retrieval(
                chunk_requests=[chunk_request],
                filters=project_persona_filters,
                batch_retrieval=True,
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
            # Again, not best practice here.
            time.sleep(1)
            inference_chunks = document_index.id_based_retrieval(
                chunk_requests=[chunk_request], filters=filters, batch_retrieval=True
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
                chunk_requests=[chunk_request],
                filters=project_persona_filters,
                batch_retrieval=True,
            )
            assert len(inference_chunks) == 0
