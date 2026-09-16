import time
import uuid

from onyx.configs.constants import PUBLIC_DOC_PAT, DocumentSource
from onyx.context.search.models import IndexFilters, InferenceChunk
from onyx.document_index.interfaces_new import (
    DocumentSectionRequest,
    MetadataUpdateRequest,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    make_chunk,
    make_indexing_metadata,
)


def _retrieve_by_source(
    document_index: OpenSearchDocumentIndex,
    document_id: str,
    source: DocumentSource,
) -> list[InferenceChunk]:
    return document_index.id_based_retrieval(
        chunk_requests=[DocumentSectionRequest(document_id=document_id)],
        filters=IndexFilters(
            access_control_list=[PUBLIC_DOC_PAT],
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            source_type=[source],
        ),
    )


def _wait_for_source_count(
    document_index: OpenSearchDocumentIndex,
    document_id: str,
    source: DocumentSource,
    expected_count: int,
) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if (
            len(_retrieve_by_source(document_index, document_id, source))
            == expected_count
        ):
            return
        time.sleep(0.25)
    raise AssertionError(
        f"Timed out waiting for {source.value} to return {expected_count} chunks"
    )


def test_multi_source_index_filter_and_metadata_update(
    opensearch_index: OpenSearchDocumentIndex,
    tenant_context: None,  # noqa: ARG001
) -> None:
    document_id = f"multi-source-{uuid.uuid4().hex}"
    chunk = make_chunk(document_id).model_copy(
        update={
            "source_types": (
                DocumentSource.WEB,
                DocumentSource.GOOGLE_DRIVE,
            )
        }
    )
    opensearch_index.index(
        chunks=[chunk],
        indexing_metadata=make_indexing_metadata(
            [document_id],
            old_counts=[0],
            new_counts=[1],
        ),
    )

    _wait_for_source_count(
        opensearch_index, document_id, DocumentSource.WEB, expected_count=1
    )
    _wait_for_source_count(
        opensearch_index,
        document_id,
        DocumentSource.GOOGLE_DRIVE,
        expected_count=1,
    )
    retrieved = _retrieve_by_source(opensearch_index, document_id, DocumentSource.WEB)
    assert retrieved[0].source_type is DocumentSource.GOOGLE_DRIVE
    assert retrieved[0].source_types == (
        DocumentSource.GOOGLE_DRIVE,
        DocumentSource.WEB,
    )
    _wait_for_source_count(
        opensearch_index, document_id, DocumentSource.FILE, expected_count=0
    )

    opensearch_index.update(
        [
            MetadataUpdateRequest(
                document_ids=[document_id],
                doc_id_to_chunk_cnt={document_id: 1},
                source_types=(DocumentSource.SHAREPOINT,),
            )
        ]
    )

    _wait_for_source_count(
        opensearch_index, document_id, DocumentSource.SHAREPOINT, expected_count=1
    )
    _wait_for_source_count(
        opensearch_index, document_id, DocumentSource.WEB, expected_count=0
    )
