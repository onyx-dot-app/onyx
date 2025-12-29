import logging
import time
from datetime import datetime
from typing import Any

import httpx

from onyx.configs.app_configs import BLURB_SIZE
from onyx.configs.app_configs import RERANK_COUNT
from onyx.configs.chat_configs import TITLE_CONTENT_RATIO
from onyx.configs.constants import INDEX_SEPARATOR
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.context.search.models import QueryExpansionType
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.interfaces import DocumentIndex as OldDocumentIndex
from onyx.document_index.interfaces import (
    DocumentInsertionRecord as OldDocumentInsertionRecord,
)
from onyx.document_index.interfaces import IndexBatchParams
from onyx.document_index.interfaces import UpdateRequest
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.interfaces import VespaDocumentFields
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.interfaces_new import DocumentInsertionRecord
from onyx.document_index.interfaces_new import DocumentSectionRequest
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import NORMALIZATION_PIPELINE_ZSCORE
from onyx.document_index.opensearch.client import NORMALIZATION_PIPELINE_ZSCORE_NAME
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import DocumentSchema
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.utils.logger import setup_logger
from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE
from shared_configs.model_server_models import Embedding


logger = setup_logger(__name__)
# Set the logging level to WARNING to ignore INFO and DEBUG logs from httpx. By
# default it emits INFO-level logs for every request.
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)


def _perform_hybrid_search(
    os_client: OpenSearchClient,
    query_text: str,
    query_vector: list[float],
    k: int,
    num_candidates: int,
    search_pipeline: str,
) -> dict[str, Any]:
    hybrid_query = {
        "hybrid": {
            "queries": [
                # Title vector search
                {
                    "knn": {
                        "title_vector": {"vector": query_vector, "k": num_candidates}
                    }
                },
                # Content vector search
                {
                    "knn": {
                        "content_vector": {"vector": query_vector, "k": num_candidates}
                    }
                },
                # Title keyword search
                {
                    "multi_match": {
                        "query": query_text,
                        "fields": ["title^2", "title.keyword"],
                        "type": "best_fields",
                    }
                },
                # Content keyword search
                {"match": {"content": {"query": query_text}}},
                # Phrase matching for exact phrases
                {"match_phrase": {"content": {"query": query_text, "boost": 1.5}}},
            ]
        }
    }

    search_body = {
        "query": hybrid_query,
        "size": k,
    }

    return os_client.search(search_body, search_pipeline=search_pipeline)


def _opensearch_hit_to_inference_chunk(
    hit: dict[str, Any], null_score: bool = False
) -> InferenceChunkUncleaned:
    logger.info(f"[OPENSEARCH HIT DEBUG][ANDREI]: Hit keys: {hit.keys()}")
    logger.info(f"[OPENSEARCH HIT DEBUG][ANDREI]: Hit _score: {hit.get('_score')}")
    logger.info(f"[OPENSEARCH HIT DEBUG][ANDREI]: Hit _id: {hit.get('_id')}")

    if "_source" in hit:
        source = hit["_source"]
        logger.info(f"[OPENSEARCH HIT DEBUG][ANDREI]: _source keys: {source.keys()}")
        logger.info(
            f"[OPENSEARCH HIT DEBUG][ANDREI]: _source sample: {dict(list(source.items())[:3])}"
        )
    else:
        logger.error(
            f"[OPENSEARCH HIT DEBUG][ANDREI]: No _source in hit! Full hit structure: {hit}"
        )
        raise KeyError(
            "Expected '_source' key in OpenSearch hit but it was not present"
        )

    # Parse metadata from list format (key:::value) to dict.
    metadata_dict: dict[str, str | list[str]] = {}
    if source.get("metadata"):
        for item in source["metadata"]:
            if INDEX_SEPARATOR in item:
                key, value = item.split(INDEX_SEPARATOR, 1)
                if key in metadata_dict:
                    # Convert to list if multiple values.
                    if isinstance(metadata_dict[key], list):
                        metadata_dict[key].append(value)  # type: ignore
                    else:
                        metadata_dict[key] = [metadata_dict[key], value]  # type: ignore
                else:
                    metadata_dict[key] = value

    # Parse datetime if present.
    updated_at = None
    if source.get("last_updated"):
        try:
            updated_at = datetime.fromisoformat(
                source["last_updated"].replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            pass

    # OpenSearch doesn't provide dynamic summaries like Vespa, so use content as
    # highlight.
    match_highlights = [source.get("content", "")[:400]]

    return InferenceChunkUncleaned(
        chunk_id=source["chunk_index"],
        blurb=source.get("content", "")[:BLURB_SIZE],
        content=source["content"],
        source_links={0: ""},  # OpenSearch doesn't store source_links.
        section_continuation=False,  # Not stored in OpenSearch.
        document_id=source["document_id"],
        source_type=source["source_type"],
        image_file_id=None,  # Not stored in OpenSearch.
        title=source.get("title"),
        semantic_identifier=source[
            "document_id"
        ],  # Using doc_id as semantic_identifier.
        boost=int(source.get("global_boost", 1)),
        recency_bias=1.0,  # Default value.
        score=None if null_score else hit.get("_score", 0),
        hidden=False,  # Not stored in OpenSearch.
        primary_owners=None,  # Not stored in OpenSearch.
        secondary_owners=None,  # Not stored in OpenSearch.
        large_chunk_reference_ids=[],  # Not stored in OpenSearch.
        metadata=metadata_dict,
        metadata_suffix=None,  # Will need to extract from content.
        doc_summary="",  # Not stored separately in OpenSearch.
        chunk_context="",  # Not stored separately in OpenSearch.
        match_highlights=match_highlights,
        updated_at=updated_at,
    )


def _cleanup_opensearch_chunks(
    chunks: list[InferenceChunkUncleaned],
) -> list[InferenceChunk]:
    """Clean up chunks by removing indexing-time augmentations.

    For OpenSearch, the content field contains the full augmented content.
    We don't have the individual components stored separately, so we'll
    just pass through for now and rely on the content as-is.
    """
    # For now, just convert to InferenceChunk without cleaning.
    # In the future, we could store metadata_suffix separately to enable proper
    # cleanup.
    return [chunk.to_inference_chunk() for chunk in chunks]


class OpenSearchOldDocumentIndex(OldDocumentIndex):
    """
    Wrapper for OpenSearch to adapt the new DocumentIndex interface with
    invocations to the old DocumentIndex interface in the hotpath.

    The analogous class for Vespa is VespaIndex which calls to
    VespaDocumentIndex.

    TODO(andrei): This is purely temporary until there are no more references to
    the old interface in hotpath.
    """

    def __init__(
        self,
        index_name: str,
        secondary_index_name: str | None,
        large_chunks_enabled: bool,
        secondary_large_chunks_enabled: bool | None,
        multitenant: bool = False,
        httpx_client: httpx.Client | None = None,
    ) -> None:
        # Initialize parent with index names
        super().__init__(
            index_name=index_name,
            secondary_index_name=secondary_index_name,
        )

        #    httpx_client = httpx.Client(
        #         cert=(
        #             cast(tuple[str, str], (VESPA_CLOUD_CERT_PATH, VESPA_CLOUD_KEY_PATH))
        #             if MANAGED_VESPA
        #             else None
        #         ),
        #         verify=False if not MANAGED_VESPA else True,
        #         timeout=None if no_timeout else VESPA_REQUEST_TIMEOUT,
        #         http2=http2,
        #     )
        self._real_index = OpenSearchDocumentIndex(
            index_name=index_name,
            tenant_state=TenantState(tenant_id="", multitenant=multitenant),
            # httpx_client=httpx_client,
        )

    @staticmethod
    def register_multitenant_indices(
        indices: list[str],
        embedding_dims: list[int],
        embedding_precisions: list[EmbeddingPrecision],
    ) -> None:
        raise NotImplementedError(
            "[ANDREI]: Multitenant index registration is not implemented for OpenSearch."
        )

    def ensure_indices_exist(
        self,
        primary_embedding_dim: int,
        primary_embedding_precision: EmbeddingPrecision,
        secondary_index_embedding_dim: int | None,
        secondary_index_embedding_precision: EmbeddingPrecision | None,
    ) -> None:
        # Only handle primary index for now, ignore secondary.
        return self._real_index.verify_and_create_index_if_necessary(
            primary_embedding_dim, primary_embedding_precision
        )

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        index_batch_params: IndexBatchParams,
    ) -> set[OldDocumentInsertionRecord]:
        # Convert IndexBatchParams to IndexingMetadata.
        chunk_counts: dict[str, IndexingMetadata.ChunkCounts] = {}
        for doc_id in index_batch_params.doc_id_to_new_chunk_cnt:
            old_count = index_batch_params.doc_id_to_previous_chunk_cnt.get(doc_id, 0)
            new_count = index_batch_params.doc_id_to_new_chunk_cnt[doc_id]
            chunk_counts[doc_id] = IndexingMetadata.ChunkCounts(
                old_chunk_cnt=old_count,
                new_chunk_cnt=new_count,
            )

        indexing_metadata = IndexingMetadata(doc_id_to_chunk_cnt_diff=chunk_counts)

        results = self._real_index.index(chunks, indexing_metadata)

        # Convert list[DocumentInsertionRecord] to set[OldDocumentInsertionRecord]
        return {
            OldDocumentInsertionRecord(
                document_id=record.document_id,
                already_existed=record.already_existed,
            )
            for record in results
        }

    def delete_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        chunk_count: int | None,
    ) -> int:
        return self._real_index.delete(doc_id, chunk_count)

    def update_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        chunk_count: int | None,
        fields: VespaDocumentFields | None,
        user_fields: VespaDocumentUserFields | None,
    ) -> None:
        if fields is None and user_fields is None:
            raise ValueError(
                f"Bug: Tried to update document {doc_id} with no updated fields or user fields."
            )

        # Convert VespaDocumentFields to MetadataUpdateRequest.
        update_request = MetadataUpdateRequest(
            document_ids=[doc_id],
            doc_id_to_chunk_cnt={
                doc_id: chunk_count if chunk_count is not None else -1
            },
            access=fields.access if fields else None,
            document_sets=fields.document_sets if fields else None,
            boost=fields.boost if fields else None,
            hidden=fields.hidden if fields else None,
            project_ids=(
                set(user_fields.user_projects)
                if user_fields and user_fields.user_projects
                else None
            ),
        )

        return self._real_index.update([update_request], old_doc_id_to_new_doc_id={})

    def update(
        self,
        update_requests: list[UpdateRequest],
        *,
        tenant_id: str,
    ) -> None:
        raise NotImplementedError("[ANDREI]: Update is not implemented for OpenSearch.")

    def id_based_retrieval(
        self,
        chunk_requests: list[VespaChunkRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
        get_large_chunks: bool = False,
    ) -> list[InferenceChunk]:
        # Convert VespaChunkRequest to DocumentSectionRequest.
        section_requests = [
            DocumentSectionRequest(
                document_id=req.document_id,
                min_chunk_ind=req.min_chunk_ind,
                max_chunk_ind=req.max_chunk_ind,
            )
            for req in chunk_requests
        ]

        return self._real_index.id_based_retrieval(
            section_requests, filters, batch_retrieval
        )

    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        filters: IndexFilters,
        hybrid_alpha: float,
        time_decay_multiplier: float,
        num_to_retrieve: int,
        ranking_profile_type: QueryExpansionType = QueryExpansionType.SEMANTIC,
        offset: int = 0,
        title_content_ratio: float | None = TITLE_CONTENT_RATIO,
    ) -> list[InferenceChunk]:
        # The new interface doesn't use hybrid_alpha, time_decay_multiplier,
        # ranking_profile_type, or title_content_ratio - they're handled
        # internally by OpenSearch's normalization pipeline.

        # Determine query type based on hybrid_alpha.
        if hybrid_alpha >= 0.8:
            query_type = QueryType.SEMANTIC
        elif hybrid_alpha <= 0.2:
            query_type = QueryType.KEYWORD
        else:
            query_type = QueryType.SEMANTIC  # Default to semantic for hybrid.

        return self._real_index.hybrid_retrieval(
            query=query,
            query_embedding=query_embedding,
            final_keywords=final_keywords,
            query_type=query_type,
            filters=filters,
            num_to_retrieve=num_to_retrieve,
            offset=offset,
        )

    def admin_retrieval(
        self,
        query: str,
        filters: IndexFilters,
        num_to_retrieve: int,
        offset: int = 0,
    ) -> list[InferenceChunk]:
        raise NotImplementedError(
            "[ANDREI]: Admin retrieval is not implemented for OpenSearch."
        )

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 100,
    ) -> list[InferenceChunk]:
        return self._real_index.random_retrieval(
            filters=filters,
            num_to_retrieve=num_to_retrieve,
            dirty=None,
        )


def _convert_onyx_chunk_to_opensearch_chunk(
    chunk: DocMetadataAwareIndexChunk,
    # tokenizer: BaseTokenizer,  # You'll need this for token counting
) -> DocumentChunk:
    document = chunk.source_document

    # Get the title - may be None
    title = document.get_title_for_document_index()

    # Count tokens in the content
    # The content includes title_prefix, doc_summary, content, chunk_context, and metadata_suffix
    full_content = (
        f"{chunk.title_prefix}"
        f"{chunk.doc_summary}"
        f"{chunk.content}"
        f"{chunk.chunk_context}"
        f"{chunk.metadata_suffix_keyword}"
    )
    # num_tokens = len(tokenizer.encode(full_content))

    # Convert document sets from set to list
    document_sets_list = list(chunk.document_sets) if chunk.document_sets else None

    # Convert access control list
    access_control_list = list(chunk.access.to_acl()) if chunk.access else None

    # Get metadata as list of strings (key:::value format)
    metadata_list = document.get_metadata_str_attributes()

    return DocumentChunk(
        doc_id=document.id,
        chunk_index=chunk.chunk_id,  # chunk_id is the chunk index
        chunk_size=DOC_EMBEDDING_CONTEXT_SIZE,  # From shared_configs.configs (512)
        title=title,
        content=full_content,  # Full content with all parts
        title_vector=chunk.title_embedding,  # May be None
        content_vector=chunk.embeddings.full_embedding,
        num_tokens=0,  # ???
        source_type=str(document.source.value),  # e.g., "web", "slack", etc.
        document_sets=document_sets_list,
        metadata=metadata_list,
        last_updated=document.doc_updated_at,
        created_at=None,  # Not available in DocMetadataAwareIndexChunk
        access_control_list=access_control_list,
        global_boost=float(chunk.boost),  # Convert int to float
    )


class OpenSearchDocumentIndex(DocumentIndex):
    """OpenSearch-specific implementation of the DocumentIndex interface.

    This class provides document indexing, retrieval, and management operations
    for an OpenSearch search engine instance. It handles the complete lifecycle
    of document chunks within a specific OpenSearch index/schema.
    """

    def __init__(
        self,
        index_name: str,
        tenant_state: TenantState,
    ) -> None:
        logger.info(
            f"[ANDREI]: Initializing OpenSearchDocumentIndex for index {index_name}..."
        )
        self._index_name = index_name
        self._tenant_id = tenant_state.tenant_id
        self._multitenant = tenant_state.multitenant
        if self._multitenant:
            assert (
                self._tenant_id
            ), "Bug: Must supply a tenant id if in multitenant mode."
        # TODO(andrei): Shouldn't this be index_name?
        # self._os_client = OpenSearchClient(index_name=OS_INDEX_NAME)
        self._os_client = OpenSearchClient(index_name=self._index_name)

    def verify_and_create_index_if_necessary(
        self, embedding_dim: int, embedding_precision: EmbeddingPrecision
    ) -> None:
        logger.info(f"[ANDREI]: Verifying index with embedding_dim={embedding_dim}...")
        start_time = time.perf_counter_ns()
        opensearch_schema = DocumentSchema()
        document_schema = opensearch_schema.get_document_schema(
            vector_dimension=embedding_dim
        )
        index_settings = opensearch_schema.get_index_settings()

        # Delete the existing index if it exists to start fresh.
        # TODO(andrei): We do not want this in the hotpath, this is a remnant
        # from testing.
        self._os_client.delete_index()

        self._os_client.create_index(mappings=document_schema, settings=index_settings)

        # Create the search pipeline.
        # TODO(andrei): I assume this wipes? Also what is a search pipeline?
        self._os_client.create_search_pipeline()
        self._os_client.create_search_pipeline(
            pipeline_body=NORMALIZATION_PIPELINE_ZSCORE,
            pipeline_id=NORMALIZATION_PIPELINE_ZSCORE_NAME,
        )
        end_time = time.perf_counter_ns()
        logger.info(
            f"[ANDREI]: Index creation took {(end_time - start_time) / 1_000_000} ms."
        )

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        indexing_metadata: IndexingMetadata,
    ) -> list[DocumentInsertionRecord]:
        logger.info("[ANDREI]: Indexing...")
        start_time = time.perf_counter_ns()
        indexed_doc_ids: set[str] = set()

        for chunk in chunks:
            document = _convert_onyx_chunk_to_opensearch_chunk(chunk)
            self._os_client.index_document(
                document.get_opensearch_doc_chunk_id(), document
            )
            indexed_doc_ids.add(document.doc_id)
            logger.info(
                f"[ANDREI]: Indexed chunk {document.chunk_index} of document {document.doc_id}"
            )

        logger.info("[ANDREI]: Indexing complete.")
        end_time = time.perf_counter_ns()
        logger.info(
            f"[ANDREI]: Indexing took {(end_time - start_time) / 1_000_000} ms."
        )
        # Create DocumentInsertionRecord for each unique document.
        # A document "already existed" if it had chunks before (old_chunk_cnt > 0)
        results: list[DocumentInsertionRecord] = []
        for doc_id in indexed_doc_ids:
            chunk_counts = indexing_metadata.doc_id_to_chunk_cnt_diff.get(doc_id)
            already_existed = chunk_counts.old_chunk_cnt > 0 if chunk_counts else False

            results.append(
                DocumentInsertionRecord(
                    document_id=doc_id,
                    already_existed=already_existed,
                )
            )

        return results

    def delete(self, document_id: str, chunk_count: int | None = None) -> int:
        raise NotImplementedError(
            "[ANDREI]: Deletion is not implemented for OpenSearch."
        )

    def update(
        self,
        update_requests: list[MetadataUpdateRequest],
        # TODO(andrei), WARNING: Very temporary, this is not the interface we want
        # in Updatable, we only have this to continue supporting
        # user_file_docid_migration_task for Vespa which should be done soon.
        old_doc_id_to_new_doc_id: dict[str, str],
    ) -> None:
        logger.info("[ANDREI]: Updating documents...")

        for request in update_requests:
            for doc_id in request.document_ids:
                request.doc_id_to_chunk_cnt.get(doc_id, -1)

                # Build the update payload with only non-None fields
                update_doc: dict[str, Any] = {}

                if request.access is not None:
                    update_doc["access_control_list"] = list(request.access.to_acl())

                if request.document_sets is not None:
                    update_doc["document_sets"] = list(request.document_sets)

                if request.boost is not None:
                    update_doc["global_boost"] = float(request.boost)

                # NOTE: 'hidden' and 'secondary_index_updated' aren't stored in
                # our schema. 'project_ids' would need to be added to schema if
                # needed.

                if not update_doc:
                    continue  # Nothing to update.

                logger.info(
                    f"[ANDREI]: Updating document {doc_id} with update_doc: {update_doc}"
                )
                # TODO(andrei): Idk how to update in opensearch so do nothing for now.

    def id_based_retrieval(
        self,
        chunk_requests: list[DocumentSectionRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
    ) -> list[InferenceChunk]:
        logger.info(
            f"[ANDREI]: Retrieving chunks for {len(chunk_requests)} documents..."
        )
        start_time = time.perf_counter_ns()
        all_chunks: list[InferenceChunk] = []

        for request in chunk_requests:
            doc_id = request.document_id
            min_chunk = request.min_chunk_ind
            max_chunk = request.max_chunk_ind

            # Build the query to fetch chunks for this document.
            must_clauses: list[dict[str, Any]] = [{"term": {"document_id": doc_id}}]

            # Add chunk index range filters if specified
            if min_chunk is not None or max_chunk is not None:
                range_query: dict[str, Any] = {}
                if min_chunk is not None:
                    range_query["gte"] = min_chunk
                if max_chunk is not None:
                    range_query["lte"] = max_chunk

                must_clauses.append({"range": {"chunk_index": range_query}})

            search_body = {
                "query": {"bool": {"must": must_clauses}},
                "size": 10000,  # Max chunks to retrieve.
                "sort": [{"chunk_index": "asc"}],  # Ensure proper ordering.
            }

            try:
                response = self._os_client.search(body=search_body)

                hits = response.get("hits", {}).get("hits", [])

                # Convert hits to InferenceChunk objects.
                for hit in hits:
                    try:
                        chunk = _opensearch_hit_to_inference_chunk(hit)
                        all_chunks.append(chunk.to_inference_chunk())
                    except Exception as e:
                        logger.exception(
                            f"[ANDREI]: Failed to convert hit to chunk for doc {doc_id}: {e}"
                        )

            except Exception as e:
                logger.exception(
                    f"[ANDREI]: Failed to retrieve chunks for document {doc_id}: {e}"
                )

        end_time = time.perf_counter_ns()
        logger.info(
            f"[ANDREI]: Retrieval took {(end_time - start_time) / 1_000_000} ms."
        )
        return all_chunks

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
        start_time = time.perf_counter_ns()
        # Use final_keywords if provided, otherwise use the original query
        final_query = " ".join(final_keywords) if final_keywords else query

        # Calculate number of candidates for KNN search.
        # Similar to Vespa's approach: at least 10x the requested results,
        # minimum RERANK_COUNT.
        # TODO(andrei): No.
        num_candidates = max(10 * num_to_retrieve, RERANK_COUNT)

        logger.info(
            f"[ANDREI]: OpenSearch hybrid retrieval: query='{final_query}', "
            f"num_to_retrieve={num_to_retrieve}, num_candidates={num_candidates}"
        )

        response = _perform_hybrid_search(
            os_client=self._os_client,
            query_text=final_query,
            query_vector=query_embedding,
            k=num_to_retrieve,
            num_candidates=num_candidates,
            search_pipeline=NORMALIZATION_PIPELINE_ZSCORE_NAME,
        )
        end_time = time.perf_counter_ns()
        logger.info(
            f"[ANDREI]: Hybrid retrieval took {(end_time - start_time) / 1_000_000} ms."
        )
        logger.info(
            f"[OPENSEARCH RESPONSE DEBUG][ANDREI]: Response keys: {response.keys()}"
        )
        logger.info(
            f"[OPENSEARCH RESPONSE DEBUG][ANDREI]: Hits structure: {response.get('hits', {}).keys()}"
        )
        logger.info(
            f"[OPENSEARCH RESPONSE DEBUG][ANDREI]: Total hits: {response.get('hits', {}).get('total')}"
        )

        # Extract hits from response
        hits = response.get("hits", {}).get("hits", [])

        logger.info(
            f"[ANDREI]: OpenSearch returned {len(hits)} hits for query: '{final_query[:50]}...'"
        )

        if hits:
            logger.info(
                f"[OPENSEARCH RESPONSE DEBUG][ANDREI]: First hit structure (full): {hits[0]}"
            )

        # Convert OpenSearch hits to InferenceChunkUncleaned.
        uncleaned_chunks = [_opensearch_hit_to_inference_chunk(hit) for hit in hits]

        # Clean up the chunks (remove indexing-time augmentations).
        cleaned_chunks = _cleanup_opensearch_chunks(uncleaned_chunks)

        # TODO(andrei): Apply filters (access control, document sets, etc.)

        return cleaned_chunks

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 100,
        dirty: bool | None = None,
    ) -> list[InferenceChunk]:
        raise NotImplementedError(
            "[ANDREI]: Random retrieval is not implemented for OpenSearch."
        )
