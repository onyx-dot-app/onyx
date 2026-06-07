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
from onyx.configs.constants import RETURN_SEPARATOR
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
from onyx.indexing.port_reembed import _bare_contents
from onyx.indexing.port_reembed import _reconstruct_source_document
from onyx.indexing.port_reembed import _stored_chunk_to_doc_aware
from onyx.indexing.port_reembed import AugmentationReembedContext
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
    document_id: str = "doc-1",
    metadata_suffix: str | None = None,
    metadata_list: list[str] | None = None,
    title: str | None = "Doc Title",
    chunk_index: int = 0,
    doc_summary: str = "",
    chunk_context: str = "",
) -> DocumentChunkWithoutVectors:
    return DocumentChunkWithoutVectors(
        document_id=document_id,
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
        doc_summary=doc_summary,
        chunk_context=chunk_context,
        tenant_id=TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False),
    )


def _vec(text: str) -> list[float]:
    """A deterministic, content-dependent fake embedding: different input text
    yields a different vector, so a test can prove the embedding input changed."""
    return [float(len(text)), float(sum(ord(ch) for ch in text) % 1000)]


class _ContentVecEmbedder:
    """Fake embedder whose vectors depend on the actual embedding input, so tests
    can assert that stripping/re-enriching changed what got embedded."""

    def embed_chunks(self, chunks: list[DocAwareChunk]) -> list[IndexChunk]:
        out = []
        for chunk in chunks:
            text = generate_enriched_content_for_chunk_embedding(chunk)
            title = chunk.source_document.get_title_for_document_index()
            out.append(
                IndexChunk.model_construct(
                    **shallow_model_dump(chunk),
                    embeddings=ChunkEmbedding(
                        full_embedding=_vec(text), mini_chunk_embeddings=[]
                    ),
                    title_embedding=_vec(title) if title else None,
                )
            )
        return out


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
    # RAG on in both, model changed -> AUGMENTATION (re-enrich under new LLM)
    assert (
        select_reembed_strategy(
            _ss(enable_contextual_rag=True, contextual_rag_model_configuration_id=1),
            _ss(enable_contextual_rag=True, contextual_rag_model_configuration_id=2),
        )
        is ReembedStrategy.AUGMENTATION
    )
    # RAG on in both, same model -> only the embedder could differ -> MODEL_ONLY
    assert (
        select_reembed_strategy(
            _ss(enable_contextual_rag=True, contextual_rag_model_configuration_id=1),
            _ss(enable_contextual_rag=True, contextual_rag_model_configuration_id=1),
        )
        is ReembedStrategy.MODEL_ONLY
    )
    # RAG OFF in both: a stale model-id difference is irrelevant (no enrichment in
    # either index) -> MODEL_ONLY, not a spurious AUGMENTATION.
    assert (
        select_reembed_strategy(
            _ss(enable_contextual_rag=False, contextual_rag_model_configuration_id=1),
            _ss(enable_contextual_rag=False, contextual_rag_model_configuration_id=2),
        )
        is ReembedStrategy.MODEL_ONLY
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


def test_augmentation_requires_context() -> None:
    with pytest.raises(ValueError):
        re_embed_chunks(
            [_stored_chunk("body")], ReembedStrategy.AUGMENTATION, MagicMock()
        )


def _augmented_stored_chunk() -> tuple[DocumentChunkWithoutVectors, str]:
    """A stored chunk whose content carries title prefix + doc summary +
    chunk context + keyword metadata tail. Returns (chunk, bare_text)."""
    metadata_list = convert_metadata_dict_to_list_of_strings({"author": "Jane"})
    _semantic, keyword = _get_metadata_suffix_for_document_index(
        convert_metadata_list_of_strings_to_dict(metadata_list), include_separator=True
    )
    title = "My Title"
    doc_summary = "DOCSUM. "
    chunk_context = " CTX."
    bare = "the body text"
    content = f"{title}{RETURN_SEPARATOR}{doc_summary}{bare}{chunk_context}{keyword}"
    chunk = _stored_chunk(
        content,
        metadata_suffix=keyword,
        metadata_list=metadata_list,
        title=title,
        doc_summary=doc_summary,
        chunk_context=chunk_context,
    )
    return chunk, bare


def test_strip_stored_chunk_to_bare_content() -> None:
    """cleanup strips title prefix, metadata tail, doc summary and chunk context,
    leaving only the original chunk body."""
    chunk, bare = _augmented_stored_chunk()
    assert _bare_contents([chunk]) == [bare]


def test_reconstruct_document_text_from_chunks() -> None:
    """Doc text is reconstructed by joining the bare chunks in chunk-index order."""
    c0 = _stored_chunk("first part", chunk_index=0, title="T")
    c1 = _stored_chunk("second part", chunk_index=1, title="T")
    # pass out of order to prove the helper sorts by chunk_index
    doc = _reconstruct_source_document([c1, c0], ["second part", "first part"])
    assert doc.id == "doc-1"
    assert doc.get_text_content() == "first part second part"
    assert doc.get_title_for_document_index() == "T"


def test_augmentation_strip_off_reembeds_bare() -> None:
    """RAG on -> off: the FUTURE chunk drops doc_summary/chunk_context from both
    the stored content and the embedding input, and clears those fields. The
    embedding input (hence the vector) differs from the MODEL_ONLY (Tier-1)
    input, which keeps the augmentation glued in."""
    chunk, bare = _augmented_stored_chunk()
    keyword = chunk.metadata_suffix or ""
    semantic = rebuild_semantic_tail(chunk)

    ctx = AugmentationReembedContext(future_enable_contextual_rag=False)
    [result] = re_embed_chunks(
        [chunk],
        ReembedStrategy.AUGMENTATION,
        cast(IndexingEmbedder, _ContentVecEmbedder()),
        augmentation_ctx=ctx,
    )

    # stored (BM25) content rebuilt without the contextual-RAG augmentation
    assert result.content == f"My Title{RETURN_SEPARATOR}{bare}{keyword}"
    assert result.doc_summary == ""
    assert result.chunk_context == ""

    # the embedded text was title_prefix + bare + semantic tail (no summary/context)
    strip_embed_input = f"My Title{RETURN_SEPARATOR}{bare}{semantic}"
    assert result.content_vector == _vec(strip_embed_input)
    # ... and that genuinely differs from the Tier-1 (MODEL_ONLY) embed input,
    # which keeps the doc summary + chunk context.
    tier1_embed_input = recover_embedding_input(chunk)
    assert result.content_vector != _vec(tier1_embed_input)
    # non-augmentation fields are preserved
    assert result.metadata_suffix == keyword
    assert result.title == chunk.title


def test_augmentation_enrich_on_generates_and_reembeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG off -> on: the bare chunk is re-enriched under the FUTURE LLM (stubbed
    here), and the new doc_summary/chunk_context land in the stored content, the
    stored fields, and the embedding input. The vector differs from the strip
    path because the embedded text now carries the regenerated summaries."""

    # Stub the contextual-RAG enrichment (the LLM call is the indexing pipeline's
    # own tested surface; here we prove the port's strip -> enrich -> re-glue ->
    # embed wiring). The lazy import inside _augmentation_reembed resolves this.
    def _fake_enrich(
        chunks: list[DocAwareChunk], **_kwargs: object
    ) -> list[DocAwareChunk]:
        for c in chunks:
            c.doc_summary = "SUMMARY. "
            c.chunk_context = " CONTEXT."
        return chunks

    monkeypatch.setattr(
        "onyx.indexing.indexing_pipeline.add_contextual_summaries", _fake_enrich
    )

    bare = "the body text"
    metadata_list = convert_metadata_dict_to_list_of_strings({"author": "Jane"})
    _semantic, keyword = _get_metadata_suffix_for_document_index(
        convert_metadata_list_of_strings_to_dict(metadata_list), include_separator=True
    )
    # PRESENT had RAG off: no doc_summary/chunk_context glued in.
    chunk = _stored_chunk(
        f"My Title{RETURN_SEPARATOR}{bare}{keyword}",
        metadata_suffix=keyword,
        metadata_list=metadata_list,
        title="My Title",
    )
    semantic = rebuild_semantic_tail(chunk)

    ctx = AugmentationReembedContext(
        future_enable_contextual_rag=True,
        llm=MagicMock(),
        tokenizer=MagicMock(),
        chunk_token_limit=128,
        contextual_rag_reserved_tokens=512,
    )
    [result] = re_embed_chunks(
        [chunk],
        ReembedStrategy.AUGMENTATION,
        cast(IndexingEmbedder, _ContentVecEmbedder()),
        augmentation_ctx=ctx,
    )

    # the regenerated summaries are stored both as fields and glued into content
    assert result.doc_summary == "SUMMARY. "
    assert result.chunk_context == " CONTEXT."
    assert (
        result.content == f"My Title{RETURN_SEPARATOR}SUMMARY. {bare} CONTEXT.{keyword}"
    )

    # the embedded text carries the new summaries; vector differs from strip-only
    enrich_embed_input = f"My Title{RETURN_SEPARATOR}SUMMARY. {bare} CONTEXT.{semantic}"
    assert result.content_vector == _vec(enrich_embed_input)
    strip_embed_input = f"My Title{RETURN_SEPARATOR}{bare}{semantic}"
    assert result.content_vector != _vec(strip_embed_input)


def test_augmentation_mixed_docs_enrich_per_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One AUGMENTATION call may span documents (the port batches them): each
    chunk must be enriched against its OWN document's reconstructed text, and
    output order must match input order."""

    def _fake_enrich(
        chunks: list[DocAwareChunk], **_kwargs: object
    ) -> list[DocAwareChunk]:
        for c in chunks:
            doc = c.source_document
            c.doc_summary = f"[{doc.id}:{doc.get_text_content()}] "
        return chunks

    monkeypatch.setattr(
        "onyx.indexing.indexing_pipeline.add_contextual_summaries", _fake_enrich
    )

    a0 = _stored_chunk("a-first", document_id="doc-a", chunk_index=0, title=None)
    a1 = _stored_chunk("a-second", document_id="doc-a", chunk_index=1, title=None)
    b0 = _stored_chunk("b-only", document_id="doc-b", chunk_index=0, title=None)

    ctx = AugmentationReembedContext(
        future_enable_contextual_rag=True,
        llm=MagicMock(),
        tokenizer=MagicMock(),
        chunk_token_limit=128,
        contextual_rag_reserved_tokens=512,
    )
    # interleaved on purpose: the per-doc grouping must not rely on input order
    results = re_embed_chunks(
        [a0, b0, a1],
        ReembedStrategy.AUGMENTATION,
        cast(IndexingEmbedder, _ContentVecEmbedder()),
        augmentation_ctx=ctx,
    )

    assert [(r.document_id, r.chunk_index) for r in results] == [
        ("doc-a", 0),
        ("doc-b", 0),
        ("doc-a", 1),
    ]
    # each chunk saw its own document's reconstructed text, not the whole batch's
    assert results[0].doc_summary == "[doc-a:a-first a-second] "
    assert results[1].doc_summary == "[doc-b:b-only] "
    assert results[2].doc_summary == "[doc-a:a-first a-second] "


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
