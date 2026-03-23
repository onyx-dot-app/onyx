"""External dependency tests for the old DocumentIndex interface.

These tests assume Vespa and OpenSearch are running.
"""

import time
from collections.abc import Generator

import pytest

from onyx.context.search.models import IndexFilters
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import IndexBatchParams
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchOldDocumentIndex,
)
from onyx.document_index.vespa.index import VespaIndex
from onyx.indexing.models import DocMetadataAwareIndexChunk
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.document_index.conftest import make_chunk


@pytest.fixture(scope="module")
def document_indices(
    vespa_index: VespaIndex,
    opensearch_old_index: OpenSearchOldDocumentIndex,
) -> Generator[list[DocumentIndex], None, None]:
    # Ideally these are parametrized; doing so with pytest fixtures is tricky.
    yield [opensearch_old_index, vespa_index]


@pytest.fixture(scope="function")
def chunks(
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[DocMetadataAwareIndexChunk], None, None]:
    yield [make_chunk("test_doc", chunk_id=i) for i in range(5)]


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
