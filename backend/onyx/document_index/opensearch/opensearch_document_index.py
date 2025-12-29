import logging
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
from onyx.document_index.opensearch.client import SEARCH_PIPELINE_NAME
from onyx.document_index.opensearch.constants import OS_INDEX_NAME
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


def hybrid_search(
    os_client: OpenSearchClient,
    query_text: str,
    query_vector: list[float],
    k: int = 50,
    num_candidates: int = 500,
    search_pipeline: str | None = SEARCH_PIPELINE_NAME,
) -> dict:
    """
    Perform hybrid search combining keyword and vector searches.

    Args:
        os_client: OpenSearch client instance
        query_text: Text query for keyword search
        query_vector: Embedding vector for similarity
        k: Number of results to return
        num_candidates: Number of candidates for KNN search

    Returns:
        OpenSearch response dictionary
    """

    # Build the hybrid query
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

    # Prepare search body with the hybrid query
    search_body = {
        "query": hybrid_query,
        "size": k,
    }

    return os_client.search(search_body, search_pipeline=search_pipeline)


def _opensearch_hit_to_inference_chunk(
    hit: dict[str, Any], null_score: bool = False
) -> InferenceChunkUncleaned:
    """Convert an OpenSearch hit to an InferenceChunkUncleaned object."""
    logger.debug(f"[OPENSEARCH HIT DEBUG] Hit keys: {hit.keys()}")
    logger.debug(f"[OPENSEARCH HIT DEBUG] Hit _score: {hit.get('_score')}")
    logger.debug(f"[OPENSEARCH HIT DEBUG] Hit _id: {hit.get('_id')}")

    if "_source" in hit:
        source = hit["_source"]
        logger.debug(f"[OPENSEARCH HIT DEBUG] _source keys: {source.keys()}")
        logger.debug(
            f"[OPENSEARCH HIT DEBUG] _source sample: {dict(list(source.items())[:3])}"
        )
    else:
        logger.error(
            f"[OPENSEARCH HIT DEBUG] No _source in hit! Full hit structure: {hit}"
        )
        raise KeyError(
            "Expected '_source' key in OpenSearch hit but it was not present"
        )

    # Parse metadata from list format (key:::value) to dict
    metadata_dict: dict[str, str | list[str]] = {}
    if source.get("metadata"):
        for item in source["metadata"]:
            if INDEX_SEPARATOR in item:
                key, value = item.split(INDEX_SEPARATOR, 1)
                if key in metadata_dict:
                    # Convert to list if multiple values
                    if isinstance(metadata_dict[key], list):
                        metadata_dict[key].append(value)  # type: ignore
                    else:
                        metadata_dict[key] = [metadata_dict[key], value]  # type: ignore
                else:
                    metadata_dict[key] = value

    # Parse datetime if present
    updated_at = None
    if source.get("last_updated"):
        try:
            updated_at = datetime.fromisoformat(
                source["last_updated"].replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            pass

    # OpenSearch doesn't provide dynamic summaries like Vespa, so use content as highlight
    match_highlights = [source.get("content", "")[:400]]

    return InferenceChunkUncleaned(
        chunk_id=source["chunk_index"],
        blurb=source.get("content", "")[:BLURB_SIZE],
        content=source["content"],
        source_links={0: ""},  # OpenSearch doesn't store source_links
        section_continuation=False,  # Not stored in OpenSearch
        document_id=source["document_id"],
        source_type=source["source_type"],
        image_file_id=None,  # Not stored in OpenSearch
        title=source.get("title"),
        semantic_identifier=source[
            "document_id"
        ],  # Using doc_id as semantic_identifier
        boost=int(source.get("global_boost", 1)),
        recency_bias=1.0,  # Default value
        score=None if null_score else hit.get("_score", 0),
        hidden=False,  # Not stored in OpenSearch
        primary_owners=None,  # Not stored in OpenSearch
        secondary_owners=None,  # Not stored in OpenSearch
        large_chunk_reference_ids=[],  # Not stored in OpenSearch
        metadata=metadata_dict,
        metadata_suffix=None,  # Will need to extract from content
        doc_summary="",  # Not stored separately in OpenSearch
        chunk_context="",  # Not stored separately in OpenSearch
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
    # For now, just convert to InferenceChunk without cleaning
    # In the future, we could store metadata_suffix separately to enable proper cleanup
    return [chunk.to_inference_chunk() for chunk in chunks]


class OpenSearchOldDocumentIndex(OldDocumentIndex):
    """Wrapper to adapt the new OpenSearchDocumentIndex to the old DocumentIndex interface."""

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
        """Register multitenant indices. Not implemented for OpenSearch yet."""
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
        """Verify and create index if necessary."""
        # Only handle primary index for now, ignore secondary
        return self._real_index.verify_and_create_index_if_necessary(
            primary_embedding_dim, primary_embedding_precision
        )

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        index_batch_params: IndexBatchParams,
    ) -> set[OldDocumentInsertionRecord]:
        """Index document chunks. Converts new IndexingMetadata to old IndexBatchParams."""
        # Convert IndexBatchParams to IndexingMetadata
        chunk_counts: dict[str, IndexingMetadata.ChunkCounts] = {}
        for doc_id in index_batch_params.doc_id_to_new_chunk_cnt:
            old_count = index_batch_params.doc_id_to_previous_chunk_cnt.get(doc_id, 0)
            new_count = index_batch_params.doc_id_to_new_chunk_cnt[doc_id]
            chunk_counts[doc_id] = IndexingMetadata.ChunkCounts(
                old_chunk_cnt=old_count,
                new_chunk_cnt=new_count,
            )

        indexing_metadata = IndexingMetadata(doc_id_to_chunk_cnt_diff=chunk_counts)

        # Call the new interface
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
        """Delete a single document."""
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
        """Update a single document's metadata fields."""
        if fields is None and user_fields is None:
            return

        # Convert VespaDocumentFields to MetadataUpdateRequest
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

        self._real_index.update([update_request], old_doc_id_to_new_doc_id={})

    def update(
        self,
        update_requests: list[UpdateRequest],
        *,
        tenant_id: str,
    ) -> None:
        """Batch update documents' metadata fields."""
        # Convert old UpdateRequest list to new MetadataUpdateRequest list
        new_requests: list[MetadataUpdateRequest] = []
        for old_req in update_requests:
            doc_ids = [info.doc_id for info in old_req.minimal_document_indexing_info]
            doc_id_to_chunk_cnt = {
                info.doc_id: -1  # Unknown chunk count for old interface
                for info in old_req.minimal_document_indexing_info
            }

            new_req = MetadataUpdateRequest(
                document_ids=doc_ids,
                doc_id_to_chunk_cnt=doc_id_to_chunk_cnt,
                access=old_req.access,
                document_sets=old_req.document_sets,
                boost=old_req.boost,
                hidden=old_req.hidden,
            )
            new_requests.append(new_req)

        self._real_index.update(new_requests, old_doc_id_to_new_doc_id={})

    def id_based_retrieval(
        self,
        chunk_requests: list[VespaChunkRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
    ) -> list[InferenceChunk]:
        """Retrieve chunks by document ID."""
        # Convert VespaChunkRequest to DocumentSectionRequest
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
        ranking_profile_type: QueryExpansionType,
        offset: int = 0,
        title_content_ratio: float | None = TITLE_CONTENT_RATIO,
    ) -> list[InferenceChunk]:
        """Perform hybrid search."""
        # The new interface doesn't use hybrid_alpha, time_decay_multiplier,
        # ranking_profile_type, or title_content_ratio - they're handled internally
        # by OpenSearch's normalization pipeline

        # Determine query type based on hybrid_alpha
        if hybrid_alpha >= 0.9:
            query_type = QueryType.SEMANTIC
        elif hybrid_alpha <= 0.1:
            query_type = QueryType.KEYWORD
        else:
            query_type = QueryType.SEMANTIC  # Default to semantic for hybrid

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
        """Admin retrieval with emphasis on title matching."""
        # For admin retrieval, use keyword search with empty embedding
        # OpenSearch will emphasize title matching in the hybrid query
        embedding_dim = (
            self._real_index._embedding_dim or 768
        )  # Default to 768 if not set
        empty_embedding = [0.0] * embedding_dim

        return self._real_index.hybrid_retrieval(
            query=query,
            query_embedding=empty_embedding,
            final_keywords=[query],
            query_type=QueryType.KEYWORD,
            filters=filters,
            num_to_retrieve=num_to_retrieve,
            offset=offset,
        )

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 10,
    ) -> list[InferenceChunk]:
        """Retrieve random chunks."""
        return self._real_index.random_retrieval(
            filters=filters,
            num_to_retrieve=num_to_retrieve,
            dirty=None,
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
        # httpx_client: httpx.Client,
    ) -> None:
        self._index_name = index_name
        # self._httpx_client = httpx_client
        self._tenant_id = tenant_state.tenant_id
        self._multitenant = tenant_state.multitenant
        if self._multitenant:
            assert (
                self._tenant_id
            ), "Bug: Must supply a tenant id if in multitenant mode."
        self._os_client = OpenSearchClient(index_name=OS_INDEX_NAME)
        self._embedding_dim: int | None = None  # Will be set during index creation

    def verify_and_create_index_if_necessary(
        self, embedding_dim: int, embedding_precision: EmbeddingPrecision
    ) -> None:
        print(f"[ANDREI]: Verifying index with embedding_dim={embedding_dim}...")

        # Store the embedding dimension for later use
        self._embedding_dim = embedding_dim

        # Create the index with proper schema first.
        schema = DocumentSchema()
        mappings = schema.get_document_schema(vector_dimension=embedding_dim)
        settings = schema.get_index_settings()

        # Delete the existing index if it exists to start fresh.
        self._os_client.delete_index()

        # Create the index with the proper mappings.
        self._os_client.create_index(mappings, settings)

        # Create the search pipeline.
        # TODO(andrei): I assume this wipes?
        self._os_client.create_search_pipeline()
        self._os_client.create_search_pipeline(
            pipeline_body=NORMALIZATION_PIPELINE_ZSCORE,
            pipeline_id=NORMALIZATION_PIPELINE_ZSCORE_NAME,
        )

    def _convert_to_opensearch_chunk(
        self,
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

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        indexing_metadata: IndexingMetadata,
    ) -> list[DocumentInsertionRecord]:
        print("[ANDREI]: Indexing...")

        # Track unique document IDs that were indexed
        indexed_doc_ids: set[str] = set()

        for chunk in chunks:
            document = self._convert_to_opensearch_chunk(chunk)
            self._os_client.index_document(document.get_os_doc_id(), document)
            indexed_doc_ids.add(document.doc_id)
            print(
                f"[ANDREI]: Indexed chunk {document.chunk_index} of document {document.doc_id}"
            )

        print("[ANDREI]: Indexing complete.")

        # Create DocumentInsertionRecord for each unique document
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
        raise NotImplementedError("[ANDREI]: Update is not implemented for OpenSearch.")

    def id_based_retrieval(
        self,
        chunk_requests: list[DocumentSectionRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
    ) -> list[InferenceChunk]:
        raise NotImplementedError(
            "[ANDREI]: ID-based retrieval is not implemented for OpenSearch."
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
        """Perform hybrid search combining semantic and keyword search.

        Args:
            query: The search query string
            query_embedding: Vector embedding of the query
            final_keywords: Optional list of keywords to use instead of query
            query_type: Type of query (SEMANTIC, KEYWORD, etc.)
            filters: Filters to apply (access control, document sets, etc.)
            num_to_retrieve: Number of results to return
            offset: Offset for pagination

        Returns:
            List of InferenceChunk objects matching the query
        """
        # Use final_keywords if provided, otherwise use the original query
        final_query = " ".join(final_keywords) if final_keywords else query

        # Calculate number of candidates for KNN search
        # Similar to Vespa's approach: at least 10x the requested results, minimum RERANK_COUNT
        num_candidates = max(10 * num_to_retrieve, RERANK_COUNT)

        logger.debug(
            f"OpenSearch hybrid retrieval: query='{final_query}', "
            f"num_to_retrieve={num_to_retrieve}, num_candidates={num_candidates}"
        )

        # Perform the hybrid search using the helper function
        response = hybrid_search(
            os_client=self._os_client,
            query_text=final_query,
            query_vector=query_embedding,
            k=num_to_retrieve,
            num_candidates=num_candidates,
            search_pipeline=NORMALIZATION_PIPELINE_ZSCORE_NAME,
        )

        # Debug: Log the full response structure
        logger.debug(f"[OPENSEARCH RESPONSE DEBUG] Response keys: {response.keys()}")
        logger.debug(
            f"[OPENSEARCH RESPONSE DEBUG] Hits structure: {response.get('hits', {}).keys()}"
        )
        logger.debug(
            f"[OPENSEARCH RESPONSE DEBUG] Total hits: {response.get('hits', {}).get('total')}"
        )

        # Extract hits from response
        hits = response.get("hits", {}).get("hits", [])

        logger.info(
            f"OpenSearch returned {len(hits)} hits for query: '{final_query[:50]}...'"
        )

        if hits:
            logger.debug(
                f"[OPENSEARCH RESPONSE DEBUG] First hit structure (full): {hits[0]}"
            )

        # Convert OpenSearch hits to InferenceChunkUncleaned
        uncleaned_chunks = [_opensearch_hit_to_inference_chunk(hit) for hit in hits]

        # Clean up the chunks (remove indexing-time augmentations)
        cleaned_chunks = _cleanup_opensearch_chunks(uncleaned_chunks)

        # TODO(andrei): Apply filters (access control, document sets, etc.)
        # For now, we're not filtering - OpenSearch should handle this via query filters

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
