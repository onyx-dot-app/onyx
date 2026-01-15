from onyx.configs.app_configs import BLURB_SIZE
from onyx.configs.constants import RETURN_SEPARATOR
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.indexing.models import DocMetadataAwareIndexChunk


def generate_enriched_content_for_chunk(chunk: DocMetadataAwareIndexChunk) -> str:
    return f"{chunk.title_prefix}{chunk.doc_summary}{chunk.content}{chunk.chunk_context}{chunk.metadata_suffix_keyword}"


def cleanup_content_for_chunks(
    chunks: list[InferenceChunkUncleaned],
) -> list[InferenceChunk]:
    """
    Removes indexing-time content additions from chunks. Inverse of
    generate_enriched_content_for_chunk.

    During indexing, chunks are augmented with additional text to improve search
    quality:
    - Title prepended to content (for better keyword/semantic matching)
    - Metadata suffix appended to content
    - Contextual RAG: doc_summary (beginning) and chunk_context (end)

    This function strips these additions before returning chunks to users,
    restoring the original document content. Cleaning is applied in sequence:
    1. Title removal:
        - Full match: Strips exact title from beginning
        - Partial match: If content starts with title[:BLURB_SIZE], splits on
          RETURN_SEPARATOR to remove title section
    2. Metadata suffix removal:
        - Strips metadata_suffix from end, plus trailing RETURN_SEPARATOR
    3. Contextual RAG removal:
        - Strips doc_summary from beginning (if present)
        - Strips chunk_context from end (if present)

    TODO(andrei): This entire function is not that fantastic, clean it up during
    QA before rolling out OpenSearch.

    Args:
        chunks: Chunks as retrieved from the document index with indexing
            augmentations intact.

    Returns:
        Clean InferenceChunk objects with augmentations removed, containing only
            the original document content that should be shown to users.
    """

    def _remove_title(chunk: InferenceChunkUncleaned) -> str:
        # TODO(andrei): This was ported over from
        # backend/onyx/document_index/vespa/vespa_document_index.py but I don't
        # think this logic is correct. In Vespa at least we set the title field
        # from the output of get_title_for_document_index, which is not
        # necessarily the same data that is prepended to the content; that comes
        # from title_prefix.
        # This was added in
        # https://github.com/onyx-dot-app/onyx/commit/e90c66c1b61c5b7da949652d703f7c906863e6e4#diff-2a2a29d5929de75cdaea77867a397934d9f8b785ce40a861c0d704033e3663ab,
        # see postprocessing.py. At that time the content enrichment logic was
        # also added in that commit, see
        # https://github.com/onyx-dot-app/onyx/commit/e90c66c1b61c5b7da949652d703f7c906863e6e4#diff-d807718aa263a15c1d991a4ab063c360c8419eaad210b4ba70e1e9f47d2aa6d2R77
        # chunker.py.
        if not chunk.title or not chunk.content:
            return chunk.content

        if chunk.content.startswith(chunk.title):
            return chunk.content[len(chunk.title) :].lstrip()

        # BLURB SIZE is by token instead of char but each token is at least 1 char
        # If this prefix matches the content, it's assumed the title was prepended
        if chunk.content.startswith(chunk.title[:BLURB_SIZE]):
            return (
                chunk.content.split(RETURN_SEPARATOR, 1)[-1]
                if RETURN_SEPARATOR in chunk.content
                else chunk.content
            )
        return chunk.content

    def _remove_metadata_suffix(chunk: InferenceChunkUncleaned) -> str:
        if not chunk.metadata_suffix:
            return chunk.content
        return chunk.content.removesuffix(chunk.metadata_suffix).rstrip(
            RETURN_SEPARATOR
        )

    def _remove_contextual_rag(chunk: InferenceChunkUncleaned) -> str:
        # remove document summary
        if chunk.doc_summary and chunk.content.startswith(chunk.doc_summary):
            chunk.content = chunk.content[len(chunk.doc_summary) :].lstrip()
        # remove chunk context
        if chunk.chunk_context and chunk.content.endswith(chunk.chunk_context):
            chunk.content = chunk.content[
                : len(chunk.content) - len(chunk.chunk_context)
            ].rstrip()
        return chunk.content

    for chunk in chunks:
        chunk.content = _remove_title(chunk)
        chunk.content = _remove_metadata_suffix(chunk)
        chunk.content = _remove_contextual_rag(chunk)

    return [chunk.to_inference_chunk() for chunk in chunks]
