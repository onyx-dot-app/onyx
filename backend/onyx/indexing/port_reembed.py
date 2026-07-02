"""Re-embed stored PRESENT chunks under FUTURE search settings without
re-fetching the source document (solution-design.md §5.1.1).

Two strategies, chosen by comparing PRESENT vs FUTURE settings:

- MODEL_ONLY (model / prefix / normalize / dimension changed, enrichment did
  not): the embedding input is unchanged from indexing, so we re-embed the same
  enriched text — the title prefix, doc summary and chunk context are kept,
  because the stored vector encoded all of them and the new model must encode
  the same text. The only catch is that the stored `content` ends with the
  *keyword* metadata tail while indexing embedded the *semantic* tail, so we
  swap just that tail back.
- AUGMENTATION (contextual-RAG toggle or model changed): the enriched text
  itself changes, so we strip the stored augmentation back to the bare chunk
  text, re-glue under FUTURE settings, then re-embed. Two sub-cases keyed on the
  FUTURE `enable_contextual_rag`:
    * FUTURE RAG off — strip the doc summary / chunk context / title / metadata
      and re-embed the bare chunk (no LLM).
    * FUTURE RAG on — additionally regenerate the doc summary + chunk context
      under the FUTURE contextual LLM. The full document text the LLM needs is
      *reconstructed by concatenating the document's own (bare) chunks* in chunk
      order; the port never re-fetches the source. This duplicates chunk-overlap
      regions and loses the original section boundaries, so the reconstructed
      text is not byte-identical to the source — an accepted imprecision (the LLM
      truncates to a token budget anyway, and re-fetching the source is the
      fragility this feature exists to remove).

Only regular chunks are handled (the port reads `max_chunk_size ==
DEFAULT_MAX_CHUNK_SIZE`); writes are idempotent (create-only: re-creating an
existing chunk is a benign 409) so we re-embed unconditionally rather than
diffing content hashes.
"""

from __future__ import annotations

import enum
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import RETURN_SEPARATOR
from onyx.connectors.models import convert_metadata_list_of_strings_to_dict
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.db.models import SearchSettings
from onyx.document_index.chunk_content_enrichment import cleanup_content_for_chunks
from onyx.document_index.chunk_content_enrichment import (
    generate_enriched_content_for_chunk_text,
)
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import DocumentChunkWithoutVectors
from onyx.indexing.chunker import get_metadata_suffix_for_document_index
from onyx.indexing.chunker import MAX_METADATA_PERCENTAGE
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import IndexChunk

if TYPE_CHECKING:
    from onyx.llm.interfaces import LLM
    from onyx.natural_language_processing.utils import BaseTokenizer


class ReembedStrategy(enum.Enum):
    # Only the embedder changed; re-embed the same enriched text (tail swapped).
    MODEL_ONLY = "model_only"
    # The contextual-RAG enrichment changed; rebuild the text, then re-embed.
    AUGMENTATION = "augmentation"


@dataclass
class AugmentationReembedContext:
    """Everything the AUGMENTATION path needs beyond the embedder. Built once by
    the port copier (which holds a DB session); `re_embed_chunks` itself stays
    DB-free. `future_embedding_tokenizer` (the FUTURE embedding model's) is always
    needed to reproduce the chunker's metadata-tail skip; the LLM + `tokenizer` (the
    contextual LLM's) + budgets are required only when regenerating (FUTURE RAG on)."""

    future_enable_contextual_rag: bool
    future_embedding_tokenizer: "BaseTokenizer"
    llm: "LLM | None" = None
    tokenizer: "BaseTokenizer | None" = None
    chunk_token_limit: int = 0
    contextual_rag_reserved_tokens: int = 0


def select_reembed_strategy(
    present_ss: SearchSettings, future_ss: SearchSettings
) -> ReembedStrategy:
    """AUGMENTATION when the contextual-RAG *enrichment* differs (the embedded
    text changes), otherwise MODEL_ONLY. A change in
    `contextual_rag_model_configuration_id` only matters when contextual RAG is
    on in present or future — if it is off in both, no enrichment exists in
    either index, so a stale model-id difference must not force AUGMENTATION.
    Model/prefix/normalize/dimension and multipass changes only alter the vectors
    (or large/mini chunks the port doesn't read), so they fall through to
    MODEL_ONLY."""
    rag_relevant = present_ss.enable_contextual_rag or future_ss.enable_contextual_rag
    augmentation_changed = (
        present_ss.enable_contextual_rag != future_ss.enable_contextual_rag
        or (
            rag_relevant
            and present_ss.contextual_rag_model_configuration_id
            != future_ss.contextual_rag_model_configuration_id
        )
    )
    return (
        ReembedStrategy.AUGMENTATION
        if augmentation_changed
        else ReembedStrategy.MODEL_ONLY
    )


def rebuild_semantic_tail(chunk: DocumentChunkWithoutVectors) -> str:
    """Rebuild the *semantic* metadata suffix that was embedded, from the stored
    `metadata_list`. Empty when the chunk has no metadata."""
    if not chunk.metadata_list:
        return ""
    metadata = convert_metadata_list_of_strings_to_dict(chunk.metadata_list)
    semantic_suffix, _ = get_metadata_suffix_for_document_index(
        metadata, include_separator=True
    )
    return semantic_suffix


def _semantic_tail_was_embedded(
    semantic_tail: str, max_chunk_size: int, tokenizer: BaseTokenizer
) -> bool:
    """Whether an index embedded the semantic tail. The chunker drops it from the
    embedding when it exceeds MAX_METADATA_PERCENTAGE of the chunk budget, yet still
    stores the keyword tail on `content` — so any rebuild must reproduce the skip or it
    embeds metadata the vector never saw. Pass the tokenizer of the index whose behavior
    is being reproduced: PRESENT for MODEL_ONLY (what indexing embedded), FUTURE for
    AUGMENTATION (what a fresh FUTURE index would embed) — the two models can count the
    tail differently and flip the threshold. `max_chunk_size` is the chunk budget (equal
    for both: ported chunks are all DEFAULT_MAX_CHUNK_SIZE)."""
    if not semantic_tail:
        return False
    metadata_tokens = len(tokenizer.encode(semantic_tail))
    return metadata_tokens < max_chunk_size * MAX_METADATA_PERCENTAGE


def recover_embedding_input(
    chunk: DocumentChunkWithoutVectors, present_tokenizer: BaseTokenizer
) -> str:
    """Rebuild the text that was actually embedded when this chunk was indexed.

    Stored `content` ends in the metadata's keyword form ("Jane Doe"); the embedding
    used the labeled form ("Metadata: author - Jane Doe"). So swap the keyword tail
    (`metadata_suffix`) for the labeled form rebuilt from `metadata_list` — but only
    when indexing embedded it: the chunker skips an oversized labeled tail while
    still storing the keyword one, so re-appending it would drift the vector (see
    `_semantic_tail_was_embedded`). No stored metadata -> return `content` as-is.

    `present_tokenizer` must be the PRESENT model's (what indexing used); the FUTURE
    embedder's would defeat the skip check on a model change.

    Residual: a second chunker branch (title + metadata nearly filling the budget)
    also drops the labeled tail but isn't reconstructible here without the PRESENT
    search settings, so that rare case is left uncorrected.
    """
    keyword_metadata = chunk.metadata_suffix or ""
    if not keyword_metadata:
        return chunk.content
    without_metadata = chunk.content.removesuffix(keyword_metadata)
    # If nothing was removed, content didn't end with the stored metadata, so
    # return it unchanged rather than appending a second metadata block.
    if without_metadata == chunk.content:
        return chunk.content
    semantic_tail = rebuild_semantic_tail(chunk)
    if not _semantic_tail_was_embedded(
        semantic_tail, chunk.max_chunk_size, present_tokenizer
    ):
        return without_metadata
    return without_metadata + semantic_tail


def _title_prefix(chunk: DocumentChunkWithoutVectors) -> str:
    """The title prefix the chunker prepends to content (`extract_blurb(title) +
    RETURN_SEPARATOR`). Approximated with the full stored title; for very long
    titles the chunker truncates to BLURB_SIZE tokens, so the rebuilt prefix can
    be marginally longer — accepted imprecision (the title is also encoded
    separately as `title_vector`)."""
    return f"{chunk.title}{RETURN_SEPARATOR}" if chunk.title else ""


def _stored_chunk_to_doc_aware(
    chunk: DocumentChunkWithoutVectors, embed_input: str
) -> DocAwareChunk:
    """Minimal DocAwareChunk that drives DefaultIndexingEmbedder unchanged.

    The whole embedding input goes in `content` with every enrichment field
    empty, so generate_enriched_content_for_chunk_embedding reproduces exactly
    `embed_input`. The source_document only needs `id` + title for the embedder
    (`.id`, `.get_title_for_document_index()`)."""
    source_document = Document(
        id=chunk.document_id,
        source=DocumentSource(chunk.source_type),
        semantic_identifier=chunk.semantic_identifier,
        # A stored title of None means the source title was empty, which at index
        # time produced NO title embedding. Pass "" (not None) so
        # get_title_for_document_index returns None and reproduces that; passing
        # None would wrongly fall back to semantic_identifier and add a title vector.
        title=chunk.title if chunk.title is not None else "",
        sections=[],
        metadata={},
    )
    return DocAwareChunk(
        chunk_id=chunk.chunk_index,
        blurb=chunk.blurb,
        content=embed_input,
        source_links=None,
        image_file_id=None,
        section_continuation=False,
        source_document=source_document,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        contextual_rag_reserved_tokens=0,
        doc_summary="",
        chunk_context="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        large_chunk_reference_ids=[],
    )


def _match_embeddings_by_identity(
    stored_chunks: list[DocumentChunkWithoutVectors],
    embedded: list[IndexChunk],
) -> list[IndexChunk]:
    """Reorder `embedded` to line up with `stored_chunks` by identity
    (document_id, chunk_index), NOT list position — embed_chunks may return chunks
    in a different order, and pairing by position would bind a chunk's id to another
    chunk's vector (a reorder the count check can't catch). Identity is unique per
    call: only regular chunks are ported."""
    if len(embedded) != len(stored_chunks):
        raise RuntimeError(
            f"Embedder returned {len(embedded)} chunks for {len(stored_chunks)} inputs."
        )
    by_identity = {(ic.source_document.id, ic.chunk_id): ic for ic in embedded}
    if len(by_identity) != len(embedded):
        raise RuntimeError(
            "Duplicate (document_id, chunk_index) identities among re-embedded "
            "chunks; cannot pair vectors to stored chunks unambiguously."
        )
    matched: list[IndexChunk] = []
    for stored in stored_chunks:
        ic = by_identity.get((stored.document_id, stored.chunk_index))
        if ic is None:
            raise RuntimeError(
                f"Embedder returned no chunk for "
                f"{stored.document_id}#{stored.chunk_index}"
            )
        matched.append(ic)
    return matched


def re_embed_chunks(
    stored_chunks: list[DocumentChunkWithoutVectors],
    strategy: ReembedStrategy,
    embedder: IndexingEmbedder,
    augmentation_ctx: AugmentationReembedContext | None = None,
    present_tokenizer: BaseTokenizer | None = None,
) -> list[DocumentChunk]:
    """Re-embed stored chunks under a prebuilt strategy + embedder (no DB access).

    Returns DocumentChunks ready to write to the FUTURE index. For MODEL_ONLY only
    `content_vector`/`title_vector` change; every other field is copied through.
    For AUGMENTATION the stored `content`, `doc_summary` and `chunk_context` are
    also rebuilt under FUTURE settings (`augmentation_ctx` is required, and for
    FUTURE-RAG-on must carry the contextual LLM). Chunks may span documents; only
    when FUTURE RAG is on must a document's chunks ALL be in one call — the LLM's
    doc-text reconstruction needs it complete. FUTURE-RAG-off and MODEL_ONLY re-embed
    each chunk independently, so the caller may split a document across calls.

    `present_tokenizer` (required for MODEL_ONLY) is the PRESENT embedding model's
    tokenizer — the one indexing used — needed to reproduce the metadata-tail skip
    exactly. The FUTURE embedder's tokenizer must NOT be substituted: on a model
    change it can count the tail differently and flip the threshold, re-embedding
    text the PRESENT index never did.
    """
    if not stored_chunks:
        return []
    if strategy is ReembedStrategy.AUGMENTATION:
        if augmentation_ctx is None:
            raise ValueError(
                "AUGMENTATION re-embed requires an AugmentationReembedContext"
            )
        return _augmentation_reembed(stored_chunks, embedder, augmentation_ctx)

    if present_tokenizer is None:
        raise ValueError("MODEL_ONLY re-embed requires the PRESENT tokenizer")
    embed_inputs = [
        recover_embedding_input(chunk, present_tokenizer) for chunk in stored_chunks
    ]
    doc_aware_chunks = [
        _stored_chunk_to_doc_aware(chunk, embed_input)
        for chunk, embed_input in zip(stored_chunks, embed_inputs)
    ]
    embedded = embedder.embed_chunks(doc_aware_chunks)
    # Pair each stored chunk with its OWN vector by identity, not list position.
    matched = _match_embeddings_by_identity(stored_chunks, embedded)
    # Whole stored chunk + the two new vectors; everything else copied through.
    return [
        DocumentChunk(
            **dict(stored),
            content_vector=index_chunk.embeddings.full_embedding,
            title_vector=index_chunk.title_embedding,
        )
        for stored, index_chunk in zip(stored_chunks, matched)
    ]


def _bare_contents(stored_chunks: list[DocumentChunkWithoutVectors]) -> list[str]:
    """Strip every stored chunk back to its original (un-augmented) text via the
    canonical inverse of the indexing-time enrichment."""
    # Lazy import: opensearch_document_index is a heavy module and only needed on
    # the AUGMENTATION path; keeps port_reembed's import surface light + cycle-free.
    from onyx.document_index.opensearch.opensearch_document_index import (
        convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned,
    )

    uncleaned = [
        convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned(chunk, None, {})
        for chunk in stored_chunks
    ]
    cleaned = cleanup_content_for_chunks(uncleaned)
    return [chunk.content for chunk in cleaned]


def _reconstruct_source_document(
    stored_chunks: list[DocumentChunkWithoutVectors], bare_contents: list[str]
) -> Document:
    """Rebuild a minimal Document whose get_text_content() returns the document
    text reconstructed from its bare chunks (chunk-index order). Used by the
    contextual LLM to regenerate summaries — see the module docstring on the
    accepted imprecision of concatenating overlapping chunks."""
    ordered = sorted(
        zip(stored_chunks, bare_contents), key=lambda pair: pair[0].chunk_index
    )
    doc_text = " ".join(bare for _, bare in ordered if bare)
    first = stored_chunks[0]
    return Document(
        id=first.document_id,
        source=DocumentSource(first.source_type),
        semantic_identifier=first.semantic_identifier,
        title=first.title if first.title is not None else "",
        sections=[TextSection(text=doc_text)],
        metadata={},
    )


def _future_semantic_tail(
    chunk: DocumentChunkWithoutVectors, future_embedding_tokenizer: BaseTokenizer
) -> str:
    """The semantic metadata tail to embed when rebuilding under FUTURE settings —
    empty when a fresh FUTURE index would drop it as oversized (the chunker's
    MAX_METADATA_PERCENTAGE skip; see _semantic_tail_was_embedded), so the re-embedded
    vector matches index-time behavior."""
    semantic_tail = rebuild_semantic_tail(chunk)
    if not _semantic_tail_was_embedded(
        semantic_tail, chunk.max_chunk_size, future_embedding_tokenizer
    ):
        return ""
    return semantic_tail


def _augmentation_reembed(
    stored_chunks: list[DocumentChunkWithoutVectors],
    embedder: IndexingEmbedder,
    ctx: AugmentationReembedContext,
) -> list[DocumentChunk]:
    bare_contents = _bare_contents(stored_chunks)
    future_rag_on = ctx.future_enable_contextual_rag
    reserved = ctx.contextual_rag_reserved_tokens if future_rag_on else 0

    # One reconstructed Document per document_id — the input may span documents,
    # and each chunk's enrichment must see only its own document's text.
    pairs_by_doc: dict[str, list[tuple[DocumentChunkWithoutVectors, str]]] = (
        defaultdict(list)
    )
    for chunk, bare in zip(stored_chunks, bare_contents):
        pairs_by_doc[chunk.document_id].append((chunk, bare))
    source_documents = {
        doc_id: _reconstruct_source_document(
            [chunk for chunk, _ in pairs], [bare for _, bare in pairs]
        )
        for doc_id, pairs in pairs_by_doc.items()
    }

    # Rebuild each chunk from its bare content under FUTURE enrichment settings.
    # title_prefix + metadata are unchanged by a RAG toggle, so they are restored;
    # doc_summary/chunk_context start empty and are filled below when RAG is on.
    doc_aware_chunks = [
        DocAwareChunk(
            chunk_id=chunk.chunk_index,
            blurb=chunk.blurb,
            content=bare,
            source_links=None,
            image_file_id=None,
            section_continuation=False,
            source_document=source_documents[chunk.document_id],
            title_prefix=_title_prefix(chunk),
            metadata_suffix_semantic=_future_semantic_tail(
                chunk, ctx.future_embedding_tokenizer
            ),
            metadata_suffix_keyword=chunk.metadata_suffix or "",
            contextual_rag_reserved_tokens=reserved,
            doc_summary="",
            chunk_context="",
            mini_chunk_texts=None,
            large_chunk_id=None,
            large_chunk_reference_ids=[],
        )
        for chunk, bare in zip(stored_chunks, bare_contents)
    ]

    if future_rag_on:
        if ctx.llm is None or ctx.tokenizer is None:
            raise ValueError(
                "contextual-RAG-on re-embed requires an LLM + tokenizer in the context"
            )
        # Lazy import to avoid an import cycle with the indexing pipeline.
        from onyx.indexing.indexing_pipeline import add_contextual_summaries

        # Groups by source_document.id internally, so the mixed-doc input is fine.
        add_contextual_summaries(
            chunks=doc_aware_chunks,
            llm=ctx.llm,
            tokenizer=ctx.tokenizer,
            chunk_token_limit=ctx.chunk_token_limit,
        )

    embedded = embedder.embed_chunks(doc_aware_chunks)
    # Pair each stored chunk with its OWN vector by identity, not list position.
    matched = _match_embeddings_by_identity(stored_chunks, embedded)

    results: list[DocumentChunk] = []
    for stored, doc_aware, index_chunk in zip(stored_chunks, doc_aware_chunks, matched):
        fields = dict(stored)
        # The stored (BM25) content, rebuilt under FUTURE enrichment.
        fields["content"] = generate_enriched_content_for_chunk_text(doc_aware)
        fields["doc_summary"] = doc_aware.doc_summary
        fields["chunk_context"] = doc_aware.chunk_context
        results.append(
            DocumentChunk(
                **fields,
                content_vector=index_chunk.embeddings.full_embedding,
                title_vector=index_chunk.title_embedding,
            )
        )
    return results
