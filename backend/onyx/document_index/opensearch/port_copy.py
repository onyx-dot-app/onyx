"""PRESENT -> FUTURE chunk copy for the reindex port.

Reads a document's existing chunks from the PRESENT OpenSearch index via the PIT
scan, re-embeds them under the FUTURE model, and writes them to the FUTURE index
create-only (it never overwrites a chunk a live/forward writer already owns, so a
stale backlog write can't clobber a fresher one). The port Celery task drives this per
batch and owns lifecycle (cursor, stall); keeping the OpenSearch specifics here
keeps them off the generic docprocessing worker.

The AUGMENTATION strategy (contextual-RAG toggle/model change) re-enriches each
document, which needs all of a document's chunks together to reconstruct the doc
text — and a document's chunks can span PIT pages — so that path buffers the
batch into a single page, while MODEL_ONLY streams page by page.
"""

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
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.utils.logger import setup_logger
from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE

logger = setup_logger()

# Chunks per create-only write. AUGMENTATION buffers a whole batch into one page, so
# an unbounded write could run minutes with no heartbeat and get a live port falsely
# stall-failed. Matches the MODEL_ONLY per-page size the watchdog already tolerates.
_PORT_WRITE_PAGE_SIZE = 1000


def _build_augmentation_ctx(
    future_search_settings: SearchSettings,
) -> AugmentationReembedContext:
    """Prepare the AUGMENTATION inputs while a DB session is available. For
    FUTURE-RAG-off only the flag matters; for FUTURE-RAG-on we also resolve the
    contextual LLM/tokenizer and the same token budgets the chunker uses."""
    if not future_search_settings.enable_contextual_rag:
        return AugmentationReembedContext(future_enable_contextual_rag=False)

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
    augmentation_ctx: AugmentationReembedContext | None = None,
    surviving_doc_ids: Callable[[], set[str]] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> int:
    """Port one batch of documents PRESENT -> FUTURE; returns chunks written.

    Both callbacks run per page right before the write (after the slow re-embed):
    surviving_doc_ids drops chunks of docs deleted mid-batch (no resurrection);
    should_abort stops writing once the attempt is cancelled."""
    pages: Iterable[list[DocumentChunkWithoutVectors]]
    if strategy is ReembedStrategy.AUGMENTATION:
        # Buffer the batch into one page: re-enrichment needs each document's
        # chunks complete (they can span PIT pages), and one page also means one
        # embed round-trip + one bulk write for the whole batch.
        pages = [
            [
                chunk
                for page in present_client.iter_chunks_for_doc_ids(doc_ids)
                for chunk in page
            ]
        ]
    else:
        pages = present_client.iter_chunks_for_doc_ids(doc_ids)

    chunks_written = 0
    for page_chunks in pages:
        reembedded = re_embed_chunks(
            page_chunks, strategy, embedder, augmentation_ctx=augmentation_ctx
        )
        if not reembedded:
            continue
        # Stop writing the instant the attempt is cancelled (e.g. by a deletion).
        if should_abort is not None and should_abort():
            break
        # Drop chunks of docs deleted mid-batch — create-only would otherwise
        # re-add them to FUTURE (resurrection).
        if surviving_doc_ids is not None:
            surviving = surviving_doc_ids()
            reembedded = [c for c in reembedded if c.document_id in surviving]
            if not reembedded:
                continue
        # Sub-page the write, heartbeating (via should_abort) before each, so one
        # write can't outlast the watchdog and get this live port falsely failed.
        for i in range(0, len(reembedded), _PORT_WRITE_PAGE_SIZE):
            if should_abort is not None and should_abort():
                return chunks_written
            sub = reembedded[i : i + _PORT_WRITE_PAGE_SIZE]
            future_index.index_raw_chunks(sub, use_create_only=True)
            chunks_written += len(sub)
    return chunks_written


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
        self._augmentation_ctx: AugmentationReembedContext | None = None
        if self._strategy is ReembedStrategy.AUGMENTATION:
            self._augmentation_ctx = _build_augmentation_ctx(future_search_settings)

    def copy_doc_batch(
        self,
        doc_ids: list[str],
        surviving_doc_ids: Callable[[], set[str]] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> int:
        return copy_present_chunks_to_future(
            present_client=self._present_client,
            future_index=self._future_index,
            doc_ids=doc_ids,
            strategy=self._strategy,
            embedder=self._embedder,
            augmentation_ctx=self._augmentation_ctx,
            surviving_doc_ids=surviving_doc_ids,
            should_abort=should_abort,
        )
