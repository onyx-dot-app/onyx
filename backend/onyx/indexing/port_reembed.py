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
  text, re-glue under FUTURE settings, then re-embed.

Only regular chunks are handled (the port reads `max_chunk_size ==
DEFAULT_MAX_CHUNK_SIZE`); writes are idempotent (external versioning) so we
re-embed unconditionally rather than diffing content hashes.
"""

import enum

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import convert_metadata_list_of_strings_to_dict
from onyx.connectors.models import Document
from onyx.db.models import SearchSettings
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import DocumentChunkWithoutVectors

# The chunker's canonical metadata-suffix builder. Reused (rather than
# replicated) so the rebuilt semantic tail is byte-identical to what indexing
# produced; replicating it would risk silent drift in the embedding input.
from onyx.indexing.chunker import _get_metadata_suffix_for_document_index
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.models import DocAwareChunk


class ReembedStrategy(enum.Enum):
    # Only the embedder changed; re-embed the same enriched text (tail swapped).
    MODEL_ONLY = "model_only"
    # The contextual-RAG enrichment changed; rebuild the text, then re-embed.
    AUGMENTATION = "augmentation"


def select_reembed_strategy(
    present_ss: SearchSettings, future_ss: SearchSettings
) -> ReembedStrategy:
    """AUGMENTATION when contextual-RAG settings differ (the embedded text
    changes), otherwise MODEL_ONLY. Model/prefix/normalize/dimension and
    multipass changes only alter the vectors (or large/mini chunks the port
    doesn't read), so they fall through to MODEL_ONLY."""
    augmentation_changed = (
        present_ss.enable_contextual_rag != future_ss.enable_contextual_rag
        or present_ss.contextual_rag_model_configuration_id
        != future_ss.contextual_rag_model_configuration_id
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
    semantic_suffix, _ = _get_metadata_suffix_for_document_index(
        metadata, include_separator=True
    )
    return semantic_suffix


def recover_embedding_input(chunk: DocumentChunkWithoutVectors) -> str:
    """Rebuild the text that was actually embedded when this chunk was indexed.

    The stored `content` is that text except for the metadata at its end: it is
    stored in keyword form ("Jane Doe") but was embedded in labeled form
    ("Metadata: author - Jane Doe"). So drop the stored keyword metadata
    (`metadata_suffix`) and append the labeled form rebuilt from `metadata_list`.
    If the chunk has no appended metadata, return `content` as-is.
    """
    keyword_metadata = chunk.metadata_suffix or ""
    if not keyword_metadata:
        return chunk.content
    without_metadata = chunk.content.removesuffix(keyword_metadata)
    # If nothing was removed, content didn't end with the stored metadata, so
    # return it unchanged rather than appending a second metadata block.
    if without_metadata == chunk.content:
        return chunk.content
    return without_metadata + rebuild_semantic_tail(chunk)


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


def re_embed_chunks(
    stored_chunks: list[DocumentChunkWithoutVectors],
    strategy: ReembedStrategy,
    embedder: IndexingEmbedder,
) -> list[DocumentChunk]:
    """Re-embed stored chunks under a prebuilt strategy + embedder (no DB access).

    Returns the whole stored chunks as DocumentChunk, in order, with only
    content_vector and title_vector recomputed (every other field copied through,
    so the FUTURE write is a faithful copy with new embeddings). Raises
    NotImplementedError for AUGMENTATION — only model/prefix/dimension changes are
    supported today.
    """
    if not stored_chunks:
        return []
    if strategy is ReembedStrategy.AUGMENTATION:
        # Augmentation re-embed (strip -> re-glue -> re-embed) is the next
        # increment; the contextual-RAG-on case additionally needs the source
        # document text, which the stored chunks don't carry, so the port must
        # supply it. Fail loudly rather than embed a wrong (un-stripped) input.
        raise NotImplementedError(
            "Augmentation-change re-embed (contextual-RAG toggle/model) is not "
            "yet supported; only model/prefix/dimension changes are."
        )

    embed_inputs = [recover_embedding_input(chunk) for chunk in stored_chunks]
    doc_aware_chunks = [
        _stored_chunk_to_doc_aware(chunk, embed_input)
        for chunk, embed_input in zip(stored_chunks, embed_inputs)
    ]
    embedded = embedder.embed_chunks(doc_aware_chunks)

    # Sanity: the embedder must return chunks 1:1 with what it was given.
    if len(embedded) != len(stored_chunks):
        raise RuntimeError(
            f"Embedder returned {len(embedded)} chunks for {len(stored_chunks)} inputs."
        )
    # Whole stored chunk + the two new vectors; everything else copied through.
    return [
        DocumentChunk(
            **dict(stored),
            content_vector=index_chunk.embeddings.full_embedding,
            title_vector=index_chunk.title_embedding,
        )
        for stored, index_chunk in zip(stored_chunks, embedded)
    ]
