import json
from typing import Any

import httpx

from onyx.configs.chat_configs import TITLE_CONTENT_RATIO
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_experts_stores_representations,
)
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.context.search.models import QueryExpansionType
from onyx.db.enums import EmbeddingPrecision
from onyx.db.models import DocumentSource
from onyx.document_index.chunk_content_enrichment import cleanup_content_for_chunks
from onyx.document_index.chunk_content_enrichment import (
    generate_enriched_content_for_chunk,
)
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
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.schema import ACCESS_CONTROL_LIST_FIELD_NAME
from onyx.document_index.opensearch.schema import DOCUMENT_SETS_FIELD_NAME
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import DocumentSchema
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from onyx.document_index.opensearch.schema import GLOBAL_BOOST_FIELD_NAME
from onyx.document_index.opensearch.schema import HIDDEN_FIELD_NAME
from onyx.document_index.opensearch.schema import PROJECT_IDS_FIELD_NAME
from onyx.document_index.opensearch.search import DocumentQuery
from onyx.document_index.opensearch.search import (
    MIN_MAX_NORMALIZATION_PIPELINE_CONFIG,
)
from onyx.document_index.opensearch.search import (
    MIN_MAX_NORMALIZATION_PIPELINE_NAME,
)
from onyx.document_index.opensearch.search import (
    ZSCORE_NORMALIZATION_PIPELINE_CONFIG,
)
from onyx.document_index.opensearch.search import (
    ZSCORE_NORMALIZATION_PIPELINE_NAME,
)
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import Document
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.model_server_models import Embedding


logger = setup_logger(__name__)


def _convert_opensearch_chunk_to_inference_chunk_uncleaned(
    chunk: DocumentChunk,
) -> InferenceChunkUncleaned:
    return InferenceChunkUncleaned(
        chunk_id=chunk.chunk_index,
        blurb=chunk.blurb,
        content=chunk.content,
        source_links=json.loads(chunk.source_links) if chunk.source_links else None,
        image_file_id=chunk.image_file_id,
        # Deprecated. Fill in some reasonable default.
        section_continuation=False,
        document_id=chunk.document_id,
        source_type=DocumentSource(chunk.source_type),
        semantic_identifier=chunk.semantic_identifier,
        title=chunk.title,
        boost=chunk.global_boost,
        # TODO(andrei): Do in a followup. We should be able to get this from
        # OpenSearch.
        recency_bias=1.0,
        # TODO(andrei): This is how good the match is, we need this, key insight
        # is we can order chunks by this. Should not be hard to plumb this from
        # a search result, do that in a followup.
        score=None,
        hidden=chunk.hidden,
        metadata=json.loads(chunk.metadata),
        # TODO(andrei): The vector DB needs to supply this. I vaguely know
        # OpenSearch can from the documentation I've seen till now, look at this
        # in a followup.
        match_highlights=[],
        # TODO(andrei) Consider storing a chunk content index instead of a full
        # string when working on chunk content augmentation.
        doc_summary=chunk.doc_summary,
        # TODO(andrei) Same thing as contx ret above, LLM gens context for each
        # chunk.
        chunk_context=chunk.chunk_context,
        updated_at=chunk.last_updated,
        primary_owners=chunk.primary_owners,
        secondary_owners=chunk.secondary_owners,
        # TODO(andrei): This is the suffix appended to the end of the chunk
        # content to assist querying. There are better ways we can do this, for
        # ex. keeping an index of where to string split from.
        metadata_suffix=None,
    )


def _convert_onyx_chunk_to_opensearch_document(
    chunk: DocMetadataAwareIndexChunk,
) -> DocumentChunk:
    return DocumentChunk(
        document_id=chunk.source_document.id,
        chunk_index=chunk.chunk_id,
        title=chunk.source_document.title,
        title_vector=chunk.title_embedding,
        content=generate_enriched_content_for_chunk(chunk),
        content_vector=chunk.embeddings.full_embedding,
        source_type=chunk.source_document.source.value,
        metadata=json.dumps(chunk.source_document.metadata),
        last_updated=chunk.source_document.doc_updated_at,
        public=chunk.access.is_public,
        # TODO(andrei): When going over ACL look very carefully at
        # access_control_list. Notice DocumentAccess::to_acl prepends every
        # string with a type.
        access_control_list=list(chunk.access.to_acl()),
        global_boost=chunk.boost,
        semantic_identifier=chunk.source_document.semantic_identifier,
        image_file_id=chunk.image_file_id,
        source_links=json.dumps(chunk.source_links) if chunk.source_links else None,
        blurb=chunk.blurb,
        doc_summary=chunk.doc_summary,
        chunk_context=chunk.chunk_context,
        document_sets=list(chunk.document_sets) if chunk.document_sets else None,
        project_ids=list(chunk.user_project) if chunk.user_project else None,
        primary_owners=get_experts_stores_representations(
            chunk.source_document.primary_owners
        ),
        secondary_owners=get_experts_stores_representations(
            chunk.source_document.secondary_owners
        ),
        # TODO(andrei): Consider not even getting this from
        # DocMetadataAwareIndexChunk and instead using OpenSearchDocumentIndex's
        # instance variable. One source of truth -> less chance of a very bad
        # bug in prod.
        tenant_id=TenantState(tenant_id=chunk.tenant_id, multitenant=MULTI_TENANT),
    )


class OpenSearchOldDocumentIndex(OldDocumentIndex):
    """
    Wrapper for OpenSearch to adapt the new DocumentIndex interface with
    invocations to the old DocumentIndex interface in the hotpath.

    The analogous class for Vespa is VespaIndex which calls to
    VespaDocumentIndex.

    TODO(andrei): This is very dumb and purely temporary until there are no more
    references to the old interface in the hotpath.
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
        super().__init__(
            index_name=index_name,
            secondary_index_name=secondary_index_name,
        )
        if multitenant:
            raise ValueError(
                "Bug: OpenSearch is not yet ready for multitenant environments but something tried to use it."
            )
        self._real_index = OpenSearchDocumentIndex(
            index_name=index_name,
            # TODO(andrei): Sus. Do not plug this into production until all
            # instances where tenant ID is passed into a method call get
            # refactored to passing this data in on class init.
            tenant_state=TenantState(tenant_id="", multitenant=multitenant),
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
            old_count = index_batch_params.doc_id_to_previous_chunk_cnt[doc_id]
            new_count = index_batch_params.doc_id_to_new_chunk_cnt[doc_id]
            chunk_counts[doc_id] = IndexingMetadata.ChunkCounts(
                old_chunk_cnt=old_count,
                new_chunk_cnt=new_count,
            )

        indexing_metadata = IndexingMetadata(doc_id_to_chunk_cnt_diff=chunk_counts)

        results = self._real_index.index(chunks, indexing_metadata)

        # Convert list[DocumentInsertionRecord] to
        # set[OldDocumentInsertionRecord].
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

        return self._real_index.update([update_request])

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


class OpenSearchDocumentIndex(DocumentIndex):
    """OpenSearch-specific implementation of the DocumentIndex interface.

    This class provides document indexing, retrieval, and management operations
    for an OpenSearch search engine instance. It handles the complete lifecycle
    of document chunks within a specific OpenSearch index/schema.

    Although not yet used in this way in the codebase, each kind of embedding
    used should correspond to a different instance of this class, and therefore
    a different index in OpenSearch.
    """

    def __init__(
        self,
        index_name: str,
        tenant_state: TenantState,
    ) -> None:
        self._index_name: str = index_name
        self._tenant_state: TenantState = tenant_state
        self._os_client = OpenSearchClient(index_name=self._index_name)

    def verify_and_create_index_if_necessary(
        self, embedding_dim: int, embedding_precision: EmbeddingPrecision
    ) -> None:
        expected_mappings = DocumentSchema.get_document_schema(
            embedding_dim, self._tenant_state.multitenant
        )
        if not self._os_client.index_exists():
            self._os_client.create_index(
                mappings=expected_mappings,
                settings=DocumentSchema.get_index_settings(),
            )
        if not self._os_client.validate_index(
            expected_mappings=expected_mappings,
        ):
            raise RuntimeError(
                f"The index {self._index_name} is not valid. The expected mappings do not match the actual mappings."
            )

        self._os_client.create_search_pipeline(
            pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME,
            pipeline_body=MIN_MAX_NORMALIZATION_PIPELINE_CONFIG,
        )
        self._os_client.create_search_pipeline(
            pipeline_id=ZSCORE_NORMALIZATION_PIPELINE_NAME,
            pipeline_body=ZSCORE_NORMALIZATION_PIPELINE_CONFIG,
        )

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        indexing_metadata: IndexingMetadata,
    ) -> list[DocumentInsertionRecord]:
        # Set of doc IDs.
        unique_docs_to_be_indexed: set[str] = set()
        document_indexing_results: list[DocumentInsertionRecord] = []
        for chunk in chunks:
            document_insertion_record: DocumentInsertionRecord | None = None
            onyx_document: Document = chunk.source_document
            if onyx_document.id not in unique_docs_to_be_indexed:
                # If this is the first time we see this doc in this indexing
                # operation, first delete the doc's chunks from the index. This
                # is so that there are no dangling chunks in the index, in the
                # event that the new document's content contains fewer chunks
                # than the previous content.
                # TODO(andrei): This can possibly be made more efficient by
                # checking if the chunk count has actually decreased. This
                # assumes that overlapping chunks are perfectly overwritten. If
                # we can't guarantee that then we need the code as-is.
                unique_docs_to_be_indexed.add(onyx_document.id)
                num_chunks_deleted = self.delete(
                    onyx_document.id, onyx_document.chunk_count
                )
                # If we see that chunks were deleted we assume the doc already
                # existed.
                document_insertion_record = DocumentInsertionRecord(
                    document_id=onyx_document.id,
                    already_existed=num_chunks_deleted > 0,
                )

            opensearch_document_chunk = _convert_onyx_chunk_to_opensearch_document(
                chunk
            )
            # TODO(andrei): After our client supports batch indexing, use that
            # here.
            self._os_client.index_document(opensearch_document_chunk)

            if document_insertion_record is not None:
                # Only add records once per doc. This object is not None only if
                # we've seen this doc for the first time in this for-loop.
                document_indexing_results.append(document_insertion_record)

        return document_indexing_results

    def delete(self, document_id: str, chunk_count: int | None = None) -> int:
        """Deletes all chunks for a given document.

        TODO(andrei): Make this method require supplying source type.
        TODO(andrei): Consider implementing this method to delete on document
        chunk IDs vs querying for matching document chunks.

        Args:
            document_id: The ID of the document to delete.
            chunk_count: The number of chunks in OpenSearch for the document.
                Defaults to None.

        Raises:
            RuntimeError: Failed to delete some or all of the chunks for the
                document.

        Returns:
            The number of chunks successfully deleted.
        """
        query_body = DocumentQuery.delete_from_document_id_query(
            document_id=document_id,
            tenant_state=self._tenant_state,
        )

        return self._os_client.delete_by_query(query_body)

    def update(
        self,
        update_requests: list[MetadataUpdateRequest],
    ) -> None:
        """Updates some set of chunks.

        NOTE: Requires document chunk count be known; will raise if it is not.
        NOTE: Each update request must have some field to update; if not it is
        assumed there is a bug in the caller and this will raise.

        TODO(andrei): Consider exploring a batch API for OpenSearch for this
        operation.

        Args:
            update_requests: A list of update requests, each containing a list
                of document IDs and the fields to update. The field updates
                apply to all of the specified documents in each update request.

        Raises:
            RuntimeError: Failed to update some or all of the chunks for the
                specified documents.
        """
        for update_request in update_requests:
            properties_to_update: dict[str, Any] = dict()
            # TODO(andrei): Nit but consider if we can use DocumentChunk
            # here so we don't have to think about passing in the
            # appropriate types into this dict.
            if update_request.access is not None:
                properties_to_update[ACCESS_CONTROL_LIST_FIELD_NAME] = list(
                    update_request.access.to_acl()
                )
            if update_request.document_sets is not None:
                properties_to_update[DOCUMENT_SETS_FIELD_NAME] = list(
                    update_request.document_sets
                )
            if update_request.boost is not None:
                properties_to_update[GLOBAL_BOOST_FIELD_NAME] = int(
                    update_request.boost
                )
            if update_request.hidden is not None:
                properties_to_update[HIDDEN_FIELD_NAME] = update_request.hidden
            if update_request.project_ids is not None:
                properties_to_update[PROJECT_IDS_FIELD_NAME] = list(
                    update_request.project_ids
                )

            for doc_id in update_request.document_ids:
                if not properties_to_update:
                    raise ValueError(
                        f"Bug: Tried to update document {doc_id} with no updated fields or user fields."
                    )

                doc_chunk_count = update_request.doc_id_to_chunk_cnt.get(doc_id, -1)
                if doc_chunk_count < 0:
                    raise ValueError(
                        f"Tried to update document {doc_id} but its chunk count is not known. Older versions of the "
                        "application used to permit this but is not a supported state for a document when using OpenSearch."
                    )
                if doc_chunk_count == 0:
                    raise ValueError(
                        f"Bug: Tried to update document {doc_id} but its chunk count was 0."
                    )

                for chunk_index in range(doc_chunk_count):
                    document_chunk_id = get_opensearch_doc_chunk_id(
                        document_id=doc_id, chunk_index=chunk_index
                    )
                    self._os_client.update_document(
                        document_chunk_id=document_chunk_id,
                        properties_to_update=properties_to_update,
                    )

    def id_based_retrieval(
        self,
        chunk_requests: list[DocumentSectionRequest],
        # TODO(andrei): When going over ACL look very carefully at
        # access_control_list. Notice DocumentAccess::to_acl prepends every
        # string with a type.
        filters: IndexFilters,
        # TODO(andrei): Remove this from the new interface at some point; we
        # should not be exposing this.
        batch_retrieval: bool = False,
    ) -> list[InferenceChunk]:
        """
        TODO(andrei): Consider implementing this method to retrieve on document
        chunk IDs vs querying for matching document chunks.
        """
        results: list[InferenceChunk] = []
        for chunk_request in chunk_requests:
            document_chunks: list[DocumentChunk] = []
            query_body = DocumentQuery.get_from_document_id_query(
                document_id=chunk_request.document_id,
                tenant_state=self._tenant_state,
                max_chunk_size=chunk_request.max_chunk_size,
                min_chunk_index=chunk_request.min_chunk_ind,
                max_chunk_index=chunk_request.max_chunk_ind,
            )
            document_chunks = self._os_client.search(
                body=query_body,
                search_pipeline_id=None,
            )
            inference_chunks_uncleaned: list[InferenceChunkUncleaned] = [
                _convert_opensearch_chunk_to_inference_chunk_uncleaned(document_chunk)
                for document_chunk in document_chunks
            ]
            inference_chunks: list[InferenceChunk] = cleanup_content_for_chunks(
                inference_chunks_uncleaned
            )
            results.extend(inference_chunks)
        return results

    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        query_type: QueryType,
        # TODO(andrei): When going over ACL look very carefully at
        # access_control_list. Notice DocumentAccess::to_acl prepends every
        # string with a type.
        filters: IndexFilters,
        num_to_retrieve: int,
        offset: int = 0,
    ) -> list[InferenceChunk]:
        query_body = DocumentQuery.get_hybrid_search_query(
            query_text=query,
            query_vector=query_embedding,
            num_candidates=1000,  # TODO(andrei): Magic number.
            num_hits=num_to_retrieve,
            tenant_state=self._tenant_state,
        )
        document_chunks: list[DocumentChunk] = self._os_client.search(
            body=query_body,
            search_pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME,
        )
        inference_chunks_uncleaned: list[InferenceChunkUncleaned] = [
            _convert_opensearch_chunk_to_inference_chunk_uncleaned(document_chunk)
            for document_chunk in document_chunks
        ]
        inference_chunks: list[InferenceChunk] = cleanup_content_for_chunks(
            inference_chunks_uncleaned
        )

        return inference_chunks

    def random_retrieval(
        self,
        # TODO(andrei): When going over ACL look very carefully at
        # access_control_list. Notice DocumentAccess::to_acl prepends every
        # string with a type.
        filters: IndexFilters,
        num_to_retrieve: int = 100,
        dirty: bool | None = None,
    ) -> list[InferenceChunk]:
        raise NotImplementedError(
            "[ANDREI]: Random retrieval is not implemented for OpenSearch."
        )
