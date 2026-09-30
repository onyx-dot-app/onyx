"""Tests for how KG deep extraction reads a document's chunks from the document
index."""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

# Imported first: onyx.db.entities and onyx.db.document import each other, and
# the cycle only resolves when onyx.db.document loads first.
import onyx.db.document  # noqa: F401
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.kg.models import KGChunkFormat
from onyx.kg.utils.extraction_utils import _get_document_chunk_batches

_EXTRACTION_UTILS = "onyx.kg.utils.extraction_utils"


def _chunk(chunk_id: int, title: str | None = "Title") -> InferenceChunk:
    return InferenceChunk(
        document_id="doc-1",
        chunk_id=chunk_id,
        content=f"content {chunk_id}",
        source_type=DocumentSource.GONG,
        semantic_identifier="doc-1",
        title=title,
        boost=0,
        score=None,
        hidden=False,
        metadata={"account": "acme"},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
        image_file_id=None,
        source_links={},
        section_continuation=False,
        blurb="",
        primary_owners=["owner@acme.com"],
        secondary_owners=None,
    )


def _batches(
    chunks: list[InferenceChunk], batch_size: int
) -> tuple[list[list[KGChunkFormat]], MagicMock]:
    document_index = MagicMock()
    document_index.id_based_retrieval.return_value = chunks
    with (
        patch(
            f"{_EXTRACTION_UTILS}.get_session_with_current_tenant",
            return_value=nullcontext(MagicMock()),
        ),
        patch(f"{_EXTRACTION_UTILS}.get_current_search_settings"),
        patch(
            f"{_EXTRACTION_UTILS}.get_default_document_index",
            return_value=document_index,
        ),
    ):
        batches = list(
            _get_document_chunk_batches("doc-1", "tenant_a", batch_size=batch_size)
        )
    return batches, document_index


def test_reads_the_whole_document_scoped_to_the_tenant() -> None:
    _, document_index = _batches([_chunk(0)], batch_size=8)

    kwargs = document_index.id_based_retrieval.call_args.kwargs
    (request,) = kwargs["chunk_requests"]
    assert request.document_id == "doc-1"
    assert request.min_chunk_ind is None
    assert request.max_chunk_ind is None
    assert kwargs["filters"].tenant_id == "tenant_a"
    assert kwargs["filters"].access_control_list is None
    assert kwargs["batch_retrieval"] is True


def test_maps_inference_chunks_to_kg_chunks() -> None:
    batches, _ = _batches([_chunk(0), _chunk(1, title=None)], batch_size=8)

    (batch,) = batches
    assert batch[0] == KGChunkFormat(
        document_id="doc-1",
        chunk_id=0,
        title="Title",
        content="content 0",
        primary_owners=["owner@acme.com"],
        secondary_owners=[],
        source_type=DocumentSource.GONG.value,
        metadata={"account": "acme"},
    )
    assert batch[1].title == ""


def test_yields_fixed_size_batches() -> None:
    batches, _ = _batches([_chunk(i) for i in range(5)], batch_size=2)

    assert [[chunk.chunk_id for chunk in batch] for batch in batches] == [
        [0, 1],
        [2, 3],
        [4],
    ]


def test_document_without_chunks_yields_nothing() -> None:
    batches, _ = _batches([], batch_size=2)

    assert batches == []
