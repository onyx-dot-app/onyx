"""PRESENT -> FUTURE chunk copy for the reindex port.

Reads a document's existing chunks from the PRESENT OpenSearch index via the PIT
scan, re-embeds them under the FUTURE model, and writes them to the FUTURE index
create-only (it never overwrites a chunk a live/forward writer already owns, so a
stale backlog write can't clobber a fresher one). The port Celery task drives this per
batch and owns lifecycle (cursor, stall); keeping the OpenSearch specifics here
keeps them off the generic docprocessing worker.

Contextual-RAG-ON AUGMENTATION re-embeds one document per page — its per-chunk LLM
re-enrichment is the slow, unheartbeated phase, and needs a doc's chunks complete
(they span PIT pages) to rebuild the doc text. RAG-off / MODEL_ONLY have no LLM step,
so they stream PIT pages.
"""

from collections import defaultdict
from collections.abc import Callable
from collections.abc import Iterable

from onyx.db.models import SearchSettings
from onyx.document_index.factory import build_opensearch_document_index
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import DocumentChunkWithoutVectors
from onyx.indexing.chunker import DEFAULT_CONTEXTUAL_RAG_RESERVED_TOKENS
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.port_reembed import AugmentationReembedContext
from onyx.indexing.port_reembed import re_embed_chunks
from onyx.indexing.port_reembed import ReembedStrategy
from onyx.indexing.port_reembed import select_reembed_strategy
from onyx.llm.factory import get_contextual_rag_llm_for_search_settings
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import get_tokenizer
from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE

# Cap per bulk write so it can't run long unheartbeated and get a live port stall-failed.
_PORT_WRITE_PAGE_SIZE = 1000


def _build_augmentation_ctx(
    future_search_settings: SearchSettings,
) -> AugmentationReembedContext:
    """Prepare the AUGMENTATION inputs while a DB session is available. The FUTURE
    embedding tokenizer is always resolved (reproduces the chunker's metadata-tail skip);
    for FUTURE-RAG-on we also resolve the contextual LLM/tokenizer and the same token
    budgets the chunker uses."""
    future_embedding_tokenizer = get_tokenizer(
        model_name=future_search_settings.model_name,
        provider_type=future_search_settings.provider_type,
    )
    if not future_search_settings.enable_contextual_rag:
        return AugmentationReembedContext(
            future_enable_contextual_rag=False,
            future_embedding_tokenizer=future_embedding_tokenizer,
        )

    llm = get_contextual_rag_llm_for_search_settings(future_search_settings)
    if llm is None:
        raise ValueError(
            "contextual-RAG is enabled on the FUTURE search settings but no "
            "contextual RAG model is configured (and no tenant default exists)"
        )
    tokenizer = get_tokenizer(
        model_name=llm.config.model_name,
        provider_type=llm.config.model_provider,
    )
    return AugmentationReembedContext(
        future_enable_contextual_rag=True,
        future_embedding_tokenizer=future_embedding_tokenizer,
        llm=llm,
        tokenizer=tokenizer,
        # The same *2 fudge factor over the chunk size that the indexing
        # pipeline applies to absorb embedder-vs-LLM tokenizer drift.
        chunk_token_limit=DOC_EMBEDDING_CONTEXT_SIZE * 2,
        contextual_rag_reserved_tokens=DEFAULT_CONTEXTUAL_RAG_RESERVED_TOKENS,
    )


def copy_present_chunks_to_future(
    present_client: OpenSearchIndexClient,
    future_index: OpenSearchDocumentIndex,
    doc_ids: list[str],
    strategy: ReembedStrategy,
    embedder: IndexingEmbedder,
    present_tokenizer: BaseTokenizer,
    augmentation_ctx: AugmentationReembedContext | None = None,
    surviving_doc_ids: Callable[[], set[str]] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> tuple[int, bool]:
    """Port one batch PRESENT -> FUTURE; returns (chunks written, aborted).
    aborted=True means should_abort stopped the copy mid-batch, so the caller must not
    advance its cursor past this partial batch.

    should_abort brackets each re-embed and precedes each write — it aborts a cancelled
    attempt and heartbeats so a slow-but-live port isn't stall-failed. surviving_doc_ids
    drops chunks of docs deleted mid-batch (no resurrection)."""
    pages: Iterable[list[DocumentChunkWithoutVectors]]
    # Contextual RAG-on AUGMENTATION: buffer to reassemble each doc (chunks span PIT pages), then
    # re-embed one doc per page so the unheartbeated per-chunk LLM re-enrichment is bounded
    # to a single doc, not a whole batch (kept under the stall threshold). Others stream PIT pages.
    rag_on_augmentation = (
        strategy is ReembedStrategy.AUGMENTATION
        and augmentation_ctx is not None
        and augmentation_ctx.future_enable_contextual_rag
    )
    if rag_on_augmentation:
        by_doc: dict[str, list[DocumentChunkWithoutVectors]] = defaultdict(list)
        for page in present_client.iter_chunks_for_doc_ids(doc_ids):
            for chunk in page:
                by_doc[chunk.document_id].append(chunk)
        pages = list(by_doc.values())
    else:
        pages = present_client.iter_chunks_for_doc_ids(doc_ids)

    chunks_written = 0
    for page_chunks in pages:
        # Heartbeat before re_embed (the longest gap), not just before writes; also
        # skips a needless re_embed on cancel.
        if should_abort is not None and should_abort():
            return chunks_written, True
        reembedded = re_embed_chunks(
            page_chunks,
            strategy,
            embedder,
            augmentation_ctx=augmentation_ctx,
            present_tokenizer=present_tokenizer,
        )
        if not reembedded:
            continue
        # Stop writing the instant the attempt is cancelled (e.g. by a deletion).
        if should_abort is not None and should_abort():
            return chunks_written, True
        # Heartbeat before each sub-page write.
        for i in range(0, len(reembedded), _PORT_WRITE_PAGE_SIZE):
            if should_abort is not None and should_abort():
                return chunks_written, True
            sub = reembedded[i : i + _PORT_WRITE_PAGE_SIZE]
            # Drop chunks of docs deleted mid-batch, re-checked immediately before each
            # write (not once per page): a doc's chunks can span several sub-pages, and a
            # doc deleted between writes would otherwise be create-only resurrected.
            if surviving_doc_ids is not None:
                surviving = surviving_doc_ids()
                sub = [c for c in sub if c.document_id in surviving]
                if not sub:
                    continue
            future_index.index_raw_chunks(sub, use_create_only=True)
            chunks_written += len(sub)
    return chunks_written, False


class PortCopier:
    """Resolves the OpenSearch handles, reembed strategy, and embedder once so
    copy_doc_batch runs with no DB session held. Build it while the search
    settings are session-attached: the FUTURE provider credentials lazy-load,
    and the AUGMENTATION contextual LLM/model-config resolution needs a session.
    """

    def __init__(
        self,
        present_search_settings: SearchSettings,
        future_search_settings: SearchSettings,
    ) -> None:
        self._strategy = select_reembed_strategy(
            present_search_settings, future_search_settings
        )
        self._present_client = OpenSearchIndexClient(
            index_name=present_search_settings.index_name
        )
        self._future_index = build_opensearch_document_index(future_search_settings)
        self._embedder = DefaultIndexingEmbedder.from_db_search_settings(
            future_search_settings
        )
        # The PRESENT model's tokenizer (what indexing used) — MODEL_ONLY needs it to
        # reproduce the metadata-tail skip; the FUTURE embedder's would flip it.
        self._present_tokenizer = get_tokenizer(
            model_name=present_search_settings.model_name,
            provider_type=present_search_settings.provider_type,
        )
        self._augmentation_ctx: AugmentationReembedContext | None = None
        if self._strategy is ReembedStrategy.AUGMENTATION:
            self._augmentation_ctx = _build_augmentation_ctx(future_search_settings)

    def copy_doc_batch(
        self,
        doc_ids: list[str],
        surviving_doc_ids: Callable[[], set[str]] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> tuple[int, bool]:
        return copy_present_chunks_to_future(
            present_client=self._present_client,
            future_index=self._future_index,
            doc_ids=doc_ids,
            strategy=self._strategy,
            embedder=self._embedder,
            present_tokenizer=self._present_tokenizer,
            augmentation_ctx=self._augmentation_ctx,
            surviving_doc_ids=surviving_doc_ids,
            should_abort=should_abort,
        )
