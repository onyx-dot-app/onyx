import concurrent.futures
import logging
import random
from uuid import UUID

import httpx
from pydantic import BaseModel
from retry import retry

from onyx.configs.app_configs import BLURB_SIZE
from onyx.configs.app_configs import RECENCY_BIAS_MULTIPLIER
from onyx.configs.app_configs import RERANK_COUNT
from onyx.configs.chat_configs import DOC_TIME_DECAY
from onyx.configs.chat_configs import TITLE_CONTENT_RATIO
from onyx.configs.constants import RETURN_SEPARATOR
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.context.search.preprocessing.preprocessing import HYBRID_ALPHA
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.document_index_utils import get_document_chunk_ids
from onyx.document_index.interfaces import EnrichedDocumentIndexingInfo
from onyx.document_index.interfaces import MinimalDocumentIndexingInfo
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.interfaces_new import DocumentInsertionRecord
from onyx.document_index.interfaces_new import DocumentSectionRequest
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.vespa.chunk_retrieval import batch_search_api_retrieval
from onyx.document_index.vespa.chunk_retrieval import (
    parallel_visit_api_retrieval,
)
from onyx.document_index.vespa.chunk_retrieval import query_vespa
from onyx.document_index.vespa.deletion import delete_vespa_chunks
from onyx.document_index.vespa.indexing_utils import BaseHTTPXClientContext
from onyx.document_index.vespa.indexing_utils import batch_index_vespa_chunks
from onyx.document_index.vespa.indexing_utils import check_for_final_chunk_existence
from onyx.document_index.vespa.indexing_utils import clean_chunk_id_copy
from onyx.document_index.vespa.indexing_utils import GlobalHTTPXClientContext
from onyx.document_index.vespa.indexing_utils import TemporaryHTTPXClientContext
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from onyx.document_index.vespa.shared_utils.vespa_request_builders import (
    build_vespa_filters,
)
from onyx.document_index.vespa_constants import BATCH_SIZE
from onyx.document_index.vespa_constants import CONTENT_SUMMARY
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.document_index.vespa_constants import NUM_THREADS
from onyx.document_index.vespa_constants import VESPA_TIMEOUT
from onyx.document_index.vespa_constants import YQL_BASE
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.tools.tool_implementations.search.constants import KEYWORD_QUERY_HYBRID_ALPHA
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger
from shared_configs.model_server_models import Embedding


logger = setup_logger(__name__)
# Set the logging level to WARNING to ignore INFO and DEBUG logs from httpx. By
# default it emits INFO-level logs for every request.
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)


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

    assert (
        last_indexed_chunk is not None and last_indexed_chunk >= 0
    ), f"Bug: Last indexed chunk index is None or less than 0 for document: {document_id}."

    enriched_doc_info = EnrichedDocumentIndexingInfo(
        doc_id=document_id,
        chunk_start_index=new_chunk_count,
        chunk_end_index=last_indexed_chunk,
        old_version=is_old_version,
    )
    return enriched_doc_info


def _cleanup_chunks(chunks: list[InferenceChunkUncleaned]) -> list[InferenceChunk]:
    """Removes indexing-time content additions from chunks retrieved from Vespa.

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

    Args:
        chunks: Chunks as retrieved from Vespa with indexing augmentations
            intact.

    Returns:
        Clean InferenceChunk objects with augmentations removed, containing only
            the original document content that should be shown to users.
    """

    def _remove_title(chunk: InferenceChunkUncleaned) -> str:
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


@retry(
    tries=3,
    delay=1,
    backoff=2,
    exceptions=httpx.HTTPError,
)
def _update_single_chunk(
    doc_chunk_id: UUID,
    index_name: str,
    doc_id: str,
    http_client: httpx.Client,
    update_request: MetadataUpdateRequest,
) -> None:
    """Updates a single document chunk in Vespa.

    TODO(andrei): Couldn't this be batched?

    Args:
        doc_chunk_id: The ID of the chunk to update.
        index_name: The index the chunk belongs to.
        doc_id: The ID of the document the chunk belongs to. Used only for
            logging.
        http_client: The HTTP client to use to make the request.
        update_request: Metadata update request object received in the bulk
            update method containing fields to update.
    """

    class _Boost(BaseModel):
        model_config = {"frozen": True}
        assign: float

    class _DocumentSets(BaseModel):
        model_config = {"frozen": True}
        assign: dict[str, int]

    class _AccessControl(BaseModel):
        model_config = {"frozen": True}
        assign: dict[str, int]

    class _Hidden(BaseModel):
        model_config = {"frozen": True}
        assign: bool

    class _UserProjects(BaseModel):
        model_config = {"frozen": True}
        assign: list[int]

    class _VespaPutFields(BaseModel):
        model_config = {"frozen": True}
        # The names of these fields are based the Vespa schema. Changes to the
        # schema require changes here. These names were originally found in
        # backend/onyx/document_index/vespa_constants.py.
        boost: _Boost | None = None
        document_sets: _DocumentSets | None = None
        access_control_list: _AccessControl | None = None
        hidden: _Hidden | None = None
        user_project: _UserProjects | None = None

    class _VespaPutRequest(BaseModel):
        model_config = {"frozen": True}
        fields: _VespaPutFields

    boost_update: _Boost | None = (
        _Boost(assign=update_request.boost)
        if update_request.boost is not None
        else None
    )
    document_sets_update: _DocumentSets | None = (
        _DocumentSets(
            assign={document_set: 1 for document_set in update_request.document_sets}
        )
        if update_request.document_sets is not None
        else None
    )
    access_update: _AccessControl | None = (
        _AccessControl(
            assign={acl_entry: 1 for acl_entry in update_request.access.to_acl()}
        )
        if update_request.access is not None
        else None
    )
    hidden_update: _Hidden | None = (
        _Hidden(assign=update_request.hidden)
        if update_request.hidden is not None
        else None
    )
    user_projects_update: _UserProjects | None = (
        _UserProjects(assign=list(update_request.project_ids))
        if update_request.project_ids is not None
        else None
    )

    vespa_put_fields = _VespaPutFields(
        boost=boost_update,
        document_sets=document_sets_update,
        access_control_list=access_update,
        hidden=hidden_update,
        user_project=user_projects_update,
    )

    vespa_put_request = _VespaPutRequest(
        fields=vespa_put_fields,
    )

    vespa_url = (
        f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{doc_chunk_id}"
        "?create=true"
    )

    try:
        resp = http_client.put(
            vespa_url,
            headers={"Content-Type": "application/json"},
            json=vespa_put_request.model_dump(
                exclude_none=True
            ),  # NOTE: Important to not produce null fields in the json.
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Failed to update doc chunk {doc_chunk_id} (doc_id={doc_id}). "
            f"Code: {e.response.status_code}. Details: {e.response.text}"
        )
        # Re-raise so the @retry decorator will catch and retry, unless the
        # status code is < 5xx, in which case wrap the exception in something
        # other than an HTTPError to skip retries.
        if e.response.status_code >= 500:
            raise
        raise RuntimeError(
            f"Non-retryable error updating chunk {doc_chunk_id}: {e}"
        ) from e


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
        ), "Bug: Doc ID to chunk maps have different lengths."

        # Vespa has restrictions on valid characters, yet document IDs come from
        # external w.r.t. this class. We need to sanitize them.
        cleaned_chunks: list[DocMetadataAwareIndexChunk] = [
            clean_chunk_id_copy(chunk) for chunk in chunks
        ]
        assert len(cleaned_chunks) == len(
            chunks
        ), "Bug: Cleaned chunks and input chunks have different lengths."

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
                # TODO(andrei), WARNING: Don't we need to sanitize these doc IDs?
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
                tenant_id=self._tenant_id,
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

    def delete(self, document_id: str, chunk_count: int | None = None) -> int:
        total_chunks_deleted = 0

        sanitized_doc_id = replace_invalid_doc_id_characters(document_id)

        with (
            concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as executor,
            self._httpx_client_context as http_client,
        ):
            enriched_doc_info = _enrich_basic_chunk_info(
                index_name=self._index_name,
                http_client=http_client,
                document_id=sanitized_doc_id,
                previous_chunk_count=chunk_count,
                new_chunk_count=0,
            )
            chunks_to_delete = get_document_chunk_ids(
                enriched_document_info_list=[enriched_doc_info],
                tenant_id=self._tenant_id,
                large_chunks_enabled=self._large_chunks_enabled,
            )

            for doc_chunk_ids_batch in batch_generator(chunks_to_delete, BATCH_SIZE):
                total_chunks_deleted += len(doc_chunk_ids_batch)
                delete_vespa_chunks(
                    doc_chunk_ids=doc_chunk_ids_batch,
                    index_name=self._index_name,
                    http_client=http_client,
                    executor=executor,
                )

        return total_chunks_deleted

    def update(
        self,
        update_requests: list[MetadataUpdateRequest],
    ) -> None:
        # WARNING: This method can be called by vespa_metadata_sync_task, which
        # is kicked off by check_for_vespa_sync_task, notably before a document
        # has finished indexing. In this way, chunk_count below could be unknown
        # even for chunks not on the "old" chunk ID system; i.e. there could be
        # a race condition. Passing in None to _enrich_basic_chunk_info should
        # handle this, but a higher level TODO might be to not run update at all
        # on connectors that are still indexing, and therefore do not yet have a
        # chunk count because update_docs_chunk_count__no_commit has not been
        # run yet.
        with self._httpx_client_context as httpx_client:
            # Each invocation of this method can contain multiple update requests.
            for update_request in update_requests:
                # Each update request can correspond to multiple documents.
                for doc_id in update_request.document_ids:
                    # NOTE: -1 represents an unknown chunk count.
                    chunk_count = update_request.doc_id_to_chunk_cnt[doc_id]
                    sanitized_doc_id = replace_invalid_doc_id_characters(doc_id)
                    enriched_doc_info = _enrich_basic_chunk_info(
                        index_name=self._index_name,
                        http_client=httpx_client,
                        document_id=sanitized_doc_id,
                        previous_chunk_count=chunk_count if chunk_count >= 0 else None,
                        new_chunk_count=0,  # WARNING: This semantically makes no sense and is misusing this function.
                    )

                    doc_chunk_ids = get_document_chunk_ids(
                        enriched_document_info_list=[enriched_doc_info],
                        tenant_id=self._tenant_id,
                        large_chunks_enabled=self._large_chunks_enabled,
                    )

                    for doc_chunk_id in doc_chunk_ids:
                        _update_single_chunk(
                            doc_chunk_id,
                            self._index_name,
                            # NOTE: Used only for logging, raw ID is ok here.
                            doc_id,
                            httpx_client,
                            update_request,
                        )

                    logger.info(
                        f"Updated {len(doc_chunk_ids)} chunks for document {doc_id}."
                    )

    def id_based_retrieval(
        self,
        chunk_requests: list[DocumentSectionRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
    ) -> list[InferenceChunk]:
        sanitized_chunk_requests = [
            VespaChunkRequest(
                document_id=replace_invalid_doc_id_characters(
                    chunk_request.document_id
                ),
                min_chunk_ind=chunk_request.min_chunk_ind,
                max_chunk_ind=chunk_request.max_chunk_ind,
            )
            for chunk_request in chunk_requests
        ]

        if batch_retrieval:
            return _cleanup_chunks(
                batch_search_api_retrieval(
                    index_name=self._index_name,
                    chunk_requests=sanitized_chunk_requests,
                    filters=filters,
                    # No one was passing in this parameter in the legacy
                    # interface, it always defaulted to False.
                    get_large_chunks=False,
                )
            )
        return _cleanup_chunks(
            parallel_visit_api_retrieval(
                index_name=self._index_name,
                chunk_requests=sanitized_chunk_requests,
                filters=filters,
                # No one was passing in this parameter in the legacy interface,
                # it always defaulted to False.
                get_large_chunks=False,
            )
        )

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
        vespa_where_clauses = build_vespa_filters(filters)
        # Needs to be at least as much as the rerank-count value set in the
        # Vespa schema config. Otherwise we would be getting fewer results than
        # expected for reranking.
        target_hits = max(10 * num_to_retrieve, RERANK_COUNT)

        yql = (
            YQL_BASE.format(index_name=self._index_name)
            + vespa_where_clauses
            + f"(({{targetHits: {target_hits}}}nearestNeighbor(embeddings, query_embedding)) "
            + f"or ({{targetHits: {target_hits}}}nearestNeighbor(title_embedding, query_embedding)) "
            + 'or ({grammar: "weakAnd"}userInput(@query)) '
            + f'or ({{defaultIndex: "{CONTENT_SUMMARY}"}}userInput(@query)))'
        )

        final_query = " ".join(final_keywords) if final_keywords else query

        ranking_profile = (
            f"hybrid_search_{query_type.value}_base_{len(query_embedding)}"
        )

        logger.info(f"Selected ranking profile: {ranking_profile}")

        logger.debug(f"Query YQL: {yql}")

        # In this interface we do not pass in hybrid alpha. Tracing the codepath
        # of the legacy Vespa interface, it so happens that KEYWORD always
        # corresponds to an alpha of 0.2 (from KEYWORD_QUERY_HYBRID_ALPHA), and
        # SEMANTIC to 0.5 (from HYBRID_ALPHA). HYBRID_ALPHA_KEYWORD was only
        # used in dead code so we do not use it here.
        hybrid_alpha = (
            KEYWORD_QUERY_HYBRID_ALPHA
            if query_type == QueryType.KEYWORD
            else HYBRID_ALPHA
        )

        params: dict[str, str | int | float] = {
            "yql": yql,
            "query": final_query,
            "input.query(query_embedding)": str(query_embedding),
            "input.query(decay_factor)": str(DOC_TIME_DECAY * RECENCY_BIAS_MULTIPLIER),
            "input.query(alpha)": hybrid_alpha,
            "input.query(title_content_ratio)": TITLE_CONTENT_RATIO,
            "hits": num_to_retrieve,
            "offset": offset,
            "ranking.profile": ranking_profile,
            "timeout": VESPA_TIMEOUT,
        }

        return _cleanup_chunks(query_vespa(params))

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 100,
        dirty: bool | None = None,
    ) -> list[InferenceChunk]:
        vespa_where_clauses = build_vespa_filters(filters, remove_trailing_and=True)

        yql = YQL_BASE.format(index_name=self._index_name) + vespa_where_clauses

        random_seed = random.randint(0, 1_000_000)

        params: dict[str, str | int | float] = {
            "yql": yql,
            "hits": num_to_retrieve,
            "timeout": VESPA_TIMEOUT,
            "ranking.profile": "random_",
            "ranking.properties.random.seed": random_seed,
        }

        return _cleanup_chunks(query_vespa(params))
