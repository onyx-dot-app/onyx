import concurrent.futures

import httpx
from pydantic import BaseModel

from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.document_index_utils import get_document_chunk_ids
from onyx.document_index.interfaces import EnrichedDocumentIndexingInfo
from onyx.document_index.interfaces import MinimalDocumentIndexingInfo
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.interfaces_new import DocumentInsertionRecord
from onyx.document_index.interfaces_new import DocumentSectionRequest
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.vespa.deletion import delete_vespa_chunks
from onyx.document_index.vespa.indexing_utils import BaseHTTPXClientContext
from onyx.document_index.vespa.indexing_utils import batch_index_vespa_chunks
from onyx.document_index.vespa.indexing_utils import check_for_final_chunk_existence
from onyx.document_index.vespa.indexing_utils import clean_chunk_id_copy
from onyx.document_index.vespa.indexing_utils import GlobalHTTPXClientContext
from onyx.document_index.vespa.indexing_utils import TemporaryHTTPXClientContext
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa_constants import BATCH_SIZE
from onyx.document_index.vespa_constants import NUM_THREADS
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.utils.batching import batch_generator
from shared_configs.model_server_models import Embedding


class TenantState(BaseModel):
    """
    Captures the tenant-related state for an instance of VespaDocumentIndex.

    TODO(andrei): If we find that we need this for Opensearch too, just move
    this to interfaces_new.py.
    """

    model_config = {"frozen": True}

    tenant_id: str
    multitenant: bool


def _enrich_basic_chunk_info(
    index_name: str,
    http_client: httpx.Client,
    document_id: str,
    previous_chunk_count: int | None,
    new_chunk_count: int,
) -> EnrichedDocumentIndexingInfo:
    """Determines which chunks need to be deleted during document reindexing.

    When a document is reindexed, it may have fewer chunks than before. This
    function identifies the range of old chunks that need to be deleted by
    comparing the new chunk count with the previous chunk count.

    Example:
        If a document previously had 10 chunks (0-9) and now has 7 chunks (0-6),
        this function identifies that chunks 7-9 need to be deleted.

    Args:
        index_name: The Vespa index/schema name.
        http_client: HTTP client for making requests to Vespa.
        document_id: The Vespa-sanitized ID of the document being reindexed.
        previous_chunk_count: The total number of chunks the document had before
            reindexing. None for documents using the legacy chunk ID system.
        new_chunk_count: The total number of chunks the document has after
            reindexing. This becomes the starting index for deletion since
            chunks are 0-indexed.

    Returns:
        EnrichedDocumentIndexingInfo with chunk_start_index set to
        new_chunk_count (where deletion begins) and chunk_end_index set to
        previous_chunk_count (where deletion ends).
    """
    # Technically last indexed chunk index +1.
    last_indexed_chunk = previous_chunk_count
    # If the document has no `chunk_count` in the database, we know that it
    # has the old chunk ID system and we must check for the final chunk index.
    is_old_version = False
    if last_indexed_chunk is None:
        is_old_version = True
        minimal_doc_info = MinimalDocumentIndexingInfo(
            doc_id=document_id, chunk_start_index=new_chunk_count
        )
        last_indexed_chunk = check_for_final_chunk_existence(
            minimal_doc_info=minimal_doc_info,
            start_index=new_chunk_count,
            index_name=index_name,
            http_client=http_client,
        )

    enriched_doc_info = EnrichedDocumentIndexingInfo(
        doc_id=document_id,
        chunk_start_index=new_chunk_count,
        chunk_end_index=last_indexed_chunk,
        old_version=is_old_version,
    )
    return enriched_doc_info


class VespaDocumentIndex(DocumentIndex):
    """Vespa-specific implementation of the DocumentIndex interface.

    This class provides document indexing, retrieval, and management operations
    for a Vespa search engine instance. It handles the complete lifecycle of
    document chunks within a specific Vespa index/schema.
    """

    def __init__(
        self,
        index_name: str,
        tenant_state: TenantState,
        large_chunks_enabled: bool,
        httpx_client: httpx.Client | None = None,
    ) -> None:
        self._index_name = index_name
        self._tenant_id = tenant_state.tenant_id
        self._large_chunks_enabled = large_chunks_enabled
        # NOTE: using `httpx` here since `requests` doesn't support HTTP2. This
        # is beneficial for indexing / updates / deletes since we have to make a
        # large volume of requests.
        self._httpx_client_context: BaseHTTPXClientContext
        if httpx_client:
            # Use the provided client. Because this client is presumed global,
            # it does not close after exiting a context manager.
            self._httpx_client_context = GlobalHTTPXClientContext(httpx_client)
        else:
            # We did not receive a client, so create one what will close after
            # exiting a context manager.
            self._httpx_client_context = TemporaryHTTPXClientContext(
                get_vespa_http_client
            )
        self._multitenant = tenant_state.multitenant

    def verify_and_create_index_if_necessary(
        self, embedding_dim: int, embedding_precision: EmbeddingPrecision
    ) -> None:
        raise NotImplementedError

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        indexing_metadata: IndexingMetadata,
    ) -> list[DocumentInsertionRecord]:
        doc_id_to_chunk_cnt_diff = indexing_metadata.doc_id_to_chunk_cnt_diff
        doc_id_to_previous_chunk_cnt = {
            doc_id: chunk_cnt_diff.old_chunk_cnt
            for doc_id, chunk_cnt_diff in doc_id_to_chunk_cnt_diff.items()
        }
        doc_id_to_new_chunk_cnt = {
            doc_id: chunk_cnt_diff.new_chunk_cnt
            for doc_id, chunk_cnt_diff in doc_id_to_chunk_cnt_diff.items()
        }
        assert (
            len(doc_id_to_chunk_cnt_diff)
            == len(doc_id_to_previous_chunk_cnt)
            == len(doc_id_to_new_chunk_cnt)
        )

        # Vespa has restrictions on valid characters, yet document IDs come from
        # external w.r.t. this class. We need to sanitize them.
        cleaned_chunks: list[DocMetadataAwareIndexChunk] = [
            clean_chunk_id_copy(chunk) for chunk in chunks
        ]
        assert len(cleaned_chunks) == len(chunks)

        # Needed so the final DocumentInsertionRecord returned can have the
        # original document ID. cleaned_chunks might not contain IDs exactly as
        # callers supplied them.
        new_document_id_to_original_document_id: dict[str, str] = dict()
        for i, cleaned_chunk in enumerate(cleaned_chunks):
            old_chunk = chunks[i]
            new_document_id_to_original_document_id[
                cleaned_chunk.source_document.id
            ] = old_chunk.source_document.id

        existing_docs: set[str] = set()

        with (
            concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as executor,
            self._httpx_client_context as http_client,
        ):
            # We require the start and end index for each document in order to
            # know precisely which chunks to delete. This information exists for
            # documents that have `chunk_count` in the database, but not for
            # `old_version` documents.
            enriched_doc_infos: list[EnrichedDocumentIndexingInfo] = [
                _enrich_basic_chunk_info(
                    index_name=self._index_name,
                    http_client=http_client,
                    document_id=doc_id,
                    previous_chunk_count=doc_id_to_previous_chunk_cnt[doc_id],
                    new_chunk_count=doc_id_to_new_chunk_cnt[doc_id],
                )
                for doc_id in doc_id_to_chunk_cnt_diff.keys()
            ]

            for enriched_doc_info in enriched_doc_infos:
                # If the document has previously indexed chunks, we know it
                # previously existed and this is a reindex.
                if enriched_doc_info.chunk_end_index:
                    existing_docs.add(enriched_doc_info.doc_id)

            # Now, for each doc, we know exactly where to start and end our
            # deletion. So let's generate the chunk IDs for each chunk to
            # delete.
            # WARNING: This code seems to use
            # indexing_metadata.doc_id_to_chunk_cnt_diff as the source of truth
            # for which chunks to delete. This implies that the onus is on the
            # caller to ensure doc_id_to_chunk_cnt_diff only contains docs
            # relevant to the chunks argument to this method. This should not be
            # the contract of DocumentIndex; and this code is only a refactor
            # from old code. It would seem we should use all_cleaned_doc_ids as
            # the source of truth.
            chunks_to_delete = get_document_chunk_ids(
                enriched_document_info_list=enriched_doc_infos,
                tenant_id=self._tenant_id,  # TODO: Figure out this typing bro wtf.
                large_chunks_enabled=self._large_chunks_enabled,
            )

            # Delete old Vespa documents.
            for doc_chunk_ids_batch in batch_generator(chunks_to_delete, BATCH_SIZE):
                delete_vespa_chunks(
                    doc_chunk_ids=doc_chunk_ids_batch,
                    index_name=self._index_name,
                    http_client=http_client,
                    executor=executor,
                )

            # Insert new Vespa documents.
            for chunk_batch in batch_generator(cleaned_chunks, BATCH_SIZE):
                batch_index_vespa_chunks(
                    chunks=chunk_batch,
                    index_name=self._index_name,
                    http_client=http_client,
                    multitenant=self._multitenant,
                    executor=executor,
                )

        all_cleaned_doc_ids: set[str] = {
            chunk.source_document.id for chunk in cleaned_chunks
        }

        return [
            DocumentInsertionRecord(
                document_id=new_document_id_to_original_document_id[cleaned_doc_id],
                already_existed=cleaned_doc_id in existing_docs,
            )
            for cleaned_doc_id in all_cleaned_doc_ids
        ]

    def delete(self, db_doc_id: str, chunk_count: int | None) -> int:
        raise NotImplementedError

    def update(self, update_requests: list[MetadataUpdateRequest]) -> None:
        raise NotImplementedError

    def id_based_retrieval(
        self, chunk_requests: list[DocumentSectionRequest]
    ) -> list[InferenceChunk]:
        raise NotImplementedError

    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        query_type: QueryType,
        filters: IndexFilters,
        num_to_retrieve: int,
        offset: int = 0,
    ) -> list[InferenceChunk]:
        raise NotImplementedError

    def random_retrieval(
        self,
        filters: IndexFilters | None = None,
        num_to_retrieve: int = 100,
        dirty: bool | None = None,
    ) -> list[InferenceChunk]:
        raise NotImplementedError
