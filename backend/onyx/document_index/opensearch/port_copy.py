"""PRESENT -> FUTURE chunk copy for the reindex port.

Reads a document's existing chunks from the PRESENT OpenSearch index via the PIT
scan, re-embeds them under the FUTURE model, and writes them to the FUTURE index
with external versioning (newest-wins). The port Celery task drives this per
batch and owns lifecycle (cursor, stall); keeping the OpenSearch specifics here
keeps them off the generic docprocessing worker.
"""

from onyx.db.models import SearchSettings
from onyx.document_index.factory import build_opensearch_document_index
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.port_reembed import re_embed_chunks
from onyx.indexing.port_reembed import ReembedStrategy
from onyx.indexing.port_reembed import select_reembed_strategy


def copy_present_chunks_to_future(
    present_client: OpenSearchIndexClient,
    future_index: OpenSearchDocumentIndex,
    doc_ids: list[str],
    strategy: ReembedStrategy,
    embedder: IndexingEmbedder,
) -> int:
    """Port one batch of documents PRESENT -> FUTURE; returns chunks written."""
    chunks_written = 0
    for present_chunks in present_client.iter_chunks_for_doc_ids(doc_ids):
        reembedded = re_embed_chunks(present_chunks, strategy, embedder)
        if not reembedded:
            continue
        future_index.index_raw_chunks(reembedded, use_external_versioning=True)
        chunks_written += len(reembedded)
    return chunks_written


class PortCopier:
    """Resolves the OpenSearch handles, reembed strategy, and embedder once so
    copy_doc_batch runs with no DB session held. Build it while the search
    settings are session-attached: the FUTURE provider credentials lazy-load.
    """

    def __init__(
        self,
        present_search_settings: SearchSettings,
        future_search_settings: SearchSettings,
    ) -> None:
        self._strategy = select_reembed_strategy(
            present_search_settings, future_search_settings
        )
        if self._strategy is ReembedStrategy.AUGMENTATION:
            raise NotImplementedError(
                "Augmentation-change re-embed (contextual-RAG toggle/model) is not "
                "yet supported; only model/prefix/dimension changes are."
            )
        self._present_client = OpenSearchIndexClient(
            index_name=present_search_settings.index_name
        )
        self._future_index = build_opensearch_document_index(future_search_settings)
        self._embedder = DefaultIndexingEmbedder.from_db_search_settings(
            future_search_settings
        )

    def copy_doc_batch(self, doc_ids: list[str]) -> int:
        return copy_present_chunks_to_future(
            present_client=self._present_client,
            future_index=self._future_index,
            doc_ids=doc_ids,
            strategy=self._strategy,
            embedder=self._embedder,
        )
