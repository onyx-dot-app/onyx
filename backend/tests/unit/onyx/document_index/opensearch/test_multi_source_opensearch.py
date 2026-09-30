import json
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import IndexFilters, SearchDoc
from onyx.document_index.interfaces_new import MetadataUpdateRequest, TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
    convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned,
)
from onyx.document_index.opensearch.schema import DocumentChunkWithoutVectors
from onyx.document_index.opensearch.search import DocumentQuery


def _make_chunk(source_type: str | list[str]) -> DocumentChunkWithoutVectors:
    return DocumentChunkWithoutVectors.model_validate(
        {
            "document_id": "doc-1",
            "chunk_index": 0,
            "content": "hello",
            "source_type": source_type,
            "public": True,
            "access_control_list": [],
            "global_boost": 0,
            "semantic_identifier": "doc-1",
            "blurb": "hello",
            "doc_summary": "",
            "chunk_context": "",
        }
    )


def test_source_type_scalar_round_trips_as_scalar() -> None:
    chunk = _make_chunk(DocumentSource.WEB.value)

    assert chunk.source_type == DocumentSource.WEB.value
    assert chunk.source_types == (DocumentSource.WEB.value,)
    assert chunk.model_dump()["source_type"] == DocumentSource.WEB.value


def test_source_type_array_is_normalized_and_kept_as_array() -> None:
    chunk = _make_chunk(
        [
            DocumentSource.WEB.value,
            DocumentSource.GOOGLE_DRIVE.value,
            DocumentSource.WEB.value,
        ]
    )

    assert chunk.source_type == DocumentSource.GOOGLE_DRIVE.value
    assert chunk.source_types == (
        DocumentSource.GOOGLE_DRIVE.value,
        DocumentSource.WEB.value,
    )
    assert chunk.model_dump()["source_type"] == [
        DocumentSource.GOOGLE_DRIVE.value,
        DocumentSource.WEB.value,
    ]


def test_source_type_rejects_empty_array() -> None:
    with pytest.raises(ValueError, match="at least one source"):
        _make_chunk([])


def test_retrieval_uses_deterministic_display_source() -> None:
    result = convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned(
        _make_chunk([DocumentSource.WEB.value, DocumentSource.GOOGLE_DRIVE.value]),
        score=None,
        highlights={},
    )

    assert result.source_type is DocumentSource.GOOGLE_DRIVE
    assert result.source_types == (
        DocumentSource.GOOGLE_DRIVE,
        DocumentSource.WEB,
    )

    search_doc = SearchDoc.from_chunks_or_sections([result.to_inference_chunk()])[0]
    assert search_doc.source_type is DocumentSource.GOOGLE_DRIVE
    assert json.loads(search_doc.model_dump_json())["source_types"] == [
        DocumentSource.GOOGLE_DRIVE.value,
        DocumentSource.WEB.value,
    ]


def test_source_filter_uses_terms_query() -> None:
    query = DocumentQuery.get_from_document_id_query(
        document_id="doc-1",
        tenant_state=TenantState(tenant_id="public", multitenant=False),
        index_filters=IndexFilters(
            access_control_list=None,
            source_type=[DocumentSource.WEB, DocumentSource.GOOGLE_DRIVE],
        ),
        include_hidden=True,
        max_chunk_size=512,
        min_chunk_index=None,
        max_chunk_index=None,
    )

    filters = query["query"]["bool"]["filter"]
    assert {
        "terms": {
            "source_type": [
                DocumentSource.WEB.value,
                DocumentSource.GOOGLE_DRIVE.value,
            ]
        }
    } in filters


def test_metadata_update_writes_multiple_source_types() -> None:
    index = OpenSearchDocumentIndex.__new__(OpenSearchDocumentIndex)
    index._index_name = "test-index"
    index._tenant_state = TenantState(tenant_id="public", multitenant=False)
    index._client = MagicMock()

    index.update(
        [
            MetadataUpdateRequest(
                document_ids=["doc-1"],
                doc_id_to_chunk_cnt={"doc-1": 1},
                source_types=(DocumentSource.WEB, DocumentSource.GOOGLE_DRIVE),
            )
        ]
    )

    assert index._client.bulk_update_documents.call_args.kwargs[
        "properties_to_update"
    ] == {
        "source_type": [
            DocumentSource.GOOGLE_DRIVE.value,
            DocumentSource.WEB.value,
        ]
    }
