"""Tests for the reindex-port re-embedding (port_reembed).

These cover the pure re-embed logic: strategy selection, rebuilding the semantic
metadata tail, the embed-input recovery (the crux — stored content carries the
keyword tail, but the embedded text used the semantic tail), and the minimal
DocAwareChunk reconstruction that feeds that input to the embedder.

The embedder is a pure function of its input text, so proving the input differs
from the raw stored content (here) is equivalent to proving the resulting vector
differs; the real-embedder path is exercised once the port task is wired.
"""

from typing import cast
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import convert_metadata_dict_to_list_of_strings
from onyx.connectors.models import convert_metadata_list_of_strings_to_dict
from onyx.db.models import SearchSettings
from onyx.document_index.chunk_content_enrichment import (
    generate_enriched_content_for_chunk_embedding,
)
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.schema import DocumentChunkWithoutVectors
from onyx.indexing.chunker import _get_metadata_suffix_for_document_index
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import IndexChunk
from onyx.indexing.port_reembed import _stored_chunk_to_doc_aware
from onyx.indexing.port_reembed import re_embed_chunks
from onyx.indexing.port_reembed import rebuild_semantic_tail
from onyx.indexing.port_reembed import recover_embedding_input
from onyx.indexing.port_reembed import ReembedStrategy
from onyx.indexing.port_reembed import select_reembed_strategy
from onyx.utils.pydantic_util import shallow_model_dump
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def _stored_chunk(
    content: str,
    *,
    metadata_suffix: str | None = None,
    metadata_list: list[str] | None = None,
    title: str | None = "Doc Title",
    chunk_index: int = 0,
) -> DocumentChunkWithoutVectors:
    return DocumentChunkWithoutVectors(
        document_id="doc-1",
        chunk_index=chunk_index,
        content=content,
        source_type=DocumentSource.FILE.value,
        metadata_list=metadata_list,
        metadata_suffix=metadata_suffix,
        title=title,
        public=True,
        access_control_list=[],
        global_boost=0,
        semantic_identifier="Doc semantic id",
        blurb="blurb",
        doc_summary="",
        chunk_context="",
        tenant_id=TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False),
    )


def _ss(
    enable_contextual_rag: bool = False,
    contextual_rag_model_configuration_id: int | None = None,
) -> SearchSettings:
    return SearchSettings(
        enable_contextual_rag=enable_contextual_rag,
        contextual_rag_model_configuration_id=contextual_rag_model_configuration_id,
    )


def test_select_reembed_strategy() -> None:
    base = _ss()
    assert select_reembed_strategy(base, _ss()) is ReembedStrategy.MODEL_ONLY
    assert (
        select_reembed_strategy(base, _ss(enable_contextual_rag=True))
        is ReembedStrategy.AUGMENTATION
    )
    assert (
        select_reembed_strategy(
            _ss(enable_contextual_rag=True, contextual_rag_model_configuration_id=1),
            _ss(enable_contextual_rag=True, contextual_rag_model_configuration_id=2),
        )
        is ReembedStrategy.AUGMENTATION
    )


def test_rebuild_semantic_tail() -> None:
    metadata_list = convert_metadata_dict_to_list_of_strings(
        {"author": "Jane Doe", "team": "finance"}
    )
    expected, _ = _get_metadata_suffix_for_document_index(
        convert_metadata_list_of_strings_to_dict(metadata_list), include_separator=True
    )
    assert rebuild_semantic_tail(
        _stored_chunk("body", metadata_list=metadata_list)
    ) == (expected)
    assert rebuild_semantic_tail(_stored_chunk("body", metadata_list=None)) == ""


def test_recover_embedding_input_swaps_semantic_tail() -> None:
    metadata_list = convert_metadata_dict_to_list_of_strings(
        {"author": "Jane Doe", "team": "finance"}
    )
    semantic, keyword = _get_metadata_suffix_for_document_index(
        convert_metadata_list_of_strings_to_dict(metadata_list), include_separator=True
    )
    assert semantic != keyword  # precondition: the two tails genuinely differ

    # stored content carries the KEYWORD tail
    chunk = _stored_chunk(
        "the body text" + keyword,
        metadata_suffix=keyword,
        metadata_list=metadata_list,
    )
    embed_input = recover_embedding_input(chunk)
    assert embed_input == "the body text" + semantic
    # the crux: the embedding input is NOT the stored (keyword-tailed) content
    assert embed_input != chunk.content

    # no suffix (chunker dropped it) -> content passes through unchanged
    plain = _stored_chunk("just body", metadata_suffix=None, metadata_list=None)
    assert recover_embedding_input(plain) == "just body"

    # no keyword tail was glued in (empty metadata_suffix) -> don't add a tail,
    # even if metadata_list is present
    no_tail = _stored_chunk(
        "just body", metadata_suffix=None, metadata_list=metadata_list
    )
    assert recover_embedding_input(no_tail) == "just body"

    # content doesn't actually end with the stored suffix -> embed as-is, never
    # double-append a tail
    mismatched = _stored_chunk(
        "body without the tail",
        metadata_suffix="\n\r\nMetadata: x",
        metadata_list=metadata_list,
    )
    assert recover_embedding_input(mismatched) == "body without the tail"


def test_to_doc_aware_chunk_feeds_embed_input() -> None:
    """The reconstructed DocAwareChunk makes the embedder embed exactly the
    recovered embedding input (not the stored content), and carries the title
    for the title vector with a semantic_identifier fallback."""
    chunk = _stored_chunk("body", title="My Title")
    embed_input = recover_embedding_input(chunk)
    doc_aware = _stored_chunk_to_doc_aware(chunk, embed_input)

    assert generate_enriched_content_for_chunk_embedding(doc_aware) == embed_input
    assert doc_aware.source_document.id == chunk.document_id
    assert doc_aware.source_document.get_title_for_document_index() == "My Title"
    assert doc_aware.chunk_id == chunk.chunk_index

    # stored title None == the source title was empty == no title embedding;
    # it must NOT fall back to semantic_identifier.
    no_title = _stored_chunk("body", title=None)
    da = _stored_chunk_to_doc_aware(no_title, "body")
    assert da.source_document.get_title_for_document_index() is None


def test_re_embed_augmentation_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        re_embed_chunks(
            [_stored_chunk("body")], ReembedStrategy.AUGMENTATION, MagicMock()
        )


def test_re_embed_empty_returns_empty() -> None:
    assert re_embed_chunks([], ReembedStrategy.MODEL_ONLY, MagicMock()) == []


def test_re_embed_preserves_all_fields_swaps_only_vectors() -> None:
    """re_embed_chunks returns the whole stored chunk as a DocumentChunk with only
    content_vector/title_vector recomputed — every other field is copied through
    (so the FUTURE write is a faithful copy with new embeddings)."""
    metadata_list = convert_metadata_dict_to_list_of_strings({"author": "Jane"})
    stored = _stored_chunk(
        "body text", title="My Title", metadata_list=metadata_list, chunk_index=3
    )
    fake_cv, fake_tv = [0.5, 0.5], [0.9, 0.9]

    class _FakeEmbedder:
        def embed_chunks(self, chunks: list[DocAwareChunk]) -> list[IndexChunk]:
            return [
                IndexChunk.model_construct(
                    **shallow_model_dump(chunk),
                    embeddings=ChunkEmbedding(
                        full_embedding=fake_cv, mini_chunk_embeddings=[]
                    ),
                    title_embedding=fake_tv,
                )
                for chunk in chunks
            ]

    [result] = re_embed_chunks(
        [stored], ReembedStrategy.MODEL_ONLY, cast(IndexingEmbedder, _FakeEmbedder())
    )

    # only the two vectors are new
    assert result.content_vector == fake_cv
    assert result.title_vector == fake_tv
    # every other field is the stored chunk's, unchanged
    for field in DocumentChunkWithoutVectors.model_fields:
        assert getattr(result, field) == getattr(stored, field), field
